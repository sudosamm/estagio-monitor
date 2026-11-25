import re
from datetime import date, datetime, timedelta
from decimal import Decimal

from django import forms
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from django.utils.crypto import get_random_string

from .models import (
    DIAS_SEMANA, Agendamento, Candidatura, Configuracao, Curso, DiaSemEstagio, Documento, Estagio, FolhaEnviada,
    Feedback, Justificativa, LocalEstagio, Mensagem, PerguntaAvaliacao, Sugestao, Registro, TipoDocumento, Turma, Usuario, horas_dos_horarios,
)
from .validators import limpar_cep, limpar_cnpj_ou_cpf, limpar_cpf

MAX_FOTO_MB = 5
MAX_CURRICULO_MB = 5


def horas_str(valor):
    """Decimal('8.00') -> '8' para casar com as opções do select."""
    if valor in (None, ""):
        return valor
    d = Decimal(str(valor))
    return str(int(d)) if d == d.to_integral_value() else str(d.normalize())


def campo_horas(label="Horas por dia", required=True,
                help_text="Qualquer carga: 4, 5, 6, 7, 8… (5,5 = 5h30). Com entrada e saída preenchidas, pode deixar "
                          "vazio: é calculada pelos horários."):
    return forms.DecimalField(
        label=label, required=required, min_value=Decimal("0.5"), max_value=Decimal("12"), decimal_places=2,
        help_text=help_text, localize=True,
        widget=forms.TextInput(attrs={"inputmode": "decimal", "placeholder": "Ex.: 4, 5 ou 7", "size": 6,
                                      "data-horas-dia": "1"}),
    )


def _ajustar_choices_horas(form, nome="horas_por_dia"):
    """Mostra '7' em vez de '7.00' no valor inicial."""
    if nome in form.fields and form.initial.get(nome) is not None:
        form.initial[nome] = horas_str(form.initial[nome]).replace(".", ",")


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


