from datetime import date
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string

DIAS_SEMANA = [
    (0, "Segunda"),
    (1, "Terça"),
    (2, "Quarta"),
    (3, "Quinta"),
    (4, "Sexta"),
    (5, "Sábado"),
    (6, "Domingo"),
]
DIAS_ABREV = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


# O que cada papel de gestão pode fazer. Para tirar ou dar uma permissão ao coordenador,
# basta editar o conjunto dele aqui (o superusuário/administrador pode tudo).
PERMISSOES = {
    "painel": "Painel, lista de estagiários, tela do estágio, lançar e validar registros",
    "estagiarios": "Cadastrar estagiários",
    "contas": "Contas: supervisores, edição de dados e senha padrão",
    "cadastros": "Cursos e concedentes",
    "candidaturas": "Captação: analisar cadastros de concedentes",
    "frequencias": "Ver quem abriu e imprimiu a folha de frequência",
    "agenda": "Agendar visitas e conversas",
    "escalas": "Mudar dias e horários de estágio",
    "feriados": "Feriados e eventos da escola",
    "arquivos": "Publicar arquivos gerais",
}
PERMISSOES_POR_PAPEL = {
    "ORIENTADOR": set(PERMISSOES),
    "COORDENADOR": {"painel", "estagiarios", "contas", "cadastros", "candidaturas", "frequencias"},
}


