from datetime import timedelta
from decimal import Decimal

from django import forms
from django.conf import settings
from django.utils import timezone
from django.utils.crypto import get_random_string

from .models import (
    DIAS_SEMANA, Agendamento, Candidatura, Configuracao, Curso, DiaSemEstagio, Documento, Estagio, LocalEstagio,
    Mensagem, Registro, Usuario,
)
from .validators import limpar_cep, limpar_cnpj_ou_cpf, limpar_cpf

HORAS_DIA = [("4", "4 horas"), ("6", "6 horas"), ("8", "8 horas")]
MAX_FOTO_MB = 5
MAX_CURRICULO_MB = 5


def horas_str(valor):
    """Decimal('8.00') -> '8' para casar com as opções do select."""
    if valor in (None, ""):
        return valor
    d = Decimal(str(valor))
    return str(int(d)) if d == d.to_integral_value() else str(d.normalize())


def campo_horas(label="Carga horária por dia", initial="8"):
    return forms.TypedChoiceField(label=label, choices=HORAS_DIA, coerce=Decimal, initial=initial,
                                  help_text="Acima de 4 horas há direito a intervalo.")


def _ajustar_choices_horas(form, nome="horas_por_dia"):
    """Garante que um valor antigo fora de 4/6/8 continue aparecendo no select."""
    campo = form.fields.get(nome)
    if not campo:
        return
    atual = horas_str(form.initial.get(nome) if form.initial.get(nome) is not None else campo.initial)
    if atual is not None:
        form.initial[nome] = atual
        if atual not in {v for v, _ in campo.choices}:
            campo.choices = [*campo.choices, (atual, f"{atual} horas")]


def _minutos(t):
    return t.hour * 60 + t.minute


def _fmt_horas(minutos):
    h, m = divmod(minutos, 60)
    return f"{h}h{m:02d}" if m else f"{h}h"


class DataInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kw):
        super().__init__(format="%Y-%m-%d", **kw)


class HoraInput(forms.TimeInput):
    input_type = "time"

    def __init__(self, **kw):
        super().__init__(format="%H:%M", **kw)


class DataHoraInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, **kw):
        super().__init__(format="%Y-%m-%dT%H:%M", **kw)


def _ajustar_widgets(form):
    for campo in form.fields.values():
        w = campo.widget
        if isinstance(w, forms.Textarea):
            w.attrs.setdefault("rows", 3)


class Formulario(forms.Form):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        _ajustar_widgets(self)


class FormularioModelo(forms.ModelForm):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        _ajustar_widgets(self)


class DiasField(forms.TypedMultipleChoiceField):
    def __init__(self, **kw):
        kw.setdefault("label", "Dias de estágio")
        super().__init__(choices=DIAS_SEMANA, coerce=int, widget=forms.CheckboxSelectMultiple, **kw)


# ------------------------------------------------------------------ escalas


CAMPOS_ESCALA = ["dias", "horas_por_dia", "horario_entrada", "saida_intervalo", "volta_intervalo", "horario_saida"]


class CamposEscalaMixin(forms.Form):
    dias = DiasField(initial=[0, 1])
    horas_por_dia = campo_horas()
    horario_entrada = forms.TimeField(label="Entrada", required=False, widget=HoraInput())
    saida_intervalo = forms.TimeField(label="Saída p/ intervalo", required=False, widget=HoraInput(attrs={"data-intervalo": "1"}))
    volta_intervalo = forms.TimeField(label="Volta do intervalo", required=False, widget=HoraInput(attrs={"data-intervalo": "1"}))
    horario_saida = forms.TimeField(label="Saída", required=False, widget=HoraInput())

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        _ajustar_choices_horas(self)

    def clean(self):
        dados = super().clean()
        ent, si, vi, sai = (dados.get(k) for k in ("horario_entrada", "saida_intervalo", "volta_intervalo", "horario_saida"))
        horas = dados.get("horas_por_dia")
        if bool(si) != bool(vi):
            self.add_error("volta_intervalo" if si else "saida_intervalo", "Informe a saída e a volta do intervalo.")
            return dados
        sequencia = [t for t in (ent, si, vi, sai) if t]
        if any(b <= a for a, b in zip(sequencia, sequencia[1:])):
            self.add_error("horario_saida", "Os horários devem estar em ordem: entrada, intervalo e saída.")
            return dados
        if horas and ent and sai:
            trabalhado = (_minutos(si) - _minutos(ent)) + (_minutos(sai) - _minutos(vi)) if si else _minutos(sai) - _minutos(ent)
            if trabalhado != int(horas * 60):
                self.add_error("horario_saida", f"Os horários somam {_fmt_horas(trabalhado)}, mas a carga diária é de "
                                                f"{_fmt_horas(int(horas * 60))}. Confira.")
        return dados

    def dados_escala(self):
        d = self.cleaned_data
        return {
            "dias": ",".join(str(x) for x in sorted(d["dias"])),
            "horario_entrada": d.get("horario_entrada"),
            "saida_intervalo": d.get("saida_intervalo"),
            "volta_intervalo": d.get("volta_intervalo"),
            "horario_saida": d.get("horario_saida"),
            "horas_por_dia": d["horas_por_dia"],
        }


