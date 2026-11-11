from datetime import timedelta

from django import forms
from django.conf import settings
from django.utils import timezone

from .models import (
    DIAS_SEMANA, Agendamento, Curso, DiaSemEstagio, Documento, Estagio, LocalEstagio, Mensagem,
    Registro, Usuario,
)


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


class CamposEscalaMixin(forms.Form):
    dias = DiasField(initial=[0, 1])
    horario_entrada = forms.TimeField(label="Entrada", required=False, widget=HoraInput())
    horario_saida = forms.TimeField(label="Saída", required=False, widget=HoraInput())
    horas_por_dia = forms.DecimalField(label="Horas por dia", min_value=0.5, max_value=12, decimal_places=2, initial=4)

    def clean(self):
        dados = super().clean()
        ent, sai = dados.get("horario_entrada"), dados.get("horario_saida")
        if ent and sai and sai <= ent:
            self.add_error("horario_saida", "A saída deve ser depois da entrada.")
        return dados

    def dados_escala(self):
        d = self.cleaned_data
        return {
            "dias": ",".join(str(x) for x in sorted(d["dias"])),
            "horario_entrada": d.get("horario_entrada"),
            "horario_saida": d.get("horario_saida"),
            "horas_por_dia": d["horas_por_dia"],
        }


class EscalaLoteForm(CamposEscalaMixin, Formulario):
    estagios = forms.ModelMultipleChoiceField(
        queryset=Estagio.objects.none(), widget=forms.CheckboxSelectMultiple, label="Estagiários"
    )
    vigente_desde = forms.DateField(label="Vale a partir de", widget=DataInput())

    field_order = ["vigente_desde", "dias", "horario_entrada", "horario_saida", "horas_por_dia", "estagios"]

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
    local = forms.ModelChoiceField(queryset=LocalEstagio.objects.all(), required=False, label="Local de estágio")
    supervisor = forms.ModelChoiceField(
        queryset=Usuario.objects.filter(papel=Usuario.Papel.SUPERVISOR, is_active=True), required=False
    )
    setor = forms.CharField(required=False, max_length=100)
    data_inicio = forms.DateField(label="Início do estágio", widget=DataInput())
    data_fim = forms.DateField(label="Término previsto", widget=DataInput(), required=False)

    field_order = [
        "nomes", "curso", "turma", "local", "setor", "supervisor", "data_inicio", "data_fim",
        "dias", "horario_entrada", "horario_saida", "horas_por_dia",
    ]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["supervisor"].label_from_instance = lambda u: f"{u} ({u.local or 'sem local'})"

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
    local = forms.ModelChoiceField(queryset=LocalEstagio.objects.all(), label="Local de estágio")
    cargo = forms.CharField(required=False, max_length=80, label="Cargo/Função")

    def clean_nomes(self):
        linhas = []
        for bruto in self.cleaned_data["nomes"].splitlines():
            if not bruto.strip():
                continue
            nome, _, tel = bruto.partition(";")
            nome = " ".join(nome.split())
            if len(nome.split()) < 2:
                raise forms.ValidationError(f"Informe nome e sobrenome: “{nome}”.")
            linhas.append((nome, tel.strip()))
        if not linhas:
            raise forms.ValidationError("Informe ao menos um nome.")
        return linhas


class OrientadorForm(Formulario):
    nome = forms.CharField(label="Nome completo", max_length=150)
    email = forms.EmailField(required=False)


class UsuarioEditForm(FormularioModelo):
    class Meta:
        model = Usuario
        fields = ["nome_completo", "email", "telefone", "matricula", "cargo", "local", "is_active"]
        labels = {"is_active": "Conta ativa"}


class PerfilForm(FormularioModelo):
    class Meta:
        model = Usuario
        fields = ["email", "telefone"]


# ------------------------------------------------------------------ cadastros


class CursoForm(FormularioModelo):
    class Meta:
        model = Curso
        fields = ["nome", "carga_horaria", "horas_por_dia_padrao"]


class LocalForm(FormularioModelo):
    class Meta:
        model = LocalEstagio
        fields = ["nome", "endereco", "bairro", "cidade", "telefone", "link_mapa", "observacoes"]


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

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["supervisor"].queryset = Usuario.objects.filter(papel=Usuario.Papel.SUPERVISOR, is_active=True)
        self.fields["supervisor"].label_from_instance = lambda u: f"{u} ({u.local or 'sem local'})"


class EscalaForm(CamposEscalaMixin, Formulario):
    vigente_desde = forms.DateField(label="Vale a partir de", widget=DataInput())
    field_order = ["vigente_desde", "dias", "horario_entrada", "horario_saida", "horas_por_dia"]


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


class DiarioForm(Formulario):
    diario = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "O que você fez, aprendeu ou teve dificuldade hoje?"}),
        required=False, label="Como foi o dia",
    )


class LancamentoForm(FormularioModelo):
    """Supervisor ou orientador lança/ajusta o registro de um dia."""

    class Meta:
        model = Registro
        fields = ["situacao", "horas", "hora_chegada", "hora_saida", "confirmacao", "motivo", "obs_supervisor"]
        widgets = {"hora_chegada": HoraInput(), "hora_saida": HoraInput()}
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