class Usuario(AbstractUser):
    class Papel(models.TextChoices):
        ORIENTADOR = "ORIENTADOR", "Orientador(a)"
        COORDENADOR = "COORDENADOR", "Coordenador(a) de curso"
        SUPERVISOR = "SUPERVISOR", "Supervisor(a)"
        ESTAGIARIO = "ESTAGIARIO", "Estagiário(a)"

    papel = models.CharField(max_length=12, choices=Papel.choices, default=Papel.ESTAGIARIO)
    nome_completo = models.CharField(max_length=150)
    telefone = models.CharField(max_length=30, blank=True)
    matricula = models.CharField("Matrícula", max_length=40, blank=True)
    cargo = models.CharField("Cargo/Função", max_length=80, blank=True, help_text="Para supervisores")
    local = models.ForeignKey(
        "LocalEstagio", null=True, blank=True, on_delete=models.SET_NULL, related_name="supervisores",
        help_text="Local onde o supervisor trabalha",
    )
    cpf = models.CharField("CPF", max_length=14, blank=True)
    foto = models.ImageField(upload_to="fotos/", blank=True)
    # perfil profissional (banco de talentos)
    apresentacao = models.TextField("Sobre mim", blank=True, help_text="Uma apresentação curta: objetivos, interesses, experiências.")
    habilidades = models.TextField("Habilidades", blank=True, help_text="Separe por vírgulas. Ex.: Excel, atendimento, redes")
    curriculo = models.FileField("Currículo (PDF)", upload_to="curriculos/", blank=True)
    perfil_visivel = models.BooleanField(
        "Mostrar meu perfil às concedentes", default=False,
        help_text="Quando o banco de talentos estiver aberto, supervisores das concedentes poderão ver seu perfil e currículo.",
    )
    cursos_coordenados = models.ManyToManyField(
        "Curso", blank=True, related_name="coordenadores", verbose_name="Cursos que coordena",
        help_text="Vazio = todos os cursos.",
    )
    deve_trocar_senha = models.BooleanField(default=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["nome_completo"]
        verbose_name = "usuário"

    def __str__(self):
        return self.nome_completo or self.username

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.papel = self.Papel.ORIENTADOR
        if not self.nome_completo:
            self.nome_completo = f"{self.first_name} {self.last_name}".strip() or self.username
        super().save(*args, **kwargs)

    @property
    def is_orientador(self):
        return self.papel == self.Papel.ORIENTADOR

    @property
    def is_coordenador(self):
        return self.papel == self.Papel.COORDENADOR

    @property
    def is_gestor(self):
        """Orientador, coordenador de curso ou administrador: quem acessa a área de gestão."""
        return self.is_superuser or self.papel in PERMISSOES_POR_PAPEL

    def pode(self, permissao):
        if self.is_superuser:
            return True
        return permissao in PERMISSOES_POR_PAPEL.get(self.papel, ())

    def cursos_ids(self):
        """Cursos que o coordenador acompanha (None = todos)."""
        if not hasattr(self, "_cursos_ids"):
            ids = set(self.cursos_coordenados.values_list("pk", flat=True)) if self.pk else set()
            self._cursos_ids = ids or None
        return self._cursos_ids

    def coordena(self, curso_id):
        ids = self.cursos_ids()
        return self.is_coordenador and (ids is None or curso_id in ids)

    @property
    def is_supervisor(self):
        return self.papel == self.Papel.SUPERVISOR

    @property
    def is_estagiario(self):
        return self.papel == self.Papel.ESTAGIARIO

    @property
    def primeiro_nome(self):
        return (self.nome_completo or self.username).split()[0]

    @property
    def iniciais(self):
        partes = (self.nome_completo or self.username).split()
        return (partes[0][0] + (partes[-1][0] if len(partes) > 1 else "")).upper()

    @property
    def foto_url(self):
        if not self.foto:
            return ""
        versao = self.foto.name.rsplit("/", 1)[-1].split(".")[0][-6:]
        return reverse("foto_usuario", args=[self.pk]) + f"?v={versao}"

    @property
    def habilidades_lista(self):
        return [h.strip() for h in self.habilidades.replace("\n", ",").split(",") if h.strip()]


class Curso(models.Model):
    nome = models.CharField(max_length=120, unique=True)
    carga_horaria = models.PositiveIntegerField("Carga horária total (h)", default=300)
    horas_por_dia_padrao = models.DecimalField("Horas por dia (padrão)", max_digits=4, decimal_places=2, default=Decimal("4"))

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class DadosConcedente(models.Model):
    """Campos da ficha de cadastro de concedente (usados pela concedente e pela candidatura)."""

    class TipoConcedente(models.TextChoices):
        PJ = "PJ", "Pessoa Jurídica"
        PL = "PL", "Profissional Liberal"

    class TipoInstituicao(models.TextChoices):
        PUBLICA = "PUBLICA", "Pública"
        PRIVADA = "PRIVADA", "Privada"

    class MatrizFilial(models.TextChoices):
        MATRIZ = "MATRIZ", "Matriz"
        FILIAL = "FILIAL", "Filial"

    # dados gerais
    tipo_concedente = models.CharField("Concedente", max_length=2, choices=TipoConcedente.choices, default=TipoConcedente.PJ)
    razao_social = models.CharField("Razão social", max_length=200, blank=True)
    nome = models.CharField("Nome fantasia / unidade", max_length=160,
                            help_text="Como a concedente é conhecida; é o nome que sai na folha de frequência "
                                      "(ex.: EEM São Sebastião)")
    tipo_instituicao = models.CharField("Tipo de instituição", max_length=8, choices=TipoInstituicao.choices, blank=True)
    atividade = models.TextField("Especificação da atividade", blank=True)
    cnpj = models.CharField("CNPJ", max_length=18, blank=True, help_text="Para profissional liberal, informe o CPF")
    matriz_filial = models.CharField("Matriz ou filial", max_length=6, choices=MatrizFilial.choices, blank=True)
    # endereço
    endereco = models.CharField("Endereço", max_length=255, blank=True)
    numero = models.CharField("Nº", max_length=20, blank=True)
    bairro = models.CharField(max_length=80, blank=True)
    complemento = models.CharField(max_length=120, blank=True)
    cidade = models.CharField("Município", max_length=80, blank=True)
    uf = models.CharField("UF", max_length=2, blank=True, default="CE")
    cep = models.CharField("CEP", max_length=9, blank=True)
    telefone = models.CharField(max_length=30, blank=True)
    # representante legal
    representante_nome = models.CharField("Nome", max_length=150, blank=True)
    representante_email = models.EmailField("E-mail", blank=True)
    representante_cpf = models.CharField("CPF", max_length=14, blank=True)
    representante_documento = models.CharField("Doc. de identificação", max_length=40, blank=True, help_text="Ex.: RG 2001234567 SSP/CE")
    # outros
    link_mapa = models.URLField("Link do mapa", blank=True)
    observacoes = models.TextField("Observações", blank=True)

    class Meta:
        abstract = True

    def __str__(self):
        return self.nome

    @property
    def nome_oficial(self):
        return self.razao_social or self.nome

    @property
    def endereco_completo(self):
        rua = ", ".join(p for p in [self.endereco, self.numero] if p)
        cidade = "/".join(p for p in [self.cidade, self.uf if self.cidade else ""] if p)
        return " · ".join(p for p in [rua, self.complemento, self.bairro, cidade] if p)


CAMPOS_CONCEDENTE = [
    "tipo_concedente", "razao_social", "nome", "tipo_instituicao", "atividade", "cnpj", "matriz_filial",
    "endereco", "numero", "bairro", "complemento", "cidade", "uf", "cep", "telefone",
    "representante_nome", "representante_email", "representante_cpf", "representante_documento", "link_mapa",
    "observacoes",
]


class LocalEstagio(DadosConcedente):
    """Concedente: empresa, órgão ou profissional liberal que recebe estagiários."""

    class Meta:
        ordering = ["nome"]
        verbose_name = "concedente"
        verbose_name_plural = "concedentes"


class Estagio(models.Model):
    estagiario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="estagios",
        limit_choices_to={"papel": Usuario.Papel.ESTAGIARIO},
    )
    orientador = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="estagios_orientados",
        limit_choices_to={"papel": Usuario.Papel.ORIENTADOR},
    )
    supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="estagios_supervisionados", limit_choices_to={"papel": Usuario.Papel.SUPERVISOR},
    )
    curso = models.ForeignKey(Curso, on_delete=models.PROTECT, related_name="estagios")
    turma = models.CharField(max_length=40, blank=True)
    local = models.ForeignKey(LocalEstagio, null=True, blank=True, on_delete=models.SET_NULL, related_name="estagios")
    setor = models.CharField(max_length=100, blank=True)
    data_inicio = models.DateField("Início")
    acompanhamento_desde = models.DateField(
        "Acompanhado no sistema desde", null=True, blank=True,
        help_text="Para estágios que começaram antes do sistema: dias anteriores não aparecem como “sem registro”. "
                  "As horas desse período entram em “Horas já cumpridas antes do sistema”.",
    )
    data_fim = models.DateField("Término previsto", null=True, blank=True)
    carga_horaria = models.PositiveIntegerField(
        "Carga horária (h)", null=True, blank=True, help_text="Vazio = usa a carga horária do curso"
    )
    horas_anteriores = models.DecimalField(
        "Horas já cumpridas antes do sistema", max_digits=6, decimal_places=2, default=Decimal("0")
    )
    ativo = models.BooleanField(default=True)
    observacoes_orientador = models.TextField("Anotações privadas do orientador", blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["estagiario__nome_completo"]
        verbose_name = "estágio"

    def __str__(self):
        return f"{self.estagiario} — {self.local or 'sem local'}"

    def get_absolute_url(self):
        return reverse("estagio_detalhe", args=[self.pk])

    @property
    def carga_horaria_total(self):
        return self.carga_horaria or self.curso.carga_horaria

    def escala_em(self, dia: date):
        """Escala vigente em uma data (a mais recente com vigência <= dia)."""
        escalas = getattr(self, "_escalas_cache", None)
        if escalas is None:
            escalas = sorted(self.escalas.all(), key=lambda e: e.vigente_desde, reverse=True)
            self._escalas_cache = escalas
        for e in escalas:
            if e.vigente_desde <= dia:
                return e
        return None

    def pode_ver(self, usuario):
        if usuario.is_superuser or usuario.coordena(self.curso_id):
            return True
        return usuario.pk in {self.estagiario_id, self.orientador_id, self.supervisor_id}

    def participantes(self):
        return [u for u in [self.estagiario, self.orientador, self.supervisor] if u]


class Escala(models.Model):
    """Dias e horário em que o estagiário vai ao local, valendo a partir de uma data.

    Para mudar de 'seg e ter' para 'seg a sex' a partir de 16/11, basta criar
    uma nova escala com vigente_desde = 16/11. O histórico é preservado.
    """

    estagio = models.ForeignKey(Estagio, on_delete=models.CASCADE, related_name="escalas")
    vigente_desde = models.DateField("Vale a partir de")
    dias = models.CharField(max_length=20, help_text="Dias da semana separados por vírgula (0=segunda)")
    horario_entrada = models.TimeField("Entrada", null=True, blank=True)
    saida_intervalo = models.TimeField("Saída para o intervalo", null=True, blank=True)
    volta_intervalo = models.TimeField("Volta do intervalo", null=True, blank=True)
    horario_saida = models.TimeField("Saída", null=True, blank=True)
    horas_por_dia = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("4"))
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-vigente_desde"]
        constraints = [models.UniqueConstraint(fields=["estagio", "vigente_desde"], name="escala_unica_por_data")]

    def __str__(self):
        return f"{self.dias_display} a partir de {self.vigente_desde:%d/%m/%Y}"

    @property
    def dias_lista(self):
        return [int(d) for d in self.dias.split(",") if d.strip() != ""]

    @property
    def dias_display(self):
        lista = self.dias_lista
        if lista == [0, 1, 2, 3, 4]:
            return "Segunda a sexta"
        return ", ".join(DIAS_ABREV[d] for d in lista) or "Nenhum dia"

    @property
    def tem_intervalo(self):
        return bool(self.saida_intervalo and self.volta_intervalo)

    @property
    def horario_display(self):
        return formatar_horario(self.horario_entrada, self.saida_intervalo, self.volta_intervalo, self.horario_saida)