class EscalaLoteForm(CamposEscalaMixin, Formulario):
    estagios = forms.ModelMultipleChoiceField(
        queryset=Estagio.objects.none(), widget=forms.CheckboxSelectMultiple, label="Estagiários"
    )
    vigente_desde = forms.DateField(label="Vale a partir de", widget=DataInput())

    field_order = ["vigente_desde", *CAMPOS_ESCALA, "estagios"]

    def __init__(self, *a, estagios_qs=None, **kw):
        super().__init__(*a, **kw)
        self.fields["estagios"].queryset = estagios_qs
        self.fields["estagios"].label_from_instance = lambda e: f"{e.estagiario} — {e.curso} · {e.local or 'sem local'}"


# ------------------------------------------------------------------ contas


class EstagiariosLoteForm(CamposEscalaMixin, Formulario):
    nomes = forms.CharField(
        label="Estagiários (um por linha)",
        widget=forms.Textarea(attrs={"rows": 8, "placeholder": "Maria da Silva Souza\nJoão Pedro Lima; 2024001234"}),
        help_text="Nome completo por linha. Opcional: “; matrícula” depois do nome.",
    )
    curso = forms.ModelChoiceField(queryset=Curso.objects.all())
    turma = forms.CharField(required=False, max_length=40)
    local = forms.ModelChoiceField(queryset=LocalEstagio.objects.all(), required=False, label="Concedente")
    supervisor = forms.ModelChoiceField(
        queryset=Usuario.objects.filter(papel=Usuario.Papel.SUPERVISOR, is_active=True), required=False
    )
    setor = forms.CharField(required=False, max_length=100)
    data_inicio = forms.DateField(label="Início do estágio", widget=DataInput())
    data_fim = forms.DateField(label="Término previsto no termo", widget=DataInput(), required=False)

    field_order = ["nomes", "curso", "turma", "local", "setor", "supervisor", "data_inicio", "data_fim", *CAMPOS_ESCALA]

    orientador = forms.ModelChoiceField(
        queryset=Usuario.objects.filter(papel=Usuario.Papel.ORIENTADOR, is_active=True), required=False,
        label="Orientador(a) responsável",
    )

    def __init__(self, *a, usuario=None, **kw):
        super().__init__(*a, **kw)
        self.fields["supervisor"].label_from_instance = lambda u: f"{u} ({u.local or 'sem local'})"
        # o orientador cadastra os próprios estagiários; o coordenador escolhe o orientador
        if usuario is not None and usuario.is_orientador:
            del self.fields["orientador"]
        else:
            self.fields["orientador"].required = True
            self.order_fields(["nomes", "curso", "orientador"])
        if usuario is not None and usuario.is_coordenador and usuario.cursos_ids():
            self.fields["curso"].queryset = Curso.objects.filter(pk__in=usuario.cursos_ids())

    def clean_nomes(self):
        linhas = []
        for bruto in self.cleaned_data["nomes"].splitlines():
            if not bruto.strip():
                continue
            nome, _, matricula = bruto.partition(";")
            nome = " ".join(nome.split())
            if len(nome.split()) < 2:
                raise forms.ValidationError(f"Informe nome e sobrenome: “{nome}”.")
            linhas.append((nome, matricula.strip()))
        if not linhas:
            raise forms.ValidationError("Informe ao menos um nome.")
        return linhas


