"""Escolas, redes de ensino e vínculos das pessoas com cada escola (fundação multiescola, Etapa 1).

Ver docs/decisoes/0001-arquitetura-multiescola.md (banco compartilhado com a coluna ``escola``) e
docs/decisoes/0002-escopo-por-escola.md (como o escopo é aplicado).
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


def caminho_identidade(instance, filename):
    import os
    import uuid

    ext = os.path.splitext(filename)[1].lower()[:10]
    if isinstance(instance, Escola):
        return f"escolas/{instance.pk or 'nova'}/identidade/{uuid.uuid4().hex}{ext}"
    return f"redes/{instance.pk or 'nova'}/{uuid.uuid4().hex}{ext}"


class RedeEnsino(models.Model):
    """O que é comum às escolas de uma mesma rede (ex.: SEDUC/CE): secretaria, sistema oficial, marca padrão."""

    nome = models.CharField("Nome", max_length=160, help_text="Ex.: Secretaria da Educação do Ceará")
    uf = models.CharField("UF", max_length=2)
    secretaria = models.CharField("Sigla da secretaria", max_length=40, blank=True, help_text="Ex.: SEDUC")
    sistema_oficial = models.CharField(
        "Sistema oficial", max_length=40, blank=True,
        help_text="Nome do sistema em que a frequência e as avaliações são lançadas oficialmente (ex.: SICE). "
                  "Vazio = os textos dizem “sistema oficial”.")
    sistema_oficial_url = models.URLField("Endereço do sistema oficial", blank=True)
    brasao = models.ImageField("Brasão padrão das folhas", upload_to=caminho_identidade, blank=True)
    brasao_estatico = models.CharField(
        "Brasão padrão (arquivo do sistema)", max_length=120, blank=True,
        help_text="Caminho em static/, usado quando não há brasão enviado. Ex.: img/brasao-ceara-seduc.png")
    cabecalho_folha = models.TextField("Cabeçalho padrão da folha de frequência", blank=True)
    fuso = models.CharField("Fuso horário padrão", max_length=40, default="America/Fortaleza")
    criada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uf", "nome"]
        verbose_name = "rede de ensino"
        verbose_name_plural = "redes de ensino"
        constraints = [models.UniqueConstraint(fields=["nome", "uf"], name="rede_nome_uf_unica")]

    def __str__(self):
        return f"{self.secretaria or self.nome}/{self.uf}"


class Escola(models.Model):
    """Raiz do isolamento: cursos, concedentes, estágios e o resto pertencem a uma escola."""

    class Situacao(models.TextChoices):
        IMPLANTACAO = "IMPLANTACAO", "Em implantação"
        PILOTO = "PILOTO", "Piloto"
        ATIVA = "ATIVA", "Ativa"
        INATIVA = "INATIVA", "Inativa"

    nome = models.CharField("Nome", max_length=160, help_text="Ex.: EEEP Deputado Fulano de Tal")
    slug = models.SlugField("Identificador no endereço", max_length=60, unique=True,
                            help_text="Aparece nos links públicos (ex.: /seja-concedente/<identificador>/).")
    codigo_inep = models.CharField("Código INEP", max_length=8, blank=True)
    cnpj = models.CharField("CNPJ", max_length=18, blank=True)
    rede = models.ForeignKey(RedeEnsino, null=True, blank=True, on_delete=models.PROTECT, related_name="escolas")
    situacao = models.CharField("Situação", max_length=12, choices=Situacao.choices, default=Situacao.IMPLANTACAO)
    municipio = models.CharField("Município", max_length=80, blank=True)
    uf = models.CharField("UF", max_length=2, blank=True)
    fuso = models.CharField("Fuso horário", max_length=40, blank=True, help_text="Vazio = o da rede")
    endereco = models.CharField("Endereço", max_length=255, blank=True)
    telefone = models.CharField("Telefone", max_length=30, blank=True)
    email = models.EmailField("E-mail", blank=True)
    encarregado_dados = models.CharField(
        "Encarregado(a) de dados", max_length=150, blank=True,
        help_text="Nome e contato de quem responde pelos dados pessoais na escola (LGPD).")
    logotipo = models.ImageField("Logotipo", upload_to=caminho_identidade, blank=True)
    brasao = models.ImageField("Brasão da folha", upload_to=caminho_identidade, blank=True,
                               help_text="Vazio = o brasão padrão da rede.")
    cabecalho_folha = models.TextField("Cabeçalho da folha", blank=True, help_text="Vazio = o padrão da rede.")
    criada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "escola"
        verbose_name_plural = "escolas"
        constraints = [models.UniqueConstraint(fields=["codigo_inep"], condition=~models.Q(codigo_inep=""),
                                               name="escola_inep_unico")]

    def __str__(self):
        return self.nome

    @property
    def ativa(self):
        return self.situacao != self.Situacao.INATIVA

    @property
    def fuso_efetivo(self):
        return self.fuso or (self.rede.fuso if self.rede_id else "") or settings.TIME_ZONE

    @property
    def sistema_oficial(self):
        """Nome do sistema oficial da rede ("SICE"), ou o genérico."""
        return (self.rede.sistema_oficial if self.rede_id else "") or "sistema oficial"

    @property
    def nome_instituicao(self):
        """Linha da barra do topo (ex.: Secretaria da Educação do Ceará)."""
        return (self.rede.nome if self.rede_id else "") or settings.NOME_INSTITUICAO


class VinculoEscola(models.Model):
    """Papel de uma pessoa numa escola. Uma conta (um login) pode ter vários vínculos: vários papéis e várias
    escolas. Em 2027, ``Usuario.papel`` continua como papel principal e é mantido em sincronia com estes vínculos."""

    class Papel(models.TextChoices):
        ORIENTADOR = "ORIENTADOR", "Orientador(a)"
        COORDENADOR = "COORDENADOR", "Coordenador(a) de curso"
        SUPERVISOR = "SUPERVISOR", "Supervisor(a)"
        ESTAGIARIO = "ESTAGIARIO", "Estagiário(a)"
        RESPONSAVEL = "RESPONSAVEL", "Responsável legal"
        CONTATO_CONCEDENTE = "CONTATO", "Contato de concedente"
        ADMIN_ESCOLA = "ADMIN", "Administrador(a) da escola"

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="vinculos_escola")
    escola = models.ForeignKey(Escola, on_delete=models.CASCADE, related_name="vinculos")
    papel = models.CharField(max_length=12, choices=Papel.choices)
    ativo = models.BooleanField(default=True)
    inicio = models.DateField(default=timezone.localdate)
    fim = models.DateField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["escola__nome", "papel"]
        verbose_name = "vínculo com escola"
        verbose_name_plural = "vínculos com escolas"
        constraints = [models.UniqueConstraint(fields=["usuario", "escola", "papel"], name="vinculo_escola_unico")]
        indexes = [models.Index(fields=["usuario", "ativo"])]

    def __str__(self):
        return f"{self.usuario} · {self.get_papel_display()} · {self.escola}"
