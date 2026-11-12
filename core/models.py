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
    "escalas": "Mudar os dias de estágio (os horários são definidos pelo supervisor da concedente)",
    "feriados": "Feriados e eventos da escola",
    "arquivos": "Publicar arquivos gerais",
    "folhas": "Emitir e enviar folhas de frequência; decidir se os estagiários emitem a própria",
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
    concedentes = models.ManyToManyField(
        "LocalEstagio", blank=True, related_name="supervisores", verbose_name="Concedentes",
        help_text="Concedentes em que a pessoa é supervisora. Só pode supervisionar estagiários dessas concedentes.",
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
    avisos_email = models.BooleanField(
        "Receber os avisos também por e-mail", default=True,
        help_text="Os mesmos avisos do sino (presenças, visitas, folhas, feriados), no e-mail cadastrado acima.",
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
    def concedentes_txt(self):
        return ", ".join(str(c) for c in self.concedentes.all())

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


class Turma(models.Model):
    """Turma de um curso, identificada pelo ano de ingresso. Ex.: a turma de 2024 estagia em 2026.

    O nome costuma se repetir todo ano (é o mesmo curso); o que separa uma turma da outra é o ano.
    As listas do sistema mostram as turmas do ano de referência (ver Configuracao.ano_referencia).
    """

    curso = models.ForeignKey(Curso, on_delete=models.PROTECT, related_name="turmas")
    nome = models.CharField("Nome da turma", max_length=40, blank=True,
                            help_text="Ex.: 3º A. Vazio = nome do curso. Pode repetir o nome dos anos anteriores.")
    ano_ingresso = models.PositiveIntegerField("Ano de ingresso", help_text="Ex.: 2024 (turma de 2024)")
    ano_estagio = models.PositiveIntegerField("Ano do estágio (referência)",
                                              help_text="Ano em que a turma estagia. Ex.: a turma de 2024 estagia em 2026.")
    ativa = models.BooleanField("Ativa", default=True, help_text="Turmas inativas não aparecem nos cadastros.")

    class Meta:
        ordering = ["-ano_estagio", "curso__nome", "nome"]
        constraints = [models.UniqueConstraint(fields=["curso", "nome", "ano_ingresso"], name="turma_unica")]

    def __str__(self):
        return f"{self.curso.nome}{' · ' + self.nome if self.nome else ''} — turma {self.ano_ingresso} (estágio {self.ano_estagio})"

    @property
    def rotulo(self):
        """Curto, para listas: “3º A · 2024” ou “Técnico em Informática · 2024”."""
        return f"{self.nome or self.curso.nome} · {self.ano_ingresso}"

    def clean(self):
        if self.ano_ingresso and self.ano_estagio and self.ano_estagio < self.ano_ingresso:
            raise ValidationError({"ano_estagio": "O ano do estágio não pode ser antes do ano de ingresso."})


CAMPOS_CONCEDENTE = [
    "tipo_concedente", "razao_social", "nome", "tipo_instituicao", "atividade", "cnpj", "matriz_filial",
    "endereco", "numero", "bairro", "complemento", "cidade", "uf", "cep", "telefone",
    "representante_nome", "representante_email", "representante_cpf", "representante_documento", "link_mapa",
    "observacoes",
]


class LocalEstagio(DadosConcedente):
    """Concedente: empresa, órgão ou profissional liberal que recebe estagiários."""

    ativa = models.BooleanField("Ativa", default=True,
                                help_text="Concedentes inativas não aparecem nos cadastros de estágio e supervisores.")
    # check-in com localização: ponto da concedente e distância aceita
    latitude = models.DecimalField("Latitude", max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField("Longitude", max_digits=9, decimal_places=6, null=True, blank=True)
    raio_checkin = models.PositiveIntegerField(
        "Distância aceita (metros)", default=300,
        help_text="Até quantos metros do ponto da concedente a marcação de presença é considerada “no local”.",
    )

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
    # PROTECT: o supervisor só sai de um estágio quando outro é posto no lugar (ver Estagio.clean e TrocaSupervisor)
    supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="estagios_supervisionados", limit_choices_to={"papel": Usuario.Papel.SUPERVISOR},
    )
    curso = models.ForeignKey(Curso, on_delete=models.PROTECT, related_name="estagios")
    turma = models.ForeignKey(Turma, null=True, blank=True, on_delete=models.PROTECT, related_name="estagios")
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

    def clean(self):
        super().clean()
        if self.turma_id and self.curso_id and self.turma.curso_id != self.curso_id:
            raise ValidationError({"turma": "A turma é de outro curso."})
        if self.pk and not self.supervisor_id:
            antes = Estagio.objects.filter(pk=self.pk).values_list("supervisor_id", flat=True).first()
            if antes:
                raise ValidationError({"supervisor": "O supervisor só pode ser trocado por outro, nunca retirado."})
        if self.supervisor_id and self.local_id and not self.supervisor.concedentes.filter(pk=self.local_id).exists():
            raise ValidationError({"supervisor": f"{self.supervisor} não está cadastrado(a) como supervisor(a) de "
                                                 f"{self.local}. Vincule-o(a) a essa concedente primeiro."})

    def pode_ver(self, usuario):
        if usuario.is_superuser or usuario.coordena(self.curso_id):
            return True
        return usuario.pk in {self.estagiario_id, self.orientador_id, self.supervisor_id}

    def participantes(self):
        return [u for u in [self.estagiario, self.orientador, self.supervisor] if u]


class TrocaSupervisor(models.Model):
    """Histórico de troca do supervisor de um estágio (só o orientador/coordenador troca)."""

    estagio = models.ForeignKey(Estagio, on_delete=models.CASCADE, related_name="trocas_supervisor")
    anterior = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    novo = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    motivo = models.CharField(max_length=200, blank=True)
    feita_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    feita_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-feita_em"]


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


def chave_municipio(nome):
    """“São Gonçalo do Amarante - CE” e “SAO GONCALO DO AMARANTE” viram a mesma chave."""
    import re
    import unicodedata

    texto = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode().lower()
    texto = re.sub(r"\s*[-/(]\s*[a-z]{2}\)?\s*$", "", texto.strip())  # tira “- CE”, “/CE”, “(CE)”
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", texto).split())


class DiaSemEstagio(models.Model):
    """Feriados, recessos, eventos da escola — dias em que o estagiário não vai ao estágio.

    Abrangência:
    - ESCOLA: eventos e recessos do orientador (só os estagiários dele; pode ser de um curso).
    - MUNICIPIO: feriado municipal — vale para os estágios em concedentes daquele município.
    - TODOS: feriado nacional ou estadual — vale para todos os estágios.
    - CONCEDENTE: recesso de uma concedente — vale só para os estágios nela.
    `anual` repete o feriado na mesma data todo ano (aniversário da cidade, padroeiro…).
    `origem` diz de onde veio ("manual", "calendario"); prepara a importação automática de calendários.
    """

    class Abrangencia(models.TextChoices):
        ESCOLA = "ESCOLA", "Evento ou recesso da escola"
        MUNICIPIO = "MUNICIPIO", "Feriado municipal"
        TODOS = "TODOS", "Feriado nacional ou estadual"
        CONCEDENTE = "CONCEDENTE", "Recesso de uma concedente"

    data = models.DateField()
    descricao = models.CharField(max_length=120)
    abrangencia = models.CharField("Vale para", max_length=10, choices=Abrangencia.choices, default=Abrangencia.ESCOLA)
    municipio = models.CharField("Município", max_length=80, blank=True)
    municipio_chave = models.CharField(max_length=80, blank=True, db_index=True, editable=False)
    uf = models.CharField("UF", max_length=2, blank=True, default="CE")
    concedente = models.ForeignKey("LocalEstagio", null=True, blank=True, on_delete=models.CASCADE,
                                   related_name="recessos", help_text="Para recesso de uma concedente")
    anual = models.BooleanField("Repete todo ano nesta data", default=False)
    origem = models.CharField(max_length=20, blank=True, default="manual")
    orientador = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dias_sem_estagio",
                                   help_text="Quem cadastrou. Em eventos da escola, só vale para os estagiários dele.")
    curso = models.ForeignKey(Curso, null=True, blank=True, on_delete=models.CASCADE, help_text="Vazio = todos os cursos")

    class Meta:
        ordering = ["data"]
        verbose_name = "dia sem estágio"
        verbose_name_plural = "dias sem estágio"

    def __str__(self):
        return f"{self.data:%d/%m/%Y} — {self.descricao}"

    def save(self, *args, **kwargs):
        self.municipio_chave = chave_municipio(self.municipio) if self.abrangencia == self.Abrangencia.MUNICIPIO else ""
        super().save(*args, **kwargs)

    def ocorrencias(self, inicio, fim):
        """Datas em que vale dentro do período (o anual se repete em cada ano)."""
        if not self.anual:
            return [self.data] if inicio <= self.data <= fim else []
        datas = []
        for ano in range(max(inicio.year, self.data.year), fim.year + 1):
            try:
                dia = self.data.replace(year=ano)
            except ValueError:  # 29/02 em ano não bissexto
                continue
            if inicio <= dia <= fim:
                datas.append(dia)
        return datas


def _metros_txt(m):
    return f"{m} m" if m < 1000 else f"{m / 1000:.1f} km".replace(".", ",")


def descrever_geo(geo, local):
    """Resumo da localização de uma marcação: {"texto", "longe", "mapa"} (ou None se não foi pedida)."""
    if not geo:
        return None
    if geo.get("erro"):
        return {"texto": f"localização não informada ({geo['erro']})", "longe": None, "mapa": ""}
    mapa = f"https://www.google.com/maps?q={geo['lat']},{geo['lng']}"
    dist = geo.get("distancia")
    if dist is None:
        return {"texto": "localização registrada (concedente sem ponto no mapa)", "longe": None, "mapa": mapa}
    raio = geo.get("raio") or (local.raio_checkin if local else 300)
    longe = dist - min(geo.get("precisao") or 0, 150) > raio
    return {"texto": f"a {_metros_txt(dist)} da concedente", "longe": longe, "mapa": mapa}


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
    # localização no momento da marcação: {"lat", "lng", "precisao", "distancia"} ou {"erro": "..."}
    geo_entrada = models.JSONField("Localização da entrada", null=True, blank=True)
    geo_saida = models.JSONField("Localização da saída", null=True, blank=True)
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

    @property
    def local_entrada(self):
        return descrever_geo(self.geo_entrada, self.estagio.local)

    @property
    def local_saida(self):
        return descrever_geo(self.geo_saida, self.estagio.local)

    def calcular_horas(self):
        """Horas trabalhadas pelos horários (entrada até saída, menos o intervalo). None se faltar entrada/saída."""
        if not (self.hora_chegada and self.hora_saida):
            return None
        m = lambda t: t.hour * 60 + t.minute  # noqa: E731
        minutos = m(self.hora_saida) - m(self.hora_chegada)
        if self.saida_intervalo and self.volta_intervalo:
            minutos -= m(self.volta_intervalo) - m(self.saida_intervalo)
        if minutos <= 0:
            return None
        return (Decimal(minutos) / 60).quantize(Decimal("0.01"))

    def confirmar(self, usuario, status, obs=""):
        self.confirmacao = status
        self.confirmado_por = usuario
        self.confirmado_em = timezone.now()
        if obs:
            self.obs_supervisor = obs

    # ---- histórico: cada mudança de horário, situação ou validação fica guardada (quem, quando, de → para)
    CAMPOS_HISTORICO = ["situacao", "hora_chegada", "saida_intervalo", "volta_intervalo", "hora_saida", "horas",
                        "confirmacao", "motivo"]

    @classmethod
    def from_db(cls, db, field_names, values):
        inst = super().from_db(db, field_names, values)
        inst._antes = inst._estado()
        return inst

    def _estado(self):
        return {c: getattr(self, c) for c in self.CAMPOS_HISTORICO if c not in self.get_deferred_fields()}

    def anotar(self, usuario, acao, request=None):
        """Diz quem está mudando o registro e como (botão, digitou, lançamento…) antes de salvar."""
        self._autor, self._acao = usuario, acao
        if request is not None:
            self._ip = (request.META.get("HTTP_CF_CONNECTING_IP")
                        or request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
                        or request.META.get("REMOTE_ADDR")) or None
        return self

    def _texto(self, campo, valor):
        if valor in (None, ""):
            return "—"
        if campo in ("situacao", "confirmacao"):
            return dict(self._meta.get_field(campo).choices).get(valor, valor)
        if hasattr(valor, "strftime"):
            return valor.strftime("%H:%M")
        if campo == "horas":
            d = Decimal(valor)
            return f"{d.normalize():f}h" if d != d.to_integral_value() else f"{int(d)}h"
        return str(valor)[:120]

    def save(self, *args, **kwargs):
        antes = getattr(self, "_antes", None)
        super().save(*args, **kwargs)
        depois = self._estado()
        mudancas = []
        for c, valor in depois.items():
            velho = antes.get(c) if antes is not None else None
            if antes is not None and c not in antes:
                continue
            if (antes is None and valor not in (None, "", 0, Decimal(0))) or (antes is not None and velho != valor):
                rotulo = self._meta.get_field(c).verbose_name
                mudancas.append([str(rotulo)[:1].upper() + str(rotulo)[1:], self._texto(c, velho) if antes is not None
                                 else "—", self._texto(c, valor)])
        if mudancas:
            HistoricoRegistro.objects.create(
                estagio_id=self.estagio_id, data=self.data, registro=self, usuario=getattr(self, "_autor", None),
                acao=getattr(self, "_acao", "") or ("CRIOU" if antes is None else "ALTEROU"), mudancas=mudancas,
                ip=getattr(self, "_ip", None))
        self._antes = depois

    def delete(self, *args, **kwargs):
        HistoricoRegistro.objects.create(
            estagio_id=self.estagio_id, data=self.data, usuario=getattr(self, "_autor", None),
            acao=getattr(self, "_acao", "") or "EXCLUIU", ip=getattr(self, "_ip", None),
            mudancas=[["Registro do dia", f"{self.get_situacao_display()} {self.horario_display}".strip(), "excluído"]])
        return super().delete(*args, **kwargs)


class HistoricoRegistro(models.Model):
    """Quem mexeu no registro de um dia, quando e o que mudou (inclusive horários: de → para).

    Guardado por estágio + dia, para sobreviver mesmo se o registro for excluído (ex.: ausência cancelada).
    """

    class Acao(models.TextChoices):
        ENTRADA = "ENTRADA", "marcou a entrada pelo botão"
        PONTO = "PONTO", "marcou pelo botão"
        DIGITOU = "DIGITOU", "digitou os horários"
        AUSENCIA = "AUSENCIA", "informou ausência"
        LANCAMENTO = "LANCAMENTO", "lançou/ajustou o registro"
        VALIDACAO = "VALIDACAO", "validou"
        CANCELOU = "CANCELOU", "cancelou a ausência"
        CRIOU = "CRIOU", "criou o registro"
        ALTEROU = "ALTEROU", "alterou o registro"
        EXCLUIU = "EXCLUIU", "excluiu o registro"

    estagio = models.ForeignKey(Estagio, on_delete=models.CASCADE, related_name="historico_registros")
    data = models.DateField(help_text="Dia de estágio a que se refere")
    registro = models.ForeignKey(Registro, null=True, blank=True, on_delete=models.SET_NULL, related_name="historico")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="+")
    em = models.DateTimeField(auto_now_add=True)
    acao = models.CharField(max_length=12, choices=Acao.choices)
    mudancas = models.JSONField(default=list, help_text="[campo, antes, depois]")
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-em", "-pk"]
        indexes = [models.Index(fields=["estagio", "data"])]
        verbose_name = "histórico de registro"
        verbose_name_plural = "históricos de registro"

    def __str__(self):
        return f"{self.data:%d/%m} · {self.usuario} {self.get_acao_display()}"

    @property
    def informado_depois(self):
        """Mexeu depois do próprio dia de estágio (ex.: digitou os horários na semana seguinte)."""
        return timezone.localtime(self.em).date() > self.data


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
    logo_folha = models.ImageField("Brasão / logotipo da folha", upload_to="config/", blank=True,
                                   help_text="Canto superior esquerdo da folha de frequência. Vazio = brasão padrão do "
                                             "Governo do Ceará / SEDUC (o mesmo da folha oficial).")
    ano_referencia = models.PositiveIntegerField(
        "Ano de referência", null=True, blank=True,
        help_text="As listas mostram os estagiários das turmas que estagiam neste ano. Vazio = ano atual.",
    )
    class Localizacao(models.TextChoices):
        DESLIGADO = "DESLIGADO", "Não pedir a localização"
        REGISTRAR = "REGISTRAR", "Registrar e avisar quando estiver longe da concedente"
        EXIGIR = "EXIGIR", "Exigir estar perto da concedente para marcar presença"

    checkin_localizacao = models.CharField(
        "Localização ao marcar presença", max_length=10, choices=Localizacao.choices, default=Localizacao.DESLIGADO,
        help_text="O celular do estagiário pede permissão de localização só na hora de marcar entrada e saída. "
                  "Para comparar, cadastre o ponto de cada concedente (ficha da concedente → Localização).",
    )
    avisos_email = models.BooleanField(
        "Enviar os avisos também por e-mail", default=True,
        help_text="Para quem tem e-mail cadastrado e não desligou no perfil. Precisa do servidor de e-mail configurado "
                  "(variáveis EMAIL_HOST etc.).",
    )
    estagiarios_emitem_folha = models.BooleanField(
        "Estagiários emitem a própria folha de frequência", default=True,
        help_text="Desligado: o estagiário só baixa a folha que o orientador enviar para o mês.",
    )
    mostrar_codigo_folha = models.BooleanField(
        "Imprimir código de controle no rodapé da folha", default=True,
        help_text="Linha discreta “Emitida em … · cód. XXXX” que permite saber quem emitiu cada folha impressa.",
    )
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
    def ano_referencia_efetivo(self):
        return self.ano_referencia or timezone.localdate().year

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
    folha_enviada = models.ForeignKey("FolhaEnviada", null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name="downloads", help_text="Preenchido quando foi um download da folha enviada")

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