class SupervisoresLoteForm(Formulario):
    nomes = forms.CharField(
        label="Supervisores (um por linha)",
        widget=forms.Textarea(attrs={"rows": 5, "placeholder": "Ana Beatriz Rocha; (85) 99999-0000"}),
        help_text="Nome completo por linha. Opcional: “; telefone” depois do nome.",
    )
    local = forms.ModelChoiceField(queryset=LocalEstagio.objects.all(), label="Concedente")
    cargo = forms.CharField(required=False, max_length=80, label="Cargo/Função")

    def clean_nomes(self):
        return self.clean_nomes_texto(self.cleaned_data["nomes"])

    @staticmethod
    def clean_nomes_texto(texto, obrigatorio=True):
        linhas = []
        for bruto in texto.splitlines():
            if not bruto.strip():
                continue
            nome, _, tel = bruto.partition(";")
            nome = " ".join(nome.split())
            if len(nome.split()) < 2:
                raise forms.ValidationError(f"Informe nome e sobrenome: “{nome}”.")
            linhas.append((nome, tel.strip()))
        if not linhas and obrigatorio:
            raise forms.ValidationError("Informe ao menos um nome.")
        return linhas


class OrientadorForm(Formulario):
    nome = forms.CharField(label="Nome completo", max_length=150)
    email = forms.EmailField(required=False)


class CoordenadorForm(Formulario):
    nome = forms.CharField(label="Nome completo", max_length=150)
    email = forms.EmailField(required=False)
    telefone = forms.CharField(required=False, max_length=30)
    cursos = forms.ModelMultipleChoiceField(
        queryset=Curso.objects.all(), required=False, widget=forms.CheckboxSelectMultiple, label="Cursos que coordena",
        help_text="Vê e gerencia só os estágios desses cursos. Sem nenhum marcado, vê todos.",
    )


class UsuarioEditForm(FormularioModelo):
    class Meta:
        model = Usuario
        fields = ["nome_completo", "email", "telefone", "cpf", "matricula", "cargo", "local", "cursos_coordenados",
                  "is_active"]
        labels = {"is_active": "Conta ativa", "local": "Concedente"}
        widgets = {"cursos_coordenados": forms.CheckboxSelectMultiple}

    def clean_cpf(self):
        return limpar_cpf(self.cleaned_data.get("cpf"))


class PerfilForm(FormularioModelo):
    """Cada pessoa edita os próprios dados. Os campos mudam conforme o papel."""

    CAMPOS_CURRICULO = ["apresentacao", "habilidades", "curriculo", "perfil_visivel"]

    class Meta:
        model = Usuario
        fields = ["foto", "email", "telefone", "cpf", "cargo", "apresentacao", "habilidades", "curriculo", "perfil_visivel"]
        labels = {"foto": "Foto de perfil", "telefone": "Telefone / WhatsApp", "cargo": "Cargo/Função"}
        widgets = {"foto": forms.ClearableFileInput(attrs={"accept": "image/*"}),
                   "curriculo": forms.ClearableFileInput(attrs={"accept": "application/pdf,.pdf"}),
                   "apresentacao": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *a, curriculos=False, **kw):
        super().__init__(*a, **kw)
        u = self.instance
        self._antigos = {"foto": u.foto.name if u.foto else "", "curriculo": u.curriculo.name if u.curriculo else ""}
        self.fields["foto"].help_text = f"JPG ou PNG, até {MAX_FOTO_MB} MB. A foto é recortada em quadrado."
        if not u.is_supervisor:
            del self.fields["cargo"]
        if not u.is_estagiario:
            del self.fields["cpf"]
        else:
            self.fields["cpf"].help_text = "Sai na sua folha de frequência."
        if not (u.is_estagiario and curriculos):
            for nome in self.CAMPOS_CURRICULO:
                del self.fields[nome]
        else:
            self.fields["curriculo"].help_text = f"Somente PDF, até {MAX_CURRICULO_MB} MB."

    @property
    def tem_curriculo(self):
        return "curriculo" in self.fields

    def campos_contato(self):
        return [self[n] for n in self.fields if n not in self.CAMPOS_CURRICULO and n != "foto"]

    def campos_curriculo(self):
        return [self[n] for n in self.CAMPOS_CURRICULO if n in self.fields]

    def clean_cpf(self):
        return limpar_cpf(self.cleaned_data.get("cpf"))

    def clean_foto(self):
        foto = self.cleaned_data.get("foto")
        if foto and hasattr(foto, "content_type") and foto.size > MAX_FOTO_MB * 1024 * 1024:
            raise forms.ValidationError(f"A foto deve ter no máximo {MAX_FOTO_MB} MB.")
        return foto

    def clean_curriculo(self):
        arq = self.cleaned_data.get("curriculo")
        if arq and hasattr(arq, "content_type"):
            if arq.size > MAX_CURRICULO_MB * 1024 * 1024:
                raise forms.ValidationError(f"O currículo deve ter no máximo {MAX_CURRICULO_MB} MB.")
            inicio = arq.read(5)
            arq.seek(0)
            if inicio != b"%PDF-":
                raise forms.ValidationError("Envie o currículo em PDF.")
            arq.name = f"{get_random_string(12)}.pdf"
        return arq

    def save(self, commit=True):
        from .services import processar_foto

        user = super().save(commit=False)
        nova_foto = self.cleaned_data.get("foto")
        if "foto" in self.changed_data and nova_foto:
            user.foto = processar_foto(nova_foto)
        if commit:
            user.save()
            for campo, antigo in self._antigos.items():
                atual = getattr(user, campo)
                if campo in self.fields and antigo and (not atual or atual.name != antigo):
                    Usuario._meta.get_field(campo).storage.delete(antigo)
        return user


