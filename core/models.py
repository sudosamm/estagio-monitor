from datetime import date
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone

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


class Usuario(AbstractUser):
    class Papel(models.TextChoices):
        ORIENTADOR = "ORIENTADOR", "Orientador(a)"
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


class Curso(models.Model):
    nome = models.CharField(max_length=120, unique=True)
    carga_horaria = models.PositiveIntegerField("Carga horária total (h)", default=300)
    horas_por_dia_padrao = models.DecimalField("Horas por dia (padrão)", max_digits=4, decimal_places=2, default=Decimal("4"))

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class LocalEstagio(models.Model):
    nome = models.CharField("Nome da concedente", max_length=160)
    endereco = models.CharField("Endereço", max_length=255, blank=True)
    bairro = models.CharField(max_length=80, blank=True)
    cidade = models.CharField(max_length=80, blank=True)
    telefone = models.CharField(max_length=30, blank=True)
    link_mapa = models.URLField("Link do mapa", blank=True)
    observacoes = models.TextField("Observações", blank=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "local de estágio"
        verbose_name_plural = "locais de estágio"

    def __str__(self):
        return self.nome

    @property
    def endereco_completo(self):
        return ", ".join(p for p in [self.endereco, self.bairro, self.cidade] if p)


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
        if usuario.is_superuser:
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
    def horario_display(self):
        if self.horario_entrada and self.horario_saida:
            return f"{self.horario_entrada:%H:%M}–{self.horario_saida:%H:%M}"
        return ""


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
    hora_chegada = models.TimeField(null=True, blank=True)
    hora_saida = models.TimeField(null=True, blank=True)
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

    def confirmar(self, usuario, status, obs=""):
        self.confirmacao = status
        self.confirmado_por = usuario
        self.confirmado_em = timezone.now()
        if obs:
            self.obs_supervisor = obs


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