def formatar_horario(entrada, saida_int, volta_int, saida):
    """'07:00–11:00 · 13:00–17:00' (dois turnos) ou '13:00–17:00'."""
    def h(t):
        return f"{t:%H:%M}" if t else "…"

    if saida_int or volta_int:
        if not (entrada or saida):
            return ""
        return f"{h(entrada)}–{h(saida_int)} · {h(volta_int)}–{h(saida)}"
    if entrada and saida:
        return f"{h(entrada)}–{h(saida)}"
    return f"{h(entrada)}–" if entrada else ""


class DiaSemEstagio(models.Model):
    """Feriados, recessos, eventos da escola — dias em que ninguém vai ao estágio."""

    data = models.DateField()
    descricao = models.CharField(max_length=120)
    orientador = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dias_sem_estagio")
    curso = models.ForeignKey(Curso, null=True, blank=True, on_delete=models.CASCADE, help_text="Vazio = todos os cursos")

    class Meta:
        ordering = ["data"]
        verbose_name = "dia sem estágio"
        verbose_name_plural = "dias sem estágio"

    def __str__(self):
        return f"{self.data:%d/%m/%Y} — {self.descricao}"


class Registro(models.Model):
    """O que aconteceu em um dia de estágio."""

    class Situacao(models.TextChoices):
        PRESENTE = "PRESENTE", "Presente"
        AUSENCIA = "AUSENCIA", "Ausência informada"
        FALTA = "FALTA", "Falta"

    class Confirmacao(models.TextChoices):
        PENDENTE = "PENDENTE", "Aguardando supervisor"
        CONFIRMADA = "CONFIRMADA", "Confirmado pelo supervisor"
        CONTESTADA = "CONTESTADA", "Contestado pelo supervisor"

    estagio = models.ForeignKey(Estagio, on_delete=models.CASCADE, related_name="registros")
    data = models.DateField()
    situacao = models.CharField(max_length=10, choices=Situacao.choices)
    horas = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0"))
    hora_chegada = models.TimeField("Entrada", null=True, blank=True)
    saida_intervalo = models.TimeField("Saída para o intervalo", null=True, blank=True)
    volta_intervalo = models.TimeField("Volta do intervalo", null=True, blank=True)
    hora_saida = models.TimeField("Saída", null=True, blank=True)
    motivo = models.TextField("Motivo / justificativa", blank=True)
    diario = models.TextField("Como foi o dia", blank=True)
    confirmacao = models.CharField(max_length=10, choices=Confirmacao.choices, default=Confirmacao.PENDENTE)
    confirmado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    confirmado_em = models.DateTimeField(null=True, blank=True)
    obs_supervisor = models.TextField("Observação do supervisor", blank=True)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-data"]
        constraints = [models.UniqueConstraint(fields=["estagio", "data"], name="registro_unico_por_dia")]

    def __str__(self):
        return f"{self.estagio.estagiario} {self.data:%d/%m} {self.get_situacao_display()}"

    @property
    def horario_display(self):
        return formatar_horario(self.hora_chegada, self.saida_intervalo, self.volta_intervalo, self.hora_saida)

    def confirmar(self, usuario, status, obs=""):
        self.confirmacao = status
        self.confirmado_por = usuario
        self.confirmado_em = timezone.now()
        if obs:
            self.obs_supervisor = obs