class ConfiguracaoForm(FormularioModelo):
    class Meta:
        model = Configuracao
        fields = ["nome_escola", "municipio_escola", "cabecalho_folha", "logo_folha",
                  "captacao_aberta", "ano_captacao", "captacao_prazo", "texto_captacao",
                  "curriculos_habilitados", "banco_talentos_habilitado"]
        widgets = {"logo_folha": forms.ClearableFileInput(attrs={"accept": "image/*"}), "captacao_prazo": DataInput(),
                   "texto_captacao": forms.Textarea(attrs={"rows": 3})}

    def clean_logo_folha(self):
        logo = self.cleaned_data.get("logo_folha")
        if logo and hasattr(logo, "content_type") and logo.size > 2 * 1024 * 1024:
            raise forms.ValidationError("O logotipo deve ter no máximo 2 MB.")
        return logo


# ------------------------------------------------------------------ cadastros


class CursoForm(FormularioModelo):
    class Meta:
        model = Curso
        fields = ["nome", "carga_horaria", "horas_por_dia_padrao"]


class LocalForm(FormularioModelo):
    """Ficha de cadastro de concedente (mesmos campos do formulário da SEDUC)."""

    SECOES = [
        ("Dados gerais", ["tipo_concedente", "razao_social", "nome", "tipo_instituicao", "atividade", "cnpj", "matriz_filial"]),
        ("Endereço", ["endereco", "numero", "bairro", "complemento", "cidade", "uf", "cep", "telefone", "link_mapa"]),
        ("Representante legal", ["representante_nome", "representante_email", "representante_cpf", "representante_documento"]),
        ("Supervisores", ["novos_supervisores"]),
        ("Outras informações", ["observacoes"]),
    ]
    novos_supervisores = forms.CharField(
        label="Cadastrar supervisores desta concedente", required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Ana Beatriz Rocha; (85) 99999-0000"}),
        help_text="Um por linha: nome completo e, se quiser, “; telefone”. O restante o próprio supervisor completa no perfil.",
    )

    class Meta:
        model = LocalEstagio
        fields = [
            "tipo_concedente", "razao_social", "nome", "tipo_instituicao", "atividade", "cnpj", "matriz_filial",
            "endereco", "numero", "bairro", "complemento", "cidade", "uf", "cep", "telefone", "link_mapa",
            "representante_nome", "representante_email", "representante_cpf", "representante_documento", "observacoes",
        ]
        widgets = {
            "tipo_concedente": forms.RadioSelect, "tipo_instituicao": forms.RadioSelect, "matriz_filial": forms.RadioSelect,
            "atividade": forms.Textarea(attrs={"rows": 2}),
        }
        labels = {"endereco": "Endereço (rua, avenida…)"}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        for nome in ("tipo_instituicao", "matriz_filial"):
            self.fields[nome].choices = [c for c in self.fields[nome].choices if c[0]]
        self.fields["uf"].widget.attrs.update({"maxlength": 2, "style": "text-transform:uppercase"})

    def secoes(self):
        return [(titulo, [self[n] for n in campos if n in self.fields]) for titulo, campos in self.SECOES]

    def clean_cnpj(self):
        return limpar_cnpj_ou_cpf(self.cleaned_data.get("cnpj"))

    def clean_representante_cpf(self):
        return limpar_cpf(self.cleaned_data.get("representante_cpf"))

    def clean_cep(self):
        return limpar_cep(self.cleaned_data.get("cep"))

    def clean_uf(self):
        return (self.cleaned_data.get("uf") or "").upper()

    def clean_novos_supervisores(self):
        return SupervisoresLoteForm.clean_nomes_texto(self.cleaned_data.get("novos_supervisores", ""), obrigatorio=False)


