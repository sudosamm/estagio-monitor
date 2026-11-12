from datetime import timedelta
from decimal import Decimal

from django import forms
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from django.utils.crypto import get_random_string

from .models import (
    DIAS_SEMANA, Agendamento, Candidatura, Configuracao, Curso, DiaSemEstagio, Documento, Estagio, FolhaEnviada,
    LocalEstagio, Mensagem, Registro, Turma, Usuario,
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
        if "horas_por_dia" not in d:
            return {"dias": ",".join(str(x) for x in sorted(d["dias"]))}
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
        widget=forms.Textarea(attrs={"rows": 8, "placeholder": "Maria da Silva Souza\nJoão Pedro Lima; 2024001234"}),
        help_text="Nome completo por linha. Opcional: “; matrícula” depois do nome.",
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
        fields = ["nome_completo", "email", "telefone", "cpf", "matricula", "cargo", "concedentes", "cursos_coordenados"]
        widgets = {"cursos_coordenados": forms.CheckboxSelectMultiple, "concedentes": forms.CheckboxSelectMultiple}

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
        fields = ["nome_escola", "municipio_escola", "ano_referencia", "cabecalho_folha", "logo_folha",
                  "mostrar_codigo_folha", "estagiarios_emitem_folha", "captacao_aberta", "ano_captacao", "captacao_prazo", "texto_captacao",
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
        if "vincular_supervisores" in self.fields:
            qs = supervisores_qs()
            if self.instance.pk:
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


class PlanejarDiaForm(Formulario):
    """Estagiário avisa que vai estagiar num dia fora da escala (reposição) ou com outra carga."""

    horas = campo_horas("Quantas horas vai estagiar")
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
        del self.fields["novos_supervisores"], self.fields["vincular_supervisores"]
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


# ------------------------------------------------------------------ importação em massa


class ImportarCSVForm(CamposEscalaMixin, Formulario):
    arquivo = forms.FileField(label="Arquivo CSV", widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"}),
                              help_text="Uma linha por estagiário. Separado por ponto e vírgula (;) ou vírgula.")
    orientador = forms.ModelChoiceField(
        queryset=Usuario.objects.filter(papel=Usuario.Papel.ORIENTADOR, is_active=True), label="Orientador(a) responsável",
        help_text="Usado nas linhas em que a coluna “orientador” estiver vazia.",
    )
    acompanhamento_desde = forms.DateField(
        label="Acompanhar no sistema a partir de", widget=DataInput(), required=False,
        help_text="Para estágios que já começaram: os dias antes desta data não aparecem como “sem registro”.",
    )
    carga_cursos_novos = forms.IntegerField(label="Carga horária para cursos novos (h)", initial=300, min_value=1,
                                            help_text="Só usada se o CSV trouxer um curso que ainda não existe.")
    completar_concedentes = forms.BooleanField(label="Completar campos vazios de concedentes já cadastradas",
                                               required=False, initial=True)

    field_order = ["arquivo", "orientador", "acompanhamento_desde", *CAMPOS_ESCALA, "carga_cursos_novos",
                   "completar_concedentes"]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["dias"].label = "Dias de estágio (padrão)"
        self.fields["dias"].help_text = "Usados quando a coluna “dias” do CSV estiver vazia."
        self.fields["horario_entrada"].help_text = "Horários são opcionais: o supervisor da concedente define depois."

    def clean_arquivo(self):
        arq = self.cleaned_data["arquivo"]
        if arq.size > 2 * 1024 * 1024:
            raise forms.ValidationError("O arquivo deve ter no máximo 2 MB.")
        return arq


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
        if arq.size > 2 * 1024 * 1024:
            raise forms.ValidationError("O arquivo deve ter no máximo 2 MB.")
        return arq