def caminho_folha(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "pdf"
    return f"folhas/{instance.mes:%Y-%m}/{get_random_string(16)}.{ext}"


class FolhaEnviada(models.Model):
    """Folha de frequência de um mês que o orientador envia para os estagiários baixarem e imprimirem."""

    mes = models.DateField(help_text="Primeiro dia do mês da folha")
    turma = models.ForeignKey(Turma, null=True, blank=True, on_delete=models.CASCADE, related_name="folhas_enviadas",
                              help_text="Para todos os estagiários da turma")
    estagios = models.ManyToManyField(Estagio, blank=True, related_name="folhas_enviadas",
                                      help_text="Ou só para estes estagiários")
    arquivo = models.FileField(upload_to=caminho_folha)
    nome_original = models.CharField(max_length=255, blank=True)
    observacao = models.CharField("Observação", max_length=200, blank=True)
    enviado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    enviado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-mes", "-enviado_em"]
        verbose_name = "folha de frequência enviada"
        verbose_name_plural = "folhas de frequência enviadas"

    def __str__(self):
        return f"Frequência {self.mes:%m/%Y} — {self.destino}"

    @property
    def destino(self):
        if self.turma_id:
            return str(self.turma.rotulo)
        nomes = [str(e.estagiario) for e in self.estagios.all()]
        return ", ".join(nomes[:3]) + (f" e mais {len(nomes) - 3}" if len(nomes) > 3 else "")

    @classmethod
    def do_estagio(cls, estagio):
        filtro = models.Q(estagios=estagio)
        if estagio.turma_id:
            filtro |= models.Q(turma_id=estagio.turma_id)
        return cls.objects.filter(filtro).distinct()

    def alcanca(self, estagio):
        return (self.turma_id and self.turma_id == estagio.turma_id) or self.estagios.filter(pk=estagio.pk).exists()

    def estagios_alvo(self):
        if self.turma_id:
            return Estagio.objects.filter(models.Q(turma_id=self.turma_id) | models.Q(folhas_enviadas=self)).distinct()
        return self.estagios.all()

    @property
    def extensao(self):
        nome = self.nome_original or self.arquivo.name
        return nome.rsplit(".", 1)[-1].upper() if "." in nome else "ARQ"