class DiaSemEstagioForm(FormularioModelo):
    ate = forms.DateField(label="Até (opcional, para períodos)", required=False, widget=DataInput())

    class Meta:
        model = DiaSemEstagio
        fields = ["data", "ate", "descricao", "curso"]
        widgets = {"data": DataInput()}
        labels = {"data": "Data"}


class EstagioForm(FormularioModelo):
    class Meta:
        model = Estagio
        fields = [
            "curso", "turma", "local", "setor", "supervisor", "data_inicio", "data_fim", "carga_horaria",
            "horas_anteriores", "ativo", "observacoes_orientador",
        ]
        widgets = {"data_inicio": DataInput(), "data_fim": DataInput()}
        labels = {"local": "Concedente", "data_fim": "Término previsto no termo"}
        help_texts = {"data_fim": "Só informativo: a previsão real é calculada pelas horas que faltam."}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["supervisor"].queryset = Usuario.objects.filter(papel=Usuario.Papel.SUPERVISOR, is_active=True)
        self.fields["supervisor"].label_from_instance = lambda u: f"{u} ({u.local or 'sem local'})"


class EscalaForm(CamposEscalaMixin, Formulario):
    vigente_desde = forms.DateField(label="Vale a partir de", widget=DataInput())
    field_order = ["vigente_desde", *CAMPOS_ESCALA]


# ------------------------------------------------------------------ dia a dia


class AusenciaForm(Formulario):
    data = forms.DateField(widget=DataInput(), label="Dia")
    motivo = forms.CharField(widget=forms.Textarea, label="Motivo")

    def clean_data(self):
        d = self.cleaned_data["data"]
        hoje = timezone.localdate()
        if d < hoje - timedelta(days=7):
            raise forms.ValidationError("Só é possível informar ausências dos últimos 7 dias. Fale com o orientador.")
        return d


class PlanejarDiaForm(Formulario):
    """Estagiário avisa que vai estagiar num dia fora da escala (reposição) ou com outra carga."""

    horas = campo_horas("Quantas horas vai estagiar")
    motivo = forms.CharField(label="Observação (opcional)", required=False, max_length=160,
                             widget=forms.TextInput(attrs={"placeholder": "Ex.: reposição do dia 20/11"}))

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["horas"].help_text = ""
        _ajustar_choices_horas(self, "horas")


class DiarioForm(Formulario):
    diario = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "O que você fez, aprendeu ou teve dificuldade hoje?"}),
        required=False, label="Como foi o dia",
    )


class LancamentoForm(FormularioModelo):
    """Supervisor ou orientador lança/ajusta o registro de um dia."""

    class Meta:
        model = Registro
        fields = ["situacao", "horas", "hora_chegada", "saida_intervalo", "volta_intervalo", "hora_saida",
                  "confirmacao", "motivo", "obs_supervisor"]
        widgets = {"hora_chegada": HoraInput(), "saida_intervalo": HoraInput(), "volta_intervalo": HoraInput(),
                   "hora_saida": HoraInput()}
        labels = {"confirmacao": "Validação"}


class MensagemForm(FormularioModelo):
    class Meta:
        model = Mensagem
        fields = ["texto", "privada_orientador"]
        widgets = {"texto": forms.Textarea(attrs={"rows": 3, "placeholder": "Escreva sua dúvida ou mensagem…"})}
        labels = {"texto": ""}