class DiaPlanejado(models.Model):
    """Dia que o estagiário planejou estagiar fora da escala (reposição) ou com outra carga horária.

    Entra na previsão de término e aparece no calendário como dia de estágio.
    """

    estagio = models.ForeignKey(Estagio, on_delete=models.CASCADE, related_name="dias_planejados")
    data = models.DateField()
    horas = models.DecimalField(max_digits=4, decimal_places=2)
    motivo = models.CharField(max_length=160, blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["data"]
        constraints = [models.UniqueConstraint(fields=["estagio", "data"], name="planejamento_unico_por_dia")]
        verbose_name = "dia planejado"
        verbose_name_plural = "dias planejados"

    def __str__(self):
        return f"{self.estagio.estagiario} {self.data:%d/%m} ({self.horas}h)"


class Agendamento(models.Model):
    class Tipo(models.TextChoices):
        VISITA = "VISITA", "Visita ao local"
        CONVERSA = "CONVERSA", "Conversa / atendimento"
        REUNIAO = "REUNIAO", "Reunião"

    class Status(models.TextChoices):
        SOLICITADO = "SOLICITADO", "Solicitado"
        AGENDADO = "AGENDADO", "Agendado"
        REALIZADO = "REALIZADO", "Realizado"
        CANCELADO = "CANCELADO", "Cancelado"

    class Modalidade(models.TextChoices):
        PRESENCIAL = "PRESENCIAL", "Presencial"
        ONLINE = "ONLINE", "On-line"
        TELEFONE = "TELEFONE", "Telefone"

    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.VISITA)
    modalidade = models.CharField(max_length=10, choices=Modalidade.choices, default=Modalidade.PRESENCIAL)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SOLICITADO)
    orientador = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="agendamentos_orientador")
    estagios = models.ManyToManyField(Estagio, related_name="agendamentos")
    local = models.ForeignKey(LocalEstagio, null=True, blank=True, on_delete=models.SET_NULL)
    solicitante = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="agendamentos_solicitados")
    data_hora = models.DateTimeField("Data e hora", null=True, blank=True)
    data_sugerida = models.CharField("Sugestão de data/horário", max_length=120, blank=True)
    assunto = models.CharField(max_length=160)
    detalhes = models.TextField(blank=True)
    relato = models.TextField("Relato / ata", blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-data_hora", "-criado_em"]

    def __str__(self):
        return f"{self.get_tipo_display()}: {self.assunto}"

    def get_absolute_url(self):
        return reverse("agendamento_detalhe", args=[self.pk])

    def pode_ver(self, usuario):
        if usuario.is_superuser or usuario.pk in (self.orientador_id, self.solicitante_id):
            return True
        return self.estagios.filter(models.Q(estagiario=usuario) | models.Q(supervisor=usuario)).exists()

    def envolvidos(self):
        users = {self.orientador, self.solicitante}
        for e in self.estagios.select_related("estagiario", "supervisor"):
            users.add(e.estagiario)
            if e.supervisor:
                users.add(e.supervisor)
        return users


def caminho_anexo(instance, filename):
    hoje = timezone.localdate()
    return f"{hoje:%Y/%m}/{filename}"


class Documento(models.Model):
    class Categoria(models.TextChoices):
        FREQUENCIA = "FREQUENCIA", "Folha de frequência"
        TERMO = "TERMO", "Termo / contrato"
        RELATORIO = "RELATORIO", "Relatório"
        AVALIACAO = "AVALIACAO", "Avaliação"
        MODELO = "MODELO", "Modelo / orientação"
        OUTRO = "OUTRO", "Outro"

    titulo = models.CharField("Título", max_length=160)
    categoria = models.CharField(max_length=12, choices=Categoria.choices, default=Categoria.OUTRO)
    arquivo = models.FileField(upload_to=caminho_anexo)
    nome_original = models.CharField(max_length=255, blank=True)
    estagio = models.ForeignKey(
        Estagio, null=True, blank=True, on_delete=models.CASCADE, related_name="documentos",
        help_text="Vazio = disponível para todos os estagiários do orientador",
    )
    curso = models.ForeignKey(Curso, null=True, blank=True, on_delete=models.SET_NULL, help_text="Restringe documento geral a um curso")
    orientador = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="documentos_orientador")
    enviado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="documentos_enviados")
    descricao = models.TextField("Descrição", blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]

    def __str__(self):
        return self.titulo

    def clean(self):
        if self.arquivo and self.arquivo.size > settings.TAMANHO_MAX_ANEXO_MB * 1024 * 1024:
            raise ValidationError({"arquivo": f"O arquivo deve ter no máximo {settings.TAMANHO_MAX_ANEXO_MB} MB."})

    def pode_ver(self, usuario):
        if usuario.is_superuser or usuario.pk in (self.orientador_id, self.enviado_por_id):
            return True
        if self.estagio_id:
            return self.estagio.pode_ver(usuario)
        qs = Estagio.objects.filter(orientador_id=self.orientador_id, ativo=True)
        if self.curso_id:
            qs = qs.filter(curso_id=self.curso_id)
        return qs.filter(models.Q(estagiario=usuario) | models.Q(supervisor=usuario)).exists()

    @property
    def extensao(self):
        nome = self.nome_original or self.arquivo.name
        return nome.rsplit(".", 1)[-1].upper() if "." in nome else "ARQ"