class SupervisorSelect(forms.Select):
    """Cada opção leva as concedentes do supervisor, para o JS mostrar só os da concedente escolhida."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        opcao = super().create_option(name, value, label, selected, index, subindex, attrs)
        usuario = getattr(value, "instance", None)
        if usuario is not None:
            opcao["attrs"]["data-concedentes"] = ",".join(str(c.pk) for c in usuario.concedentes.all())
        return opcao


def supervisores_qs():
    return Usuario.objects.filter(papel=Usuario.Papel.SUPERVISOR, is_active=True).prefetch_related("concedentes")


def concedentes_ativas(atual=None):
    """Concedentes ativas (mais a atual do estágio, mesmo que tenha sido desativada)."""
    if atual is not None and atual.pk:
        return LocalEstagio.objects.filter(Q(ativa=True) | Q(pk=atual.pk))
    return LocalEstagio.objects.filter(ativa=True)


def turmas_qs(usuario=None, atual=None):
    """Turmas ativas (as do ano de referência primeiro), limitadas aos cursos do coordenador."""
    qs = Turma.objects.select_related("curso")
    qs = qs.filter(Q(ativa=True) | Q(pk=atual.pk)) if atual is not None and atual.pk else qs.filter(ativa=True)
    if usuario is not None and usuario.is_coordenador and usuario.cursos_ids():
        qs = qs.filter(curso_id__in=usuario.cursos_ids())
    return qs


class TurmaChoiceField(forms.ModelChoiceField):
    def __init__(self, **kw):
        kw.setdefault("label", "Turma")
        if not kw.get("help_text"):
            kw["help_text"] = "Curso e ano da turma. Ex.: a turma de 2024 estagia em 2026. Cadastre turmas em “Turmas”."
        kw.setdefault("queryset", Turma.objects.none())
        kw.pop("limit_choices_to", None)
        super().__init__(**kw)

    def label_from_instance(self, t):
        return str(t)


def validar_supervisor_da_concedente(form, local, supervisor):
    if local and supervisor and local not in supervisor.concedentes.all():
        form.add_error("supervisor", f"{supervisor} não é supervisor(a) de {local}. Escolha um supervisor dessa concedente "
                                     "ou vincule-o(a) a ela na ficha da concedente.")


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
    horas_por_dia = campo_horas(required=False)
    horas_obrigatorias = True  # a importação aceita vazio (vale o da planilha)
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
        if "horas_por_dia" in self.fields and not horas and not self.errors.get("horas_por_dia"):
            calculadas = horas_dos_horarios(ent, si, vi, sai) if bool(si) == bool(vi) else None
            if calculadas:
                dados["horas_por_dia"] = calculadas
            elif self.horas_obrigatorias:
                self.add_error("horas_por_dia", "Informe as horas por dia ou os horários de entrada e saída.")
                return dados
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
        if "horas_por_dia" not in d:
            return {"dias": ",".join(str(x) for x in sorted(d["dias"]))}
        return {
            "dias": ",".join(str(x) for x in sorted(d["dias"])),
            "horario_entrada": d.get("horario_entrada"),
            "saida_intervalo": d.get("saida_intervalo"),
            "volta_intervalo": d.get("volta_intervalo"),
            "horario_saida": d.get("horario_saida"),
            "horas_por_dia": d.get("horas_por_dia"),
        }


class EscalaLoteForm(CamposEscalaMixin, Formulario):
    estagios = forms.ModelMultipleChoiceField(
        queryset=Estagio.objects.none(), widget=forms.CheckboxSelectMultiple, label="Estagiários"
    )
    vigente_desde = forms.DateField(label="Vale a partir de", widget=DataInput())

    field_order = ["vigente_desde", *CAMPOS_ESCALA, "estagios"]

    def __init__(self, *a, estagios_qs=None, com_horarios=True, **kw):
        super().__init__(*a, **kw)
        self.fields["estagios"].queryset = estagios_qs
        self.fields["estagios"].label_from_instance = lambda e: f"{e.estagiario} — {e.curso} · {e.local or 'sem local'}"
        self.com_horarios = com_horarios
        if not com_horarios:  # orientador muda só os dias; cada estagiário mantém horas e horários
            for nome in ("horas_por_dia", "horario_entrada", "saida_intervalo", "volta_intervalo", "horario_saida"):
                del self.fields[nome]


# ------------------------------------------------------------------ contas


class EstagiariosLoteForm(CamposEscalaMixin, Formulario):
    nomes = forms.CharField(
        label="Estagiários (um por linha)",
        widget=forms.Textarea(attrs={"rows": 8, "placeholder": "Maria da Silva Souza; 26/04/2008\nJoão Pedro Lima; 2024001234; 03/11/2007"}),
        help_text="Nome completo por linha. Opcional, separados por “;”: matrícula e data de nascimento (usada no "
                  "primeiro acesso).",
    )
    turma = TurmaChoiceField()
    local = forms.ModelChoiceField(queryset=LocalEstagio.objects.none(), label="Concedente")
    supervisor = forms.ModelChoiceField(queryset=supervisores_qs(), widget=SupervisorSelect,
                                        help_text="Só aparecem os supervisores da concedente escolhida.")
    setor = forms.CharField(required=False, max_length=100)
    data_inicio = forms.DateField(label="Início do estágio", widget=DataInput())
    data_fim = forms.DateField(label="Término previsto no termo", widget=DataInput(), required=False)

    field_order = ["nomes", "turma", "local", "setor", "supervisor", "data_inicio", "data_fim", *CAMPOS_ESCALA]

    orientador = forms.ModelChoiceField(
        queryset=Usuario.objects.filter(papel=Usuario.Papel.ORIENTADOR, is_active=True), required=False,
        label="Orientador(a) responsável",
    )

    def __init__(self, *a, usuario=None, **kw):
        super().__init__(*a, **kw)
        self.fields["supervisor"].queryset = supervisores_qs()
        self.fields["supervisor"].label_from_instance = lambda u: f"{u} ({u.concedentes_txt or 'sem concedente'})"
        self.fields["turma"].queryset = turmas_qs(usuario)
        self.fields["local"].queryset = concedentes_ativas()
        # o orientador cadastra os próprios estagiários; o coordenador escolhe o orientador
        if usuario is not None and usuario.is_orientador:
            del self.fields["orientador"]
        else:
            self.fields["orientador"].required = True
            self.order_fields(["nomes", "turma", "orientador"])
        self.fields["horario_entrada"].help_text = "Horários são opcionais: o supervisor da concedente define depois."

    def clean(self):
        dados = super().clean()
        validar_supervisor_da_concedente(self, dados.get("local"), dados.get("supervisor"))
        return dados

    def clean_nomes(self):
        linhas = []
        for bruto in self.cleaned_data["nomes"].splitlines():
            if not bruto.strip():
                continue
            nome, *resto = [p.strip() for p in bruto.split(";")]
            nome = " ".join(nome.split())
            if len(nome.split()) < 2:
                raise forms.ValidationError(f"Informe nome e sobrenome: “{nome}”.")
            matricula, nascimento = "", None
            for parte in resto:
                if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", parte):
                    nascimento = validar_nascimento(ler_nascimento(parte, nome))
                elif parte:
                    matricula = parte
            linhas.append((nome, matricula, nascimento))
        if not linhas:
            raise forms.ValidationError("Informe ao menos um nome.")
        return linhas


class SupervisoresLoteForm(Formulario):
    nomes = forms.CharField(
        label="Supervisores (um por linha)",
        widget=forms.Textarea(attrs={"rows": 5, "placeholder": "Ana Beatriz Rocha; (85) 99999-0000"}),
        help_text="Nome completo por linha. Opcional: “; telefone” depois do nome.",
    )
    local = forms.ModelChoiceField(queryset=LocalEstagio.objects.filter(ativa=True), label="Concedente")
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
        fields = ["nome_completo", "email", "telefone", "cpf", "data_nascimento", "matricula", "cargo", "concedentes",
                  "cursos_coordenados"]
        widgets = {"cursos_coordenados": forms.CheckboxSelectMultiple, "concedentes": forms.CheckboxSelectMultiple}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        if "data_nascimento" in self.fields:
            self.fields["data_nascimento"].widget = NascimentoInput()
            self.fields["data_nascimento"].input_formats = FORMATOS_NASCIMENTO

    def clean_data_nascimento(self):
        return validar_nascimento(self.cleaned_data.get("data_nascimento"))

    def clean_cpf(self):
        return limpar_cpf(self.cleaned_data.get("cpf"))

    def clean_concedentes(self):
        novas = self.cleaned_data.get("concedentes")
        if "concedentes" not in self.fields or not self.instance.pk:
            return novas
        if not novas:
            raise forms.ValidationError("O supervisor precisa estar vinculado a pelo menos uma concedente.")
        presas = (Estagio.objects.filter(supervisor=self.instance, ativo=True).exclude(local__in=novas)
                  .select_related("local", "estagiario"))
        if presas:
            nomes = ", ".join(sorted({str(e.local) for e in presas}))
            raise forms.ValidationError(f"Não dá para tirar {nomes}: há estagiários ativos supervisionados lá. "
                                        "Troque o supervisor desses estágios antes.")
        return novas


class PerfilForm(FormularioModelo):
    """Cada pessoa edita os próprios dados. Os campos mudam conforme o papel."""

    CAMPOS_CURRICULO = ["apresentacao", "habilidades", "curriculo", "perfil_visivel"]

    class Meta:
        model = Usuario
        fields = ["foto", "email", "telefone", "cpf", "cargo", "avisos_email", "resumo_semanal", "lembrete_expediente",
                  "novidades_popup",
                  "apresentacao",
                  "habilidades", "curriculo", "perfil_visivel"]
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
        if not u.is_gestor:
            del self.fields["resumo_semanal"]
        if not u.is_estagiario:
            del self.fields["cpf"], self.fields["lembrete_expediente"]
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
        fields = ["nome_escola", "municipio_escola", "ano_referencia", "cabecalho_folha", "logo_folha",
                  "mostrar_codigo_folha", "estagiarios_emitem_folha", "checkin_localizacao", "lembrete_expediente", "lembrete_minutos", "periodo_testes", "email_sugestoes", "avaliacoes_abertas", "avaliacoes_prazo", "sice_url", "tema_escuro", "exigir_dois_fatores", "retencao_anos", "contato_privacidade", "feedback_mensal", "atestados_supervisor", "avisos_email", "resumo_semanal", "confirmacao_por_email", "dia_confirmacao", "resumo_mensal_supervisor", "captacao_aberta", "ano_captacao", "captacao_prazo", "texto_captacao",
                  "curriculos_habilitados", "banco_talentos_habilitado"]
        widgets = {"logo_folha": forms.ClearableFileInput(attrs={"accept": "image/*"}), "captacao_prazo": DataInput(), "avaliacoes_prazo": DataInput(),
                   "texto_captacao": forms.Textarea(attrs={"rows": 3})}

    SECOES = [
        ("Escola e folha de frequência", "folha", ["nome_escola", "municipio_escola", "ano_referencia", "cabecalho_folha",
                                                   "logo_folha", "mostrar_codigo_folha", "estagiarios_emitem_folha"]),
        ("Presenças e lembretes", "presencas", ["checkin_localizacao", "lembrete_expediente", "lembrete_minutos",
                                                "atestados_supervisor", "feedback_mensal"]),
        ("Supervisores", "supervisores", ["confirmacao_por_email", "dia_confirmacao", "resumo_mensal_supervisor"]),
        ("Avisos e e-mails", "avisos", ["avisos_email", "resumo_semanal", "email_sugestoes"]),
        ("Segurança e privacidade", "seguranca", ["exigir_dois_fatores", "retencao_anos", "contato_privacidade"]),
        ("Captação de concedentes", "captacao", ["captacao_aberta", "ano_captacao", "captacao_prazo", "cursos_captacao",
                                                 "texto_captacao"]),
        ("Avaliações e SICE", "avaliacoes", ["avaliacoes_abertas", "avaliacoes_prazo", "sice_url"]),
        ("Perfil profissional e aparência", "perfil", ["curriculos_habilitados", "banco_talentos_habilitado",
                                                       "tema_escuro", "periodo_testes"]),
    ]
    cursos_captacao = forms.ModelMultipleChoiceField(
        queryset=Curso.objects.none(), required=False, widget=forms.CheckboxSelectMultiple,
        label="Cursos com vagas na captação",
        help_text="As concedentes marcam só estes cursos e informam as vagas de cada um.",
    )

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["cursos_captacao"].queryset = Curso.objects.order_by("nome")
        self.fields["cursos_captacao"].initial = list(Curso.objects.filter(na_captacao=True).values_list("pk", flat=True))

    def secoes(self):
        vistos = set()
        resultado = []
        for titulo, ancora, campos in self.SECOES:
            itens = [self[n] for n in campos if n in self.fields]
            vistos.update(campos)
            resultado.append((titulo, ancora, itens))
        sobra = [self[n] for n in self.fields if n not in vistos]
        if sobra:
            resultado.append(("Outras opções", "outras", sobra))
        return resultado

    def save(self, commit=True):
        config = super().save(commit)
        if commit and "cursos_captacao" in self.cleaned_data:
            ids = {c.pk for c in self.cleaned_data["cursos_captacao"]}
            Curso.objects.filter(pk__in=ids).update(na_captacao=True)
            Curso.objects.exclude(pk__in=ids).update(na_captacao=False)
        return config

    def clean(self):
        dados = super().clean()
        if dados.get("captacao_aberta") and not dados.get("cursos_captacao"):
            self.add_error("cursos_captacao", "Escolha pelo menos um curso para abrir a captação.")
        return dados

    def clean_logo_folha(self):
        logo = self.cleaned_data.get("logo_folha")
        if logo and hasattr(logo, "content_type") and logo.size > 2 * 1024 * 1024:
            raise forms.ValidationError("O logotipo deve ter no máximo 2 MB.")
        return logo


# ------------------------------------------------------------------ cadastros


class CursoForm(FormularioModelo):
    class Meta:
        model = Curso
        fields = ["nome", "carga_horaria"]


class TurmaForm(FormularioModelo):
    class Meta:
        model = Turma
        fields = ["curso", "nome", "ano_ingresso", "ano_estagio", "ativa"]

    def __init__(self, *a, usuario=None, **kw):
        super().__init__(*a, **kw)
        if usuario is not None and usuario.is_coordenador and usuario.cursos_ids():
            self.fields["curso"].queryset = Curso.objects.filter(pk__in=usuario.cursos_ids())
        for nome in ("ano_ingresso", "ano_estagio"):
            self.fields[nome].widget.attrs.update({"min": 2000, "max": 2100})

    def clean_nome(self):
        return " ".join((self.cleaned_data.get("nome") or "").split())

    def clean(self):
        d = super().clean()
        if d.get("curso") and d.get("ano_ingresso"):
            iguais = Turma.objects.filter(curso=d["curso"], ano_ingresso=d["ano_ingresso"], nome__iexact=d.get("nome", ""))
            if iguais.exclude(pk=self.instance.pk).exists():
                raise forms.ValidationError("Já existe essa turma (mesmo curso, nome e ano de ingresso).")
        return d


class AnoReferenciaForm(FormularioModelo):
    class Meta:
        model = Configuracao
        fields = ["ano_referencia"]


class LocalForm(FormularioModelo):
    """Ficha de cadastro de concedente (mesmos campos do formulário da SEDUC)."""

    SECOES = [
        ("Dados gerais", ["tipo_concedente", "razao_social", "nome", "tipo_instituicao", "atividade", "cnpj", "matriz_filial"]),
        ("Endereço", ["endereco", "numero", "bairro", "complemento", "cidade", "uf", "cep", "telefone", "link_mapa"]),
        ("Representante legal", ["representante_nome", "representante_email", "representante_cpf", "representante_documento"]),
        ("Localização para o check-in", ["latitude", "longitude", "raio_checkin"]),
        ("Supervisores", ["novos_supervisores", "vincular_supervisores"]),
        ("Outras informações", ["observacoes"]),
    ]
    vincular_supervisores = forms.ModelMultipleChoiceField(
        queryset=Usuario.objects.none(), required=False, label="Vincular supervisor já cadastrado em outra concedente",
        help_text="Use quando a mesma pessoa também supervisiona estagiários aqui.",
    )
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
            "latitude", "longitude", "raio_checkin",
        ]
        widgets = {
            "tipo_concedente": forms.RadioSelect, "tipo_instituicao": forms.RadioSelect, "matriz_filial": forms.RadioSelect,
            "atividade": forms.Textarea(attrs={"rows": 2}),
            "latitude": forms.TextInput(attrs={"inputmode": "decimal", "placeholder": "-3.731900"}),
            "longitude": forms.TextInput(attrs={"inputmode": "decimal", "placeholder": "-38.526700"}),
        }
        labels = {"endereco": "Endereço (rua, avenida…)"}
        help_texts = {
            "latitude": "Vazio = tirada do link do mapa, se ele tiver as coordenadas. No Google Maps, toque e segure no "
                        "local e copie os números que aparecem.",
        }

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        for nome in ("tipo_instituicao", "matriz_filial"):
            self.fields[nome].choices = [c for c in self.fields[nome].choices if c[0]]
        self.fields["uf"].widget.attrs.update({"maxlength": 2, "style": "text-transform:uppercase"})
        if "raio_checkin" in self.fields:
            self.fields["raio_checkin"].required = False
        if "vincular_supervisores" in self.fields:
            qs = supervisores_qs()
            if self.instance.pk and isinstance(self.instance, LocalEstagio):
                qs = qs.exclude(concedentes=self.instance)
            self.fields["vincular_supervisores"].queryset = qs
            self.fields["vincular_supervisores"].label_from_instance = lambda u: f"{u} ({u.concedentes_txt or 'sem concedente'})"

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

    def clean(self):
        dados = super().clean()
        if "latitude" not in self.fields:
            return dados
        if not dados.get("raio_checkin"):
            dados["raio_checkin"] = LocalEstagio._meta.get_field("raio_checkin").default
        lat, lng = dados.get("latitude"), dados.get("longitude")
        if lat is None and lng is None and dados.get("link_mapa"):
            from .services import coordenadas_do_link

            achadas = coordenadas_do_link(dados["link_mapa"])
            if achadas:
                dados["latitude"], dados["longitude"] = achadas
        elif (lat is None) != (lng is None):
            self.add_error("longitude" if lng is None else "latitude", "Informe latitude e longitude juntas.")
        if lat is not None and not -90 <= lat <= 90:
            self.add_error("latitude", "Latitude vai de -90 a 90.")
        if lng is not None and not -180 <= lng <= 180:
            self.add_error("longitude", "Longitude vai de -180 a 180.")
        return dados


class DiaSemEstagioForm(FormularioModelo):
    ate = forms.DateField(label="Até (opcional, para períodos)", required=False, widget=DataInput())

    class Meta:
        model = DiaSemEstagio
        fields = ["abrangencia", "municipio", "concedente", "data", "ate", "descricao", "anual", "curso"]
        widgets = {"data": DataInput(), "abrangencia": forms.RadioSelect,
                   "municipio": forms.TextInput(attrs={"list": "municipios", "autocomplete": "off",
                                                       "placeholder": "Ex.: General Sampaio"})}
        labels = {"data": "Data", "descricao": "Descrição", "curso": "Só para o curso (eventos da escola)"}
        help_texts = {
            "municipio": "Vale para os estagiários de concedentes deste município (pelo município da ficha da concedente).",
            "anual": "Para datas fixas como o aniversário da cidade e o padroeiro: não precisa cadastrar de novo a cada ano.",
            "concedente": "O recesso vale só para os estagiários desta concedente.",
        }

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["concedente"].queryset = LocalEstagio.objects.filter(ativa=True)

    def clean(self):
        d = super().clean()
        A = DiaSemEstagio.Abrangencia
        abr = d.get("abrangencia")
        if abr == A.MUNICIPIO and not (d.get("municipio") or "").strip():
            self.add_error("municipio", "Informe o município do feriado.")
        if abr == A.CONCEDENTE and not d.get("concedente"):
            self.add_error("concedente", "Escolha a concedente do recesso.")
        if abr != A.CONCEDENTE:
            d["concedente"] = None
        if d.get("anual") and d.get("ate"):
            self.add_error("anual", "Um período (com “até”) não pode repetir todo ano. Cadastre cada data.")
        if d.get("ate") and d.get("data") and d["ate"] < d["data"]:
            self.add_error("ate", "A data final é antes da inicial.")
        if abr != A.ESCOLA:
            d["curso"] = None
        if abr != A.MUNICIPIO:
            d["municipio"] = ""
        return d


class EstagioForm(FormularioModelo):
    class Meta:
        model = Estagio
        fields = [
            "turma", "local", "setor", "supervisor", "data_inicio", "data_fim", "acompanhamento_desde",
            "carga_horaria", "horas_anteriores", "ativo", "observacoes_orientador",
        ]
        field_classes = {"turma": TurmaChoiceField}
        labels = {"local": "Concedente", "data_fim": "Término previsto no termo"}
        help_texts = {"data_fim": "Só informativo: a previsão real é calculada pelas horas que faltam.",
                      "supervisor": "Só aparecem os supervisores da concedente escolhida. Trocar o supervisor fica "
                                    "registrado no histórico do estágio."}
        widgets = {"data_inicio": DataInput(), "data_fim": DataInput(), "acompanhamento_desde": DataInput(),
                   "supervisor": SupervisorSelect}

    def __init__(self, *a, usuario=None, **kw):
        super().__init__(*a, **kw)
        self.fields["local"].required = self.fields["supervisor"].required = self.fields["turma"].required = True
        self.fields["turma"].queryset = turmas_qs(usuario, self.instance.turma if self.instance.turma_id else None)
        self.fields["local"].queryset = concedentes_ativas(self.instance.local if self.instance.local_id else None)
        self.fields["supervisor"].queryset = supervisores_qs()
        self.fields["supervisor"].label_from_instance = lambda u: f"{u} ({u.concedentes_txt or 'sem concedente'})"

    def clean(self):
        dados = super().clean()
        validar_supervisor_da_concedente(self, dados.get("local"), dados.get("supervisor"))
        return dados

    def _post_clean(self):
        if self.cleaned_data.get("turma"):
            self.instance.curso = self.cleaned_data["turma"].curso
        super()._post_clean()


class TrocarSupervisorForm(Formulario):
    """Só o orientador/coordenador troca o supervisor — e sempre colocando outro no lugar."""

    novo = forms.ModelChoiceField(queryset=Usuario.objects.none(), label="Novo supervisor")
    motivo = forms.CharField(label="Motivo (opcional)", required=False, max_length=200)

    def __init__(self, *a, estagio=None, **kw):
        super().__init__(*a, **kw)
        qs = supervisores_qs().filter(concedentes=estagio.local) if estagio.local_id else supervisores_qs()
        if estagio.supervisor_id:
            qs = qs.exclude(pk=estagio.supervisor_id)
        self.fields["novo"].queryset = qs
        self.fields["novo"].help_text = f"Supervisores cadastrados em {estagio.local}." if estagio.local_id else ""


class SubstitutosForm(Formulario):
    """Ao desativar um supervisor: um substituto (da mesma concedente) para cada estágio ativo dele."""

    def __init__(self, *a, estagios=(), sair=None, **kw):
        super().__init__(*a, **kw)
        self.estagios = list(estagios)
        self.sem_opcao = []
        for e in self.estagios:
            qs = supervisores_qs().filter(concedentes=e.local).exclude(pk=sair.pk) if e.local_id else Usuario.objects.none()
            campo = forms.ModelChoiceField(queryset=qs, label=f"{e.estagiario} · {e.local or 'sem concedente'}",
                                           empty_label="Escolha o novo supervisor")
            if not qs.exists() and e.local not in self.sem_opcao:
                self.sem_opcao.append(e.local)  # concedentes sem outro supervisor cadastrado
            self.fields[f"sub_{e.pk}"] = campo

    def trocas(self):
        return [(e, self.cleaned_data[f"sub_{e.pk}"]) for e in self.estagios]


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


class JustificativaForm(Formulario):
    """Atestado ou comprovante de um ou mais dias."""

    tipo = forms.ChoiceField(label="Tipo de documento", choices=Justificativa.Tipo.choices)
    data_inicio = forms.DateField(label="Primeiro dia", widget=DataInput())
    data_fim = forms.DateField(label="Último dia", widget=DataInput(), required=False,
                               help_text="Vazio = só o primeiro dia. Ex.: atestado de 3 dias.")
    arquivo = forms.FileField(
        label="Foto ou PDF do documento",
        widget=forms.ClearableFileInput(attrs={"accept": "image/*,application/pdf,.pdf"}),
        help_text="Tire a foto com boa luz e o documento inteiro aparecendo. O código da doença (CID) não é "
                  "obrigatório: você pode cobri-lo antes de fotografar.",
    )
    motivo = forms.CharField(label="Observação (opcional)", required=False, max_length=300,
                             widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Ex.: consulta às 9h, voltei à tarde"}))

    DIAS_ATRAS = 30
    DIAS_FRENTE = 60

    def clean(self):
        d = super().clean()
        inicio, fim = d.get("data_inicio"), d.get("data_fim") or d.get("data_inicio")
        if not inicio:
            return d
        hoje = timezone.localdate()
        if fim < inicio:
            self.add_error("data_fim", "O último dia não pode ser antes do primeiro.")
        elif inicio < hoje - timedelta(days=self.DIAS_ATRAS):
            self.add_error("data_inicio", f"Só dá para enviar documentos dos últimos {self.DIAS_ATRAS} dias. "
                                          "Fale com o orientador.")
        elif fim > hoje + timedelta(days=self.DIAS_FRENTE) or (fim - inicio).days > self.DIAS_FRENTE:
            self.add_error("data_fim", f"Período longo demais (máximo de {self.DIAS_FRENTE} dias). Fale com o orientador.")
        d["data_fim"] = fim
        return d


class DecisaoJustificativaForm(Formulario):
    parecer = forms.CharField(label="Parecer", required=False, max_length=500,
                              widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Obrigatório para recusar. "
                                                           "Ex.: documento ilegível, data não confere…"}))


class PlanejarDiaForm(Formulario):
    """Estagiário avisa que vai estagiar num dia fora da escala (reposição) ou com outra carga."""

    horas = campo_horas("Quantas horas vai estagiar", help_text="")
    motivo = forms.CharField(label="Observação (opcional)", required=False, max_length=160,
                             widget=forms.TextInput(attrs={"placeholder": "Ex.: reposição do dia 20/11"}))

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["horas"].help_text = ""
        _ajustar_choices_horas(self, "horas")


class HorariosDiaForm(Formulario):
    """O estagiário informa a que horas entrou e saiu, como na folha de papel; o supervisor confirma."""

    hora_chegada = forms.TimeField(label="Entrada", widget=HoraInput())
    saida_intervalo = forms.TimeField(label="Saída p/ intervalo", required=False, widget=HoraInput())
    volta_intervalo = forms.TimeField(label="Volta do intervalo", required=False, widget=HoraInput())
    hora_saida = forms.TimeField(label="Saída", required=False, widget=HoraInput())

    def clean(self):
        d = super().clean()
        si, vi = d.get("saida_intervalo"), d.get("volta_intervalo")
        if bool(si) != bool(vi):
            raise forms.ValidationError("Informe a saída e a volta do intervalo (ou deixe as duas em branco).")
        seq = [t for t in (d.get("hora_chegada"), si, vi, d.get("hora_saida")) if t]
        if any(b <= a for a, b in zip(seq, seq[1:])):
            raise forms.ValidationError("Os horários devem estar em ordem: entrada, intervalo e saída.")
        return d


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
        help_texts = {"horas": "Com entrada e saída preenchidas, as horas são calculadas pelos horários."}
        labels = {"confirmacao": "Validação"}

    def clean(self):
        d = super().clean()
        if d.get("situacao") == Registro.Situacao.PRESENTE:
            r = Registro(hora_chegada=d.get("hora_chegada"), saida_intervalo=d.get("saida_intervalo"),
                         volta_intervalo=d.get("volta_intervalo"), hora_saida=d.get("hora_saida"))
            calculadas = r.calcular_horas()
            if calculadas:
                d["horas"] = calculadas
                self.instance.horas = calculadas
        return d


class RevogarPresencaForm(Formulario):
    """Desfaz uma presença (mesmo já confirmada) quando houve imprevisto ou engano."""

    DESTINOS = [
        ("remover", "Remover o registro (marcado por engano, o dia fica sem registro)"),
        ("ausencia", "Trocar por ausência justificada (imprevisto: passou mal, foi dispensado…)"),
        ("falta", "Trocar por falta (não compareceu)"),
    ]
    destino = forms.ChoiceField(label="O que fazer", choices=DESTINOS, widget=forms.RadioSelect, initial="remover")
    motivo = forms.CharField(label="Motivo", max_length=300, widget=forms.Textarea(attrs={"rows": 2}),
                             help_text="Obrigatório. Fica no histórico do dia e vai no aviso às outras pessoas.")

    def __init__(self, *a, so_remover=False, **kw):
        super().__init__(*a, **kw)
        if so_remover:  # estagiário: só desfaz a própria marcação ainda não confirmada
            self.fields["destino"].choices = [self.DESTINOS[0], ("ausencia", "Trocar por ausência informada (o "
                                                                 "supervisor confirma)")]


class MensagemForm(FormularioModelo):
    class Meta:
        model = Mensagem
        fields = ["texto", "privada_orientador"]
        widgets = {"texto": forms.Textarea(attrs={"rows": 3, "placeholder": "Escreva sua dúvida ou mensagem…"})}
        labels = {"texto": ""}


EXTENSOES_DOCUMENTO = {"pdf", "png", "jpg", "jpeg", "gif", "webp", "heic", "heif", "doc", "docx", "odt", "rtf", "txt",
                       "xls", "xlsx", "ods", "csv", "ppt", "pptx", "odp", "zip"}


def conferir_documento(arq):
    """Tamanho e tipo dos arquivos da pasta/documentos (nada de .html, .svg, .exe…)."""
    if arq and arq.size > settings.TAMANHO_MAX_ANEXO_MB * 1024 * 1024:
        raise forms.ValidationError(f"O arquivo deve ter no máximo {settings.TAMANHO_MAX_ANEXO_MB} MB.")
    ext = (arq.name.rsplit(".", 1)[-1] if arq and "." in arq.name else "").lower()
    if arq and ext not in EXTENSOES_DOCUMENTO:
        raise forms.ValidationError("Tipo de arquivo não aceito. Envie PDF, foto (JPG/PNG) ou documento do Office/LibreOffice.")
    return arq


class DocumentoForm(FormularioModelo):
    class Meta:
        model = Documento
        fields = ["titulo", "categoria", "arquivo", "descricao"]

    def clean_arquivo(self):
        return conferir_documento(self.cleaned_data["arquivo"])


class EntregaForm(Formulario):
    arquivo = forms.FileField(label="Arquivo", widget=forms.ClearableFileInput(attrs={"accept": "image/*,application/pdf,.pdf,.doc,.docx,.odt"}))
    observacao = forms.CharField(label="Observação (opcional)", required=False, max_length=300)

    def clean_arquivo(self):
        return conferir_documento(self.cleaned_data["arquivo"])


class FeedbackForm(FormularioModelo):
    class Meta:
        model = Feedback
        fields = [c for c, _ in Feedback.CRITERIOS] + ["pontos_fortes", "melhorar", "reservado", "visivel_estagiario"]
        widgets = {
            **{c: forms.RadioSelect for c, _ in Feedback.CRITERIOS},
            "pontos_fortes": forms.Textarea(attrs={"rows": 2, "placeholder": "Ex.: atencioso no atendimento, aprende rápido"}),
            "melhorar": forms.Textarea(attrs={"rows": 2, "placeholder": "Ex.: chegar no horário, pedir ajuda quando travar"}),
            "reservado": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        escala = [(str(v), r) for v, r in reversed(Feedback.NOTAS)] + [("", "Não observei")]
        for c, _ in Feedback.CRITERIOS:
            self.fields[c].choices = escala

    def clean(self):
        d = super().clean()
        if not any(d.get(c) for c, _ in Feedback.CRITERIOS) and not (d.get("pontos_fortes") or d.get("melhorar")):
            raise forms.ValidationError("Dê ao menos uma nota ou escreva um comentário.")
        return d


class ComunicadoForm(Formulario):
    PARA = [("estagiarios", "Estagiários"), ("supervisores", "Supervisores"), ("todos", "Estagiários e supervisores")]
    para = forms.ChoiceField(label="Para", choices=PARA, initial="estagiarios")
    turma = forms.ModelChoiceField(queryset=Turma.objects.none(), required=False, label="Turma",
                                   empty_label="Todas as turmas")
    curso = forms.ModelChoiceField(queryset=Curso.objects.all(), required=False, label="Curso", empty_label="Todos os cursos")
    local = forms.ModelChoiceField(queryset=LocalEstagio.objects.filter(ativa=True), required=False, label="Concedente",
                                   empty_label="Todas as concedentes")
    titulo = forms.CharField(label="Assunto", max_length=120,
                             widget=forms.TextInput(attrs={"placeholder": "Ex.: Entrega do relatório até sexta"}))
    texto = forms.CharField(label="Mensagem", max_length=3000, widget=forms.Textarea(attrs={"rows": 5}))
    responsaveis = forms.BooleanField(
        label="Também para os responsáveis legais dos estagiários", required=False, initial=True,
        help_text="Eles recebem no sino (e no e-mail, se tiverem) os avisos mandados aos estagiários.")

    def __init__(self, *a, usuario=None, **kw):
        super().__init__(*a, **kw)
        from .services import ano_referencia

        turmas = Turma.objects.select_related("curso").filter(ativa=True, ano_estagio=ano_referencia())
        if usuario and usuario.is_coordenador and usuario.cursos_ids():
            turmas = turmas.filter(curso_id__in=usuario.cursos_ids())
            self.fields["curso"].queryset = Curso.objects.filter(pk__in=usuario.cursos_ids())
        self.fields["turma"].queryset = turmas
        self.fields["turma"].label_from_instance = lambda t: t.rotulo


class VariosArquivosInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class VariosArquivosField(forms.FileField):
    def __init__(self, *a, **kw):
        kw.setdefault("widget", VariosArquivosInput())
        super().__init__(*a, **kw)

    def clean(self, data, initial=None):
        um = super().clean
        if isinstance(data, (list, tuple)):
            return [um(d, initial) for d in data if d]
        return [um(data, initial)] if data else []


EXTENSOES_SUGESTAO = {"png", "jpg", "jpeg", "gif", "webp", "heic", "pdf", "txt", "csv", "doc", "docx", "odt", "xls",
                      "xlsx", "ods", "mp4", "mov", "webm", "zip"}


class SugestaoForm(Formulario):
    tipo = forms.ChoiceField(label="Sobre o quê", choices=Sugestao.Tipo.choices, initial=Sugestao.Tipo.SUGESTAO)
    nome = forms.CharField(label="Seu nome", max_length=150)
    email = forms.EmailField(label="E-mail para resposta (opcional)", required=False)
    mensagem = forms.CharField(label="Mensagem", max_length=5000, widget=forms.Textarea(attrs={
        "rows": 6, "placeholder": "Conte com detalhes. Se for um erro: o que você fez, o que esperava e o que aconteceu."}))
    anexos = VariosArquivosField(
        label="Anexos (opcional)", required=False,
        widget=VariosArquivosInput(attrs={"accept": "image/*,application/pdf,.pdf,.doc,.docx,.odt,.xls,.xlsx,.ods,"
                                                    ".csv,.txt,.zip,video/*"}),
        help_text="Prints da tela, fotos, PDFs ou planilhas.",
    )
    site = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}),
                           label="Deixe em branco")  # armadilha para robôs (fica escondida)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["anexos"].help_text += (f" Até {settings.SUGESTOES_MAX_ARQUIVOS} arquivos, "
                                            f"{settings.SUGESTOES_MAX_MB} MB no total.")

    def clean_anexos(self):
        arquivos = self.cleaned_data.get("anexos") or []
        if len(arquivos) > settings.SUGESTOES_MAX_ARQUIVOS:
            raise forms.ValidationError(f"Envie no máximo {settings.SUGESTOES_MAX_ARQUIVOS} arquivos.")
        if sum(a.size for a in arquivos) > settings.SUGESTOES_MAX_MB * 1024 * 1024:
            raise forms.ValidationError(f"Os anexos passam de {settings.SUGESTOES_MAX_MB} MB. Envie menos arquivos "
                                        "ou imagens menores.")
        for a in arquivos:
            ext = a.name.rsplit(".", 1)[-1].lower() if "." in a.name else ""
            if ext not in EXTENSOES_SUGESTAO:
                raise forms.ValidationError(f"“{a.name}”: tipo de arquivo não aceito. Use imagem, PDF, documento, "
                                            "planilha, vídeo ou ZIP.")
        return arquivos


class ColarAtividadesForm(Formulario):
    curso = forms.ModelChoiceField(queryset=Curso.objects.all(), label="Curso")
    atividades = forms.CharField(
        label="Atividades (uma por linha)", widget=forms.Textarea(attrs={"rows": 8, "placeholder":
                                                                         "REALIZAR A INSTALAÇÃO DOS DRIVERS\n"
                                                                         "REALIZAR MONTAGEM DE COMPUTADORES"}),
        help_text="Cole a lista do SICE, na mesma ordem. Linhas repetidas ou vazias são ignoradas.")
    substituir = forms.BooleanField(label="Tirar de uso as atividades atuais deste curso", required=False,
                                    help_text="As respostas já dadas continuam guardadas.")

    def linhas(self):
        vistas, resultado = set(), []
        for linha in self.cleaned_data["atividades"].splitlines():
            texto = " ".join(linha.split()).strip(" -•;")
            if texto and texto.lower() not in vistas:
                vistas.add(texto.lower())
                resultado.append(texto[:300])
        return resultado


class PerguntaAvaliacaoForm(FormularioModelo):
    class Meta:
        model = PerguntaAvaliacao
        fields = ["avaliacao", "curso", "enunciado", "ajuda", "resposta", "opcoes", "limite", "obrigatoria", "ordem",
                  "ativa"]
        widgets = {"opcoes": forms.Textarea(attrs={"rows": 3})}
        labels = {"ordem": "Ordem (a mesma do SICE)"}

    def clean(self):
        d = super().clean()
        if d.get("resposta") == PerguntaAvaliacao.Resposta.ESCOLHA and len([o for o in (d.get("opcoes") or "").splitlines()
                                                                            if o.strip()]) < 2:
            self.add_error("opcoes", "Informe pelo menos duas opções, uma por linha.")
        return d


class TipoDocumentoForm(FormularioModelo):
    class Meta:
        model = TipoDocumento
        fields = ["nome", "descricao", "momento", "prazo_dias", "quem_envia", "obrigatorio", "curso", "modelo", "ativo",
                  "ordem"]
        widgets = {"descricao": forms.Textarea(attrs={"rows": 2})}
        labels = {"ordem": "Ordem na lista"}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["curso"].empty_label = "Todos os cursos"


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
        fields = ["tipo", "modalidade", "status", "data_hora", "duracao", "local", "estagios", "assunto", "detalhes", "relato"]
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
    """Cadastro da concedente na captação. Três jeitos de usar:

    - `modo="publico"`: sem login. Quem preenche (representante legal ou pessoa autorizada por ele) cria a própria
      conta junto, para entrar depois e acompanhar a decisão da escola;
    - `modo="conta"`: quem já tem conta (supervisor/responsável) manda outra candidatura, sem criar conta;
    - `modo="escola"`: orientador/coordenador preenche a pedido da concedente;
    - `modo="editar"`: muda os dados e as vagas enquanto a escola não decidiu.
    """

    SECOES = [
        ("Quem está preenchendo", ["preenchido_por", "contato_nome", "contato_cargo", "contato_telefone",
                                   "contato_whatsapp", "contato_email"]),
        ("Dados gerais", ["tipo_concedente", "razao_social", "nome", "tipo_instituicao", "atividade", "cnpj", "matriz_filial"]),
        ("Endereço", ["endereco", "numero", "bairro", "complemento", "cidade", "uf", "cep", "telefone"]),
        ("Representante legal", ["representante_nome", "representante_email", "representante_cpf", "representante_documento"]),
        ("Cursos e vagas", ["VAGAS"]),
        ("Proposta de estágio", ["atividades", "turnos", "horario", "beneficios"]),
        ("Supervisor(a) dos estagiários", ["supervisor_nome", "supervisor_cargo", "supervisor_telefone", "supervisor_email"]),
        ("Seu acesso ao sistema", ["senha1", "senha2", "aceite_termos"]),
        ("Outras informações", ["observacoes", "consentimento"]),
    ]
    turnos = forms.MultipleChoiceField(choices=Candidatura.TURNOS, widget=forms.CheckboxSelectMultiple, required=False,
                                       label="Turnos disponíveis")
    senha1 = forms.CharField(label="Crie uma senha", strip=False,
                             widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
                             help_text="Com ela você entra no sistema para acompanhar a análise e, depois de aprovado, "
                                       "cadastrar a equipe da concedente.")
    senha2 = forms.CharField(label="Repita a senha", strip=False,
                             widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    aceite_termos = forms.BooleanField(label="Li e aceito os Termos de Uso e o Aviso de Privacidade do sistema.")
    consentimento = forms.BooleanField(
        label="Declaro que as informações são verdadeiras e autorizo a escola a usá-las para organizar o estágio.",
    )
    site = forms.CharField(required=False, label="Deixe em branco", widget=forms.TextInput(attrs={"autocomplete": "off",
                                                                                                    "tabindex": "-1"}))

    class Meta(LocalForm.Meta):
        model = Candidatura
        fields = [*LocalForm.Meta.fields, "preenchido_por", "contato_nome", "contato_cargo", "contato_telefone",
                  "contato_whatsapp", "contato_email", "atividades", "horario", "beneficios", "supervisor_nome",
                  "supervisor_cargo", "supervisor_telefone", "supervisor_email"]
        for _f in ("link_mapa", "latitude", "longitude", "raio_checkin"):
            fields.remove(_f)
        labels = {**LocalForm.Meta.labels, "observacoes": "Algo mais que a escola deva saber?"}
        help_texts = {}
        widgets = {**LocalForm.Meta.widgets, "atividades": forms.Textarea(attrs={"rows": 4}),
                   "preenchido_por": forms.RadioSelect}

    def __init__(self, *a, modo="publico", **kw):
        super().__init__(*a, **kw)
        self.modo = modo
        del self.fields["novos_supervisores"], self.fields["vincular_supervisores"]
        self.fields["razao_social"].required = True
        self.fields["razao_social"].help_text = ""
        self.fields["atividades"].widget.attrs["placeholder"] = "Ex.: apoio no atendimento ao público, organização de arquivos, suporte de informática…"
        escolhas = Candidatura.PreenchidoPor
        if modo == "escola":
            del self.fields["preenchido_por"]
        else:
            campo = self.fields["preenchido_por"]
            campo.required = True
            campo.choices = [(escolhas.REPRESENTANTE, escolhas.REPRESENTANTE.label),
                             (escolhas.AUTORIZADO, f"{escolhas.AUTORIZADO.label} (você declara que tem a autorização)")]
            if modo == "editar" and self.instance.preenchido_por == escolhas.ESCOLA:
                del self.fields["preenchido_por"]
        if modo != "publico":
            for nome in ("senha1", "senha2", "aceite_termos"):
                del self.fields[nome]
        else:
            self.fields["contato_email"].required = True
            self.fields["contato_email"].help_text = "Você recebe aqui a confirmação e a decisão da escola, e pode usá-lo para entrar."
        if modo == "editar":
            del self.fields["consentimento"], self.fields["site"]
        # cursos que a escola abriu para a captação (e, na edição, os que já tinham vaga)
        ja = {v.curso_id: v.quantidade for v in self.instance.vagas.all()} if self.instance.pk else {}
        self.cursos = list(Curso.objects.filter(Q(na_captacao=True) | Q(pk__in=ja)).order_by("nome"))
        for c in self.cursos:
            self.fields[f"curso_{c.pk}"] = forms.BooleanField(label=c.nome, required=False, initial=c.pk in ja)
            self.fields[f"vaga_{c.pk}"] = forms.IntegerField(
                label="Vagas", min_value=1, max_value=99, required=False, initial=ja.get(c.pk),
                widget=forms.NumberInput(attrs={"placeholder": "Quantas?", "inputmode": "numeric"}),
            )

    def secoes(self):
        resultado = []
        for titulo, campos in self.SECOES:
            if campos == ["VAGAS"]:
                resultado.append((titulo, []))
                continue
            itens = [self[n] for n in campos if n in self.fields]
            if itens:
                resultado.append((titulo, itens))
        return resultado

    def cursos_campos(self):
        return [(c, self[f"curso_{c.pk}"], self[f"vaga_{c.pk}"]) for c in self.cursos]

    def clean_turnos(self):
        return ",".join(self.cleaned_data.get("turnos") or [])

    def clean_supervisor_nome(self):
        nome = " ".join((self.cleaned_data.get("supervisor_nome") or "").split())
        if nome and len(nome.split()) < 2:
            raise forms.ValidationError("Informe nome e sobrenome.")
        return nome

    def clean_contato_nome(self):
        nome = " ".join((self.cleaned_data.get("contato_nome") or "").split())
        if self.modo == "publico" and len(nome.split()) < 2:
            raise forms.ValidationError("Informe nome e sobrenome: é o nome da sua conta.")
        return nome

    def clean(self):
        dados = super().clean()
        if dados.get("site"):
            raise forms.ValidationError("Não foi possível enviar o cadastro.")
        self.vagas = {}
        for c in self.cursos:
            marcado, qtd = dados.get(f"curso_{c.pk}"), dados.get(f"vaga_{c.pk}")
            if marcado and not qtd and f"vaga_{c.pk}" not in self.errors:
                self.add_error(f"vaga_{c.pk}", "Informe quantas vagas para este curso.")
            elif qtd:  # número preenchido conta como curso escolhido (mesmo sem a caixa, se o navegador não tiver JS)
                self.vagas[c] = qtd
        if not self.vagas and not any(k.startswith("vaga_") for k in self.errors):
            raise forms.ValidationError("Escolha pelo menos um curso e informe quantas vagas.")
        if "senha1" in self.fields and dados.get("senha1"):
            if dados["senha1"] != dados.get("senha2"):
                self.add_error("senha2", "As duas senhas não são iguais.")
            else:
                from django.contrib.auth.password_validation import validate_password

                provisoria = Usuario(username="concedente", nome_completo=dados.get("contato_nome", ""),
                                     email=dados.get("contato_email", ""))
                try:
                    validate_password(dados["senha1"], provisoria)
                except forms.ValidationError as exc:
                    self.add_error("senha1", exc)
        return dados

    def save(self, commit=True):
        cand = forms.ModelForm.save(self, commit=False)
        cand.turnos = self.cleaned_data["turnos"]
        if commit:
            from .models import VagaCandidatura

            cand.save()
            atuais = {v.curso_id: v for v in cand.vagas.all()}
            for c, q in self.vagas.items():
                v = atuais.pop(c.pk, None)
                if v is None:
                    VagaCandidatura.objects.create(candidatura=cand, curso=c, quantidade=q)
                elif v.quantidade != q:
                    v.quantidade = q
                    v.save(update_fields=["quantidade"])
            VagaCandidatura.objects.filter(pk__in=[v.pk for v in atuais.values()]).delete()
        return cand


class AprovarCandidaturaForm(Formulario):
    destino = forms.ChoiceField(label="Cadastrar como", widget=forms.RadioSelect)
    criar_supervisor = forms.BooleanField(required=False, initial=True,
                                          label="Criar a conta do supervisor indicado")
    criar_responsavel = forms.BooleanField(
        required=False, initial=False, label="Criar a conta do responsável pela concedente",
        help_text="Quem preencheu o cadastro poderá cadastrar a equipe e dar permissões temporárias para confirmar "
                  "presenças. O código de acesso aparece na próxima tela.")
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
        mesmo = candidatura.supervisor_nome and chave_nome(candidatura.supervisor_nome) == chave_nome(candidatura.contato_nome)
        if candidatura.conta_id:
            conta = candidatura.conta
            self.fields["criar_responsavel"].initial = True
            self.fields["criar_responsavel"].label = (
                f"Tornar {conta.nome_completo} (usuário {conta.username}) responsável pela concedente")
            self.fields["criar_responsavel"].help_text = (
                "É a conta de quem preencheu o cadastro: passa a cadastrar a equipe e dar permissões temporárias. "
                "Desmarcado, a pessoa só continua vendo a candidatura.")
            if mesmo and "criar_supervisor" in self.fields:
                self.fields["criar_supervisor"].label = (
                    f"{conta.nome_completo} também é o(a) supervisor(a) dos estagiários (usa a mesma conta)")
        else:
            self.fields["criar_responsavel"].label = (
                f"{'Tornar o supervisor também' if mesmo else 'Criar a conta de'} responsável pela concedente "
                f"({candidatura.contato_nome})")


def chave_nome(nome):
    from .seguranca import chave_texto

    return chave_texto(nome)


class RecusarCandidaturaForm(Formulario):
    parecer = forms.CharField(label="Motivo (vai na mensagem para a concedente)", widget=forms.Textarea(attrs={"rows": 3}))


# ------------------------------------------------------------------ responsáveis legais


class ResponsavelForm(Formulario):
    """Responsável legal do estudante, como está no TCE (ou a pedido do responsável)."""

    nome = forms.CharField(label="Nome completo", max_length=150)
    cpf = forms.CharField(label="CPF", max_length=14, required=False,
                          help_text="Recomendado: evita contas repetidas para irmãos e permite entrar com o CPF.")
    telefone = forms.CharField(label="Telefone / WhatsApp", max_length=30, required=False)
    email = forms.EmailField(label="E-mail", required=False, help_text="Opcional. O TCE não traz; dá para incluir depois.")
    parentesco = forms.CharField(label="Parentesco", max_length=40, required=False,
                                 widget=forms.TextInput(attrs={"placeholder": "mãe, pai, avó…"}))
    origem = forms.ChoiceField(label="De onde veio", widget=forms.RadioSelect, initial="TCE",
                               choices=[("TCE", "Do termo de compromisso (TCE)"), ("PEDIDO", "O próprio responsável pediu")])

    def clean_nome(self):
        nome = " ".join(self.cleaned_data["nome"].split())
        if len(nome.split()) < 2:
            raise forms.ValidationError("Informe nome e sobrenome.")
        return nome

    def clean_cpf(self):
        return limpar_cpf(self.cleaned_data.get("cpf"))


class ImportarResponsaveisForm(Formulario):
    arquivo = forms.FileField(label="Planilha (CSV)", widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"}))


# ------------------------------------------------------------------ importação em massa


class ImportarCSVForm(CamposEscalaMixin, Formulario):
    horas_obrigatorias = False
    arquivo = forms.FileField(label="Planilha", widget=forms.ClearableFileInput(attrs={"accept": ".xlsx,.csv,text/csv"}),
                              help_text="A planilha modelo preenchida (.xlsx) ou um CSV com uma linha por estagiário.")
    orientador = forms.ModelChoiceField(
        queryset=Usuario.objects.filter(papel=Usuario.Papel.ORIENTADOR, is_active=True), label="Orientador(a) responsável",
        help_text="Usado nas linhas em que a coluna “orientador” estiver vazia.",
    )
    acompanhamento_desde = forms.DateField(
        label="Acompanhar no sistema a partir de", widget=DataInput(), required=False,
        help_text="Para estágios que já começaram: os dias antes desta data não aparecem como “sem registro”.",
    )
    carga_cursos_novos = forms.IntegerField(label="Carga horária para cursos novos (h)", initial=300, min_value=1,
                                            help_text="Só usada se a planilha trouxer um curso que ainda não existe.")
    completar_concedentes = forms.BooleanField(label="Completar campos vazios de concedentes já cadastradas",
                                               required=False, initial=True)
    mudanca_desde = forms.DateField(
        label="Os dias mudam a partir de", widget=DataInput(), required=False,
        help_text="Opcional. Ex.: segunda e terça até 14/11 e segunda a sexta a partir de 15/11. Vale para todas as "
                  "linhas; as horas e os horários continuam os mesmos.",
    )
    dias_depois = DiasField(label="Dias de estágio a partir dessa data", required=False)

    field_order = ["arquivo", "orientador", "acompanhamento_desde", *CAMPOS_ESCALA, "mudanca_desde", "dias_depois",
                   "carga_cursos_novos", "completar_concedentes"]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["dias"].label = "Dias de estágio (padrão)"
        self.fields["dias"].help_text = "Usados quando a coluna “Dias de estágio” estiver vazia."
        self.fields["horas_por_dia"].help_text = ("Usadas nas linhas sem “Horas por dia” nem horários. Qualquer carga: "
                                                  "4, 5, 7, 8… Vazio = cada linha precisa trazer as horas ou os horários.")
        self.fields["horario_entrada"].help_text = "Horários são opcionais: o supervisor da concedente define depois."

    def clean_arquivo(self):
        arq = self.cleaned_data["arquivo"]
        if arq.size > 5 * 1024 * 1024:
            raise forms.ValidationError("O arquivo deve ter no máximo 5 MB.")
        return arq

    def clean(self):
        d = super().clean()
        if d.get("mudanca_desde") and not d.get("dias_depois"):
            self.add_error("dias_depois", "Escolha os dias de estágio a partir da mudança.")
        elif d.get("dias_depois") and not d.get("mudanca_desde"):
            self.add_error("mudanca_desde", "Informe a partir de quando os dias mudam.")
        return d


# ------------------------------------------------------------------ folhas de frequência enviadas pelo orientador

TIPOS_FOLHA = {b"%PDF-": "pdf", b"\x89PNG": "png", b"\xff\xd8\xff": "jpg"}


class FolhaEnviadaForm(Formulario):
    mes = forms.CharField(label="Mês da folha", widget=forms.TextInput(attrs={"type": "month"}))
    turma = forms.ModelChoiceField(queryset=Turma.objects.none(), required=False, label="Para toda a turma")
    estagios = forms.ModelMultipleChoiceField(queryset=Estagio.objects.none(), required=False,
                                              widget=forms.CheckboxSelectMultiple, label="Ou só para estes estagiários")
    arquivo = forms.FileField(label="Arquivo (PDF ou imagem)",
                              widget=forms.ClearableFileInput(attrs={"accept": "application/pdf,.pdf,image/png,image/jpeg"}))
    observacao = forms.CharField(label="Observação para o estagiário (opcional)", required=False, max_length=200)

    def __init__(self, *a, estagios_qs=None, turmas=None, **kw):
        super().__init__(*a, **kw)
        self.fields["estagios"].queryset = estagios_qs if estagios_qs is not None else Estagio.objects.none()
        self.fields["estagios"].label_from_instance = lambda e: f"{e.estagiario} · {e.turma.rotulo if e.turma_id else e.curso}"
        self.fields["turma"].queryset = turmas if turmas is not None else Turma.objects.none()
        self.fields["turma"].label_from_instance = str
        self.fields["arquivo"].help_text = f"Até {settings.TAMANHO_MAX_ANEXO_MB} MB."

    def clean_mes(self):
        from datetime import date

        try:
            ano, mes = (int(x) for x in self.cleaned_data["mes"].split("-"))
            return date(ano, mes, 1)
        except (ValueError, TypeError):
            raise forms.ValidationError("Escolha o mês.")

    def clean_arquivo(self):
        arq = self.cleaned_data["arquivo"]
        if arq.size > settings.TAMANHO_MAX_ANEXO_MB * 1024 * 1024:
            raise forms.ValidationError(f"O arquivo deve ter no máximo {settings.TAMANHO_MAX_ANEXO_MB} MB.")
        inicio = arq.read(5)
        arq.seek(0)
        ext = next((e for assinatura, e in TIPOS_FOLHA.items() if inicio.startswith(assinatura)), None)
        if not ext:
            raise forms.ValidationError("Envie a folha em PDF, PNG ou JPG.")
        self.extensao = ext
        return arq

    def clean(self):
        d = super().clean()
        if not d.get("turma") and not d.get("estagios"):
            raise forms.ValidationError("Escolha a turma ou marque os estagiários que vão receber a folha.")
        return d


# ------------------------------------------------------------------ importação de calendários


class RecessoForm(Formulario):
    """Recesso de uma concedente (período em que ela não recebe os estagiários)."""

    concedente = forms.ModelChoiceField(queryset=LocalEstagio.objects.none(), label="Concedente")
    data = forms.DateField(label="Primeiro dia", widget=DataInput())
    ate = forms.DateField(label="Último dia", widget=DataInput(), required=False, help_text="Vazio = um dia só.")
    descricao = forms.CharField(label="Descrição", max_length=120, initial="Recesso da concedente")

    def __init__(self, *a, concedentes=None, **kw):
        super().__init__(*a, **kw)
        self.fields["concedente"].queryset = concedentes if concedentes is not None else LocalEstagio.objects.filter(ativa=True)
        if concedentes is not None and len(concedentes) == 1:
            self.fields["concedente"].initial = concedentes[0]

    def clean(self):
        d = super().clean()
        if d.get("ate") and d.get("data"):
            if d["ate"] < d["data"]:
                self.add_error("ate", "O último dia é antes do primeiro.")
            elif (d["ate"] - d["data"]).days > 120:
                self.add_error("ate", "Período longo demais (máximo de 120 dias).")
        return d


class ImportarCalendarioForm(Formulario):
    arquivo = forms.FileField(label="Arquivo do calendário (CSV ou ICS)",
                              widget=forms.ClearableFileInput(attrs={"accept": ".csv,.ics,text/csv,text/calendar"}),
                              help_text="ICS é o formato exportado pelo Google Agenda, Outlook e muitas prefeituras.")
    abrangencia = forms.ChoiceField(label="Os itens valem para", choices=DiaSemEstagio.Abrangencia.choices,
                                    widget=forms.RadioSelect, initial=DiaSemEstagio.Abrangencia.MUNICIPIO,
                                    help_text="No CSV, a coluna “tipo” tem prioridade.")
    municipio = forms.CharField(label="Município", required=False, max_length=80,
                                widget=forms.TextInput(attrs={"list": "municipios", "autocomplete": "off"}),
                                help_text="Para feriados municipais (no CSV, a coluna “municipio” tem prioridade).")
    concedente = forms.ModelChoiceField(queryset=LocalEstagio.objects.filter(ativa=True), required=False,
                                        label="Concedente", help_text="Para recessos de uma concedente (no CSV, a "
                                                                      "coluna “concedente” tem prioridade).")
    ano = forms.IntegerField(label="Ano das datas sem ano (dd/mm)", min_value=2000, max_value=2100,
                             help_text="Datas como “23/11” repetem todo ano a partir deste.")
    substituir = forms.BooleanField(
        label="Substituir o que foi importado antes (mesmo município/abrangência e mesmos anos)", required=False,
        help_text="Use ao importar uma versão atualizada do calendário. O que foi cadastrado à mão não é apagado.")

    def clean_arquivo(self):
        arq = self.cleaned_data["arquivo"]
        if arq.size > 5 * 1024 * 1024:
            raise forms.ValidationError("O arquivo deve ter no máximo 5 MB.")
        return arq

    def clean(self):
        d = super().clean()
        if d.get("mudanca_desde") and not d.get("dias_depois"):
            self.add_error("dias_depois", "Escolha os dias de estágio a partir da mudança.")
        elif d.get("dias_depois") and not d.get("mudanca_desde"):
            self.add_error("mudanca_desde", "Informe a partir de quando os dias mudam.")
        return d


# ------------------------------------------------------------------ primeiro acesso

FORMATOS_NASCIMENTO = ["%d/%m/%Y", "%d%m%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d"]


def ler_nascimento(texto, nome=""):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            pass
    raise forms.ValidationError(f"Data de nascimento inválida para {nome}: “{texto}” (use dd/mm/aaaa).")


def validar_nascimento(valor):
    if valor and not (date(1930, 1, 1) <= valor <= timezone.localdate() - timedelta(days=365 * 10)):
        raise forms.ValidationError(f"Data de nascimento fora do esperado: {valor:%d/%m/%Y}.")
    return valor


class NascimentoInput(forms.TextInput):
    """Campo de texto dd/mm/aaaa (no celular, o calendário obriga a voltar 18 anos mês a mês)."""

    def __init__(self, **kw):
        attrs = {"inputmode": "numeric", "placeholder": "dd/mm/aaaa", "maxlength": 10, "autocomplete": "bday",
                 "data-mascara-data": "1", **kw.pop("attrs", {})}
        super().__init__(attrs=attrs, **kw)

    def format_value(self, value):
        return value.strftime("%d/%m/%Y") if hasattr(value, "strftime") else value


class PrimeiroAcessoNascimentoForm(Formulario):
    nome = forms.CharField(label="Nome completo", max_length=150,
                           widget=forms.TextInput(attrs={"autocomplete": "name", "autocapitalize": "words"}),
                           help_text="Nome e todos os sobrenomes, como no termo de compromisso (acentos não importam).")
    nascimento = forms.DateField(label="Data de nascimento", input_formats=FORMATOS_NASCIMENTO, widget=NascimentoInput(),
                                 error_messages={"invalid": "Use o formato dd/mm/aaaa (ex.: 26/04/2007)."})


class PrimeiroAcessoCodigoForm(Formulario):
    usuario = forms.CharField(label="Usuário", max_length=150,
                              widget=forms.TextInput(attrs={"autocomplete": "username", "autocapitalize": "none"}),
                              help_text="O que veio junto com o código (ex.: ana.rocha).")
    codigo = forms.CharField(label="Código de acesso", max_length=20,
                             widget=forms.TextInput(attrs={"autocomplete": "one-time-code", "autocapitalize": "characters",
                                                           "placeholder": "XXXX-XXXX", "spellcheck": "false"}))


# ------------------------------------------------------------------ conta: senha por e-mail, ajuda, modelos de e-mail

class EsqueciSenhaForm(Formulario):
    identificador = forms.CharField(label="Usuário ou e-mail", max_length=254,
                                    widget=forms.TextInput(attrs={"autocomplete": "username", "autocapitalize": "none"}))


class PedidoAjudaForm(Formulario):
    usuario = forms.CharField(label="Seu usuário (se souber)", max_length=150, required=False,
                              widget=forms.TextInput(attrs={"autocapitalize": "none"}))
    nome = forms.CharField(label="Nome completo", max_length=150)
    contato = forms.CharField(label="Como falar com você", max_length=150,
                              help_text="E-mail ou telefone/WhatsApp para o administrador responder.")
    mensagem = forms.CharField(label="O que aconteceu?", max_length=1000, widget=forms.Textarea(attrs={"rows": 4}))
    site = forms.CharField(required=False, widget=forms.HiddenInput)  # armadilha para robôs: pessoas não preenchem


class ModeloEmailForm(Formulario):
    assunto = forms.CharField(max_length=200)
    corpo = forms.CharField(label="Texto", widget=forms.Textarea(attrs={"rows": 14}))
    ativo = forms.BooleanField(label="Enviar este e-mail", required=False)

    def __init__(self, *a, tipo=None, **kw):
        super().__init__(*a, **kw)
        self.tipo = tipo

    def clean(self):
        import re

        from .emails import COMUNS, TIPOS

        dados = super().clean()
        t = TIPOS[self.tipo]
        validas = set(t.variaveis) | set(COMUNS)
        texto = f"{dados.get('assunto', '')} {dados.get('corpo', '')}"
        desconhecidas = sorted(set(re.findall(r"\{(\w+)\}", texto)) - validas)
        if desconhecidas:
            raise forms.ValidationError("Variáveis que este e-mail não tem: " + ", ".join(f"{{{v}}}" for v in desconhecidas)
                                        + ". Use só as da lista ao lado.")
        if "link" in t.variaveis and "{link}" not in dados.get("corpo", "") and self.tipo != "BLOQUEIO":
            raise forms.ValidationError("Este e-mail precisa do {link} no texto: é por ele que a pessoa continua.")
        return dados


class OpiniaoForm(Formulario):
    """Botão “Sua opinião” (período de testes): nota rápida e comentário opcional."""
    NOTAS = [(5, "Ótimo"), (4, "Bom"), (3, "Regular"), (2, "Ruim"), (1, "Muito ruim")]
    TIPOS = [("SUGESTAO", "Sugestão"), ("ERRO", "Algo deu errado"), ("ELOGIO", "Elogio"), ("DUVIDA", "Dúvida")]

    nota = forms.TypedChoiceField(choices=NOTAS, coerce=int, required=False, widget=forms.RadioSelect)
    tipo = forms.ChoiceField(choices=TIPOS, initial="SUGESTAO", widget=forms.RadioSelect)
    mensagem = forms.CharField(max_length=2000, required=False, widget=forms.Textarea(attrs={"rows": 3}))
    pagina = forms.CharField(max_length=300, required=False, widget=forms.HiddenInput)

    def clean(self):
        d = super().clean()
        if not d.get("nota") and not (d.get("mensagem") or "").strip():
            raise forms.ValidationError("Escolha uma nota ou escreva um comentário.")
        return d


# ------------------------------------------------------------------ equipe da concedente


class MembroEquipeForm(Formulario):
    """Responsável pela concedente cadastra alguém da equipe (supervisor ou funcionário que pode substituir)."""
    nome_completo = forms.CharField(label="Nome completo", max_length=150)
    cargo = forms.CharField(label="Cargo/Função", max_length=80, required=False)
    telefone = forms.CharField(label="Telefone / WhatsApp", max_length=30, required=False)
    email = forms.EmailField(label="E-mail", required=False)

    def clean_nome_completo(self):
        nome = " ".join(self.cleaned_data["nome_completo"].split())
        if len(nome.split()) < 2:
            raise forms.ValidationError("Escreva nome e sobrenome.")
        return nome


class SubstituicaoForm(Formulario):
    substituto = forms.ModelChoiceField(label="Quem vai confirmar", queryset=Usuario.objects.none())
    titular = forms.ModelChoiceField(label="No lugar de", queryset=Usuario.objects.none(), required=False,
                                     empty_label="Todos os supervisores da concedente")
    inicio = forms.DateField(label="De", widget=DataInput())
    fim = forms.DateField(label="Até", widget=DataInput())
    motivo = forms.CharField(label="Motivo", max_length=150, required=False,
                             widget=forms.TextInput(attrs={"placeholder": "Ex.: férias do supervisor"}))

    def __init__(self, *a, equipe=None, titular_fixo=None, **kw):
        super().__init__(*a, **kw)
        ativos = equipe.filter(is_active=True) if equipe is not None else Usuario.objects.none()
        self.fields["substituto"].queryset = ativos.exclude(pk=titular_fixo.pk) if titular_fixo else ativos
        self.fields["titular"].queryset = ativos
        if titular_fixo:
            del self.fields["titular"]
        self.fields["substituto"].label_from_instance = lambda u: f"{u.nome_completo}" + (f" · {u.cargo}" if u.cargo else "")