class DocumentoForm(FormularioModelo):
    class Meta:
        model = Documento
        fields = ["titulo", "categoria", "arquivo", "descricao"]

    def clean_arquivo(self):
        arq = self.cleaned_data["arquivo"]
        if arq and arq.size > settings.TAMANHO_MAX_ANEXO_MB * 1024 * 1024:
            raise forms.ValidationError(f"O arquivo deve ter no máximo {settings.TAMANHO_MAX_ANEXO_MB} MB.")
        return arq


class DocumentoGeralForm(DocumentoForm):
    class Meta(DocumentoForm.Meta):
        fields = ["titulo", "categoria", "arquivo", "descricao", "estagio", "curso"]
        labels = {"estagio": "Para um estagiário específico", "curso": "Ou para todo um curso"}

    def __init__(self, *a, estagios_qs=None, **kw):
        super().__init__(*a, **kw)
        self.fields["estagio"].queryset = estagios_qs
        self.fields["estagio"].label_from_instance = lambda e: str(e.estagiario)
        self.fields["estagio"].empty_label = "Todos os meus estagiários"
        self.fields["curso"].empty_label = "Todos os cursos"


# ------------------------------------------------------------------ agendamentos


class SolicitacaoForm(FormularioModelo):
    """Estagiário ou supervisor pede uma visita ou conversa."""

    class Meta:
        model = Agendamento
        fields = ["tipo", "modalidade", "assunto", "detalhes", "data_sugerida", "estagios"]
        widgets = {"estagios": forms.CheckboxSelectMultiple}
        labels = {"estagios": "Sobre quais estagiários"}

    def __init__(self, *a, estagios_qs=None, **kw):
        super().__init__(*a, **kw)
        self.fields["estagios"].queryset = estagios_qs
        self.fields["estagios"].label_from_instance = lambda e: str(e.estagiario)
        self.fields["data_sugerida"].widget.attrs["placeholder"] = "Ex.: quinta à tarde, ou 20/11 às 14h"
        if estagios_qs is not None and estagios_qs.count() == 1:
            self.fields["estagios"].widget = forms.MultipleHiddenInput()
            self.initial["estagios"] = list(estagios_qs)


class AgendamentoForm(FormularioModelo):
    """Orientador cria ou gerencia um agendamento."""

    class Meta:
        model = Agendamento
        fields = ["tipo", "modalidade", "status", "data_hora", "local", "estagios", "assunto", "detalhes", "relato"]
        widgets = {"estagios": forms.CheckboxSelectMultiple, "data_hora": DataHoraInput()}

    def __init__(self, *a, estagios_qs=None, **kw):
        super().__init__(*a, **kw)
        self.fields["estagios"].queryset = estagios_qs
        self.fields["estagios"].label_from_instance = lambda e: f"{e.estagiario} · {e.local or 'sem local'}"
        self.fields["data_hora"].input_formats = ["%Y-%m-%dT%H:%M"]
        if not self.instance.pk:
            self.fields["status"].initial = Agendamento.Status.AGENDADO

    def clean(self):
        d = super().clean()
        if d.get("status") == Agendamento.Status.AGENDADO and not d.get("data_hora"):
            self.add_error("data_hora", "Informe a data e hora para agendar.")
        return d


# ------------------------------------------------------------------ captação de concedentes