class Mensagem(models.Model):
    """Mural de dúvidas e conversas de um estágio (estagiário, supervisor e orientador)."""

    estagio = models.ForeignKey(Estagio, on_delete=models.CASCADE, related_name="mensagens")
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    texto = models.TextField()
    privada_orientador = models.BooleanField(
        "Somente estagiário e orientador", default=False,
        help_text="Se marcado, o supervisor não vê esta mensagem",
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["criado_em"]


class Notificacao(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notificacoes")
    texto = models.CharField(max_length=255)
    link = models.CharField(max_length=255, blank=True)
    lida = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]


class Configuracao(models.Model):
    """Configurações gerais (registro único), editadas pelo administrador."""

    nome_escola = models.CharField("Escola", max_length=160, blank=True, help_text="Ex.: EEEP Deputado Fulano de Tal")
    municipio_escola = models.CharField("Município da escola", max_length=80, blank=True)
    cabecalho_folha = models.TextField(
        "Cabeçalho da folha de frequência", blank=True,
        default="Coordenadoria de Educação Profissional\nCélula de Estágio - CEPAE",
        help_text="Uma linha por linha do cabeçalho, acima do título “FREQUÊNCIA DE ESTÁGIO”.",
    )
    logo_folha = models.ImageField("Logotipo da folha", upload_to="config/", blank=True,
                                   help_text="Imagem que aparece no canto superior esquerdo da folha de frequência.")
    captacao_aberta = models.BooleanField(
        "Captação de concedentes aberta", default=False,
        help_text="Libera a página pública “Seja uma concedente”, onde empresas se candidatam a receber estagiários.",
    )
    ano_captacao = models.PositiveIntegerField("Ano letivo da captação", null=True, blank=True,
                                               help_text="Vazio = próximo ano.")
    captacao_prazo = models.DateField("Inscrições até", null=True, blank=True)
    texto_captacao = models.TextField(
        "Texto de apresentação da captação", blank=True,
        help_text="Aparece no topo da página pública. Ex.: o que a escola oferece e como funciona o estágio.",
    )
    curriculos_habilitados = models.BooleanField(
        "Estagiários podem preencher perfil profissional e currículo", default=False,
    )
    banco_talentos_habilitado = models.BooleanField(
        "Banco de talentos aberto às concedentes", default=False,
        help_text="Supervisores passam a ver os perfis dos estagiários que autorizaram a exibição.",
    )
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "configuração"
        verbose_name_plural = "configurações"

    def __str__(self):
        return "Configurações do sistema"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def atual(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def ano_captacao_efetivo(self):
        return self.ano_captacao or timezone.localdate().year + 1

    @property
    def captacao_disponivel(self):
        return self.captacao_aberta and (not self.captacao_prazo or timezone.localdate() <= self.captacao_prazo)


def gerar_codigo_impressao():
    return get_random_string(8, "ABCDEFGHJKLMNPQRSTUVWXYZ23456789")


class ImpressaoFrequencia(models.Model):
    """Cada abertura da folha de frequência (e quantas vezes ela foi mandada para a impressora).

    Não aparece para estagiários. O código sai impresso no rodapé da folha.
    """

    estagio = models.ForeignKey(Estagio, on_delete=models.CASCADE, related_name="impressoes")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    mes = models.DateField(help_text="Primeiro dia do mês da folha")
    codigo = models.CharField(max_length=8, unique=True, default=gerar_codigo_impressao)
    aberta_em = models.DateTimeField(auto_now_add=True)
    impressoes = models.PositiveIntegerField(default=0)
    ultima_impressao = models.DateTimeField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    navegador = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-aberta_em"]
        verbose_name = "impressão de frequência"
        verbose_name_plural = "impressões de frequência"

    def __str__(self):
        return f"{self.codigo} — {self.estagio.estagiario} {self.mes:%m/%Y}"


def gerar_protocolo():
    return get_random_string(6, "ABCDEFGHJKLMNPQRSTUVWXYZ23456789")


class Candidatura(DadosConcedente):
    """Empresa/órgão que se cadastrou pela página pública para receber estagiários num ano letivo."""

    class Status(models.TextChoices):
        PENDENTE = "PENDENTE", "Aguardando análise"
        APROVADA = "APROVADA", "Aprovada"
        RECUSADA = "RECUSADA", "Recusada"

    TURNOS = [("MANHA", "Manhã"), ("TARDE", "Tarde"), ("NOITE", "Noite")]

    ano = models.PositiveIntegerField("Ano letivo")
    protocolo = models.CharField(max_length=6, unique=True, default=gerar_protocolo)
    # quem preencheu
    contato_nome = models.CharField("Nome", max_length=150)
    contato_cargo = models.CharField("Cargo", max_length=80, blank=True)
    contato_email = models.EmailField("E-mail", blank=True)
    contato_telefone = models.CharField("Telefone", max_length=30)
    contato_whatsapp = models.BooleanField("Este telefone tem WhatsApp", default=True)
    # supervisor proposto
    supervisor_nome = models.CharField("Nome completo", max_length=150, blank=True)
    supervisor_cargo = models.CharField("Cargo", max_length=80, blank=True)
    supervisor_telefone = models.CharField("Telefone", max_length=30, blank=True)
    supervisor_email = models.EmailField("E-mail", blank=True)
    # proposta
    atividades = models.TextField("Atividades que os estagiários vão realizar")
    turnos = models.CharField("Turnos disponíveis", max_length=40, blank=True)
    horario = models.CharField("Horário proposto", max_length=120, blank=True,
                               help_text="Ex.: 07h às 11h e 13h às 17h, de segunda a sexta")
    beneficios = models.CharField("Benefícios oferecidos", max_length=200, blank=True,
                                  help_text="Opcional. Ex.: bolsa, vale-transporte, alimentação")
    # análise
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDENTE)
    parecer = models.TextField("Parecer", blank=True)
    analisado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name="+")
    analisado_em = models.DateTimeField(null=True, blank=True)
    local = models.ForeignKey(LocalEstagio, null=True, blank=True, on_delete=models.SET_NULL, related_name="candidaturas",
                              verbose_name="Concedente cadastrada")
    criado_em = models.DateTimeField(auto_now_add=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "candidatura de concedente"
        verbose_name_plural = "candidaturas de concedentes"

    def get_absolute_url(self):
        return reverse("captacao_detalhe", args=[self.pk])

    @property
    def turnos_display(self):
        nomes = dict(self.TURNOS)
        return ", ".join(nomes.get(t, t) for t in self.turnos.split(",") if t)

    @property
    def total_vagas(self):
        return sum(v.quantidade for v in self.vagas.all())

    def pode_ver(self, usuario):
        if not usuario.pode("candidaturas"):
            return False
        ids = usuario.cursos_ids() if usuario.is_coordenador else None
        return ids is None or self.vagas.filter(curso_id__in=ids).exists()


class VagaCandidatura(models.Model):
    candidatura = models.ForeignKey(Candidatura, on_delete=models.CASCADE, related_name="vagas")
    curso = models.ForeignKey(Curso, on_delete=models.CASCADE, related_name="vagas_ofertadas")
    quantidade = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["curso__nome"]
        constraints = [models.UniqueConstraint(fields=["candidatura", "curso"], name="vaga_unica_por_curso")]


class AvisoExterno(models.Model):
    """Mensagem para alguém de fora do sistema (por enquanto enviada à mão por WhatsApp, e-mail ou telefone).

    Quando houver envio automático, basta processar os avisos pendentes.
    """

    class Status(models.TextChoices):
        PENDENTE = "PENDENTE", "A enviar"
        ENVIADO = "ENVIADO", "Enviado"
        DESCARTADO = "DESCARTADO", "Não será enviado"

    class Canal(models.TextChoices):
        WHATSAPP = "WHATSAPP", "WhatsApp"
        EMAIL = "EMAIL", "E-mail"
        TELEFONE = "TELEFONE", "Telefone"

    candidatura = models.ForeignKey(Candidatura, null=True, blank=True, on_delete=models.CASCADE, related_name="avisos")
    destinatario = models.CharField(max_length=150)
    email = models.EmailField(blank=True)
    telefone = models.CharField(max_length=30, blank=True)
    assunto = models.CharField(max_length=160)
    mensagem = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDENTE)
    canal = models.CharField(max_length=10, choices=Canal.choices, blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)
    enviado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    enviado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "aviso externo"
        verbose_name_plural = "avisos externos"

    def __str__(self):
        return f"{self.assunto} → {self.destinatario}"

    @property
    def whatsapp_url(self):
        from urllib.parse import quote

        from .validators import so_digitos

        d = so_digitos(self.telefone)
        if len(d) in (10, 11):
            d = "55" + d
        return f"https://wa.me/{d}?text={quote(self.mensagem)}" if len(d) >= 12 else ""

    @property
    def email_url(self):
        from urllib.parse import quote

        if not self.email:
            return ""
        return f"mailto:{self.email}?subject={quote(self.assunto)}&body={quote(self.mensagem)}"