class CandidaturaForm(LocalForm):
    """Formulário público: a concedente se candidata a receber estagiários num ano letivo."""

    SECOES = [
        ("Dados gerais", ["tipo_concedente", "razao_social", "nome", "tipo_instituicao", "atividade", "cnpj", "matriz_filial"]),
        ("Endereço", ["endereco", "numero", "bairro", "complemento", "cidade", "uf", "cep", "telefone"]),
        ("Representante legal", ["representante_nome", "representante_email", "representante_cpf", "representante_documento"]),
        ("Quem está preenchendo (vamos falar com esta pessoa)", ["contato_nome", "contato_cargo", "contato_telefone",
                                                                  "contato_whatsapp", "contato_email"]),
        ("Vagas", ["VAGAS"]),
        ("Proposta de estágio", ["atividades", "turnos", "horario", "beneficios"]),
        ("Supervisor(a) dos estagiários", ["supervisor_nome", "supervisor_cargo", "supervisor_telefone", "supervisor_email"]),
        ("Outras informações", ["observacoes", "consentimento"]),
    ]
    turnos = forms.MultipleChoiceField(choices=Candidatura.TURNOS, widget=forms.CheckboxSelectMultiple, required=False,
                                       label="Turnos disponíveis")
    consentimento = forms.BooleanField(
        label="Declaro que as informações são verdadeiras e autorizo a escola a usá-las para organizar o estágio.",
    )
    site = forms.CharField(required=False, label="Deixe em branco", widget=forms.TextInput(attrs={"autocomplete": "off",
                                                                                                    "tabindex": "-1"}))

    class Meta(LocalForm.Meta):
        model = Candidatura
        fields = [*LocalForm.Meta.fields, "contato_nome", "contato_cargo", "contato_telefone", "contato_whatsapp",
                  "contato_email", "atividades", "horario", "beneficios", "supervisor_nome", "supervisor_cargo",
                  "supervisor_telefone", "supervisor_email"]
        fields.remove("link_mapa")
        labels = {**LocalForm.Meta.labels, "observacoes": "Algo mais que a escola deva saber?"}
        widgets = {**LocalForm.Meta.widgets, "atividades": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        del self.fields["novos_supervisores"]
        self.fields["razao_social"].required = True
        self.fields["razao_social"].help_text = ""
        self.fields["atividades"].widget.attrs["placeholder"] = "Ex.: apoio no atendimento ao público, organização de arquivos, suporte de informática…"
        self.cursos = list(Curso.objects.all())
        for c in self.cursos:
            self.fields[f"vaga_{c.pk}"] = forms.IntegerField(
                label=c.nome, min_value=0, max_value=99, required=False,
                widget=forms.NumberInput(attrs={"placeholder": "0", "inputmode": "numeric"}),
            )

    def secoes(self):
        resultado = []
        for titulo, campos in self.SECOES:
            nomes = [f"vaga_{c.pk}" for c in self.cursos] if campos == ["VAGAS"] else campos
            resultado.append((titulo, [self[n] for n in nomes if n in self.fields]))
        return resultado

    def clean_turnos(self):
        return ",".join(self.cleaned_data.get("turnos") or [])

    def clean_supervisor_nome(self):
        nome = " ".join((self.cleaned_data.get("supervisor_nome") or "").split())
        if nome and len(nome.split()) < 2:
            raise forms.ValidationError("Informe nome e sobrenome.")
        return nome

    def clean(self):
        dados = super().clean()
        if dados.get("site"):
            raise forms.ValidationError("Não foi possível enviar o cadastro.")
        self.vagas = {c: dados.get(f"vaga_{c.pk}") or 0 for c in self.cursos}
        if not any(self.vagas.values()):
            raise forms.ValidationError("Informe quantos estagiários deseja em pelo menos um curso.")
        return dados

    def save(self, commit=True):
        cand = forms.ModelForm.save(self, commit=False)
        cand.turnos = self.cleaned_data["turnos"]
        if commit:
            cand.save()
            from .models import VagaCandidatura

            VagaCandidatura.objects.bulk_create(
                [VagaCandidatura(candidatura=cand, curso=c, quantidade=q) for c, q in self.vagas.items() if q]
            )
        return cand


class AprovarCandidaturaForm(Formulario):
    destino = forms.ChoiceField(label="Cadastrar como", widget=forms.RadioSelect)
    criar_supervisor = forms.BooleanField(required=False, initial=True,
                                          label="Criar a conta do supervisor indicado")
    parecer = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}), label="Observação (opcional)")

    def __init__(self, *a, candidatura=None, sugestoes=(), **kw):
        super().__init__(*a, **kw)
        self.fields["destino"].choices = [("nova", "Nova concedente")] + [
            (str(l.pk), f"Atualizar a concedente já cadastrada: {l}") for l in sugestoes
        ]
        self.fields["destino"].initial = str(sugestoes[0].pk) if sugestoes else "nova"
        if not candidatura.supervisor_nome:
            del self.fields["criar_supervisor"]
        else:
            self.fields["criar_supervisor"].label = f"Criar a conta do supervisor indicado ({candidatura.supervisor_nome})"


class RecusarCandidaturaForm(Formulario):
    parecer = forms.CharField(label="Motivo (vai na mensagem para a concedente)", widget=forms.Textarea(attrs={"rows": 3}))
