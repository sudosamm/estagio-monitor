import contextvars
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string

from escolas.escopo import EscopoEscolaManager, escola_corrente_id, escola_corrente_ou_nada

from .cifragem import CampoCifrado

# Guardados só durante uma requisição (o middleware CacheDaRequisicaoMiddleware abre e fecha): evita reler a
# configuração várias vezes na mesma página. Fora de uma requisição (comandos, testes sem cliente) não guarda nada.
CACHE_REQUISICAO = contextvars.ContextVar("cache_requisicao", default=None)

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
    "encerramento": "Encerrar o ano letivo e anonimizar dados antigos (LGPD)",
    "avaliacoes": "Editar as perguntas das avaliações (autoavaliação e avaliação do orientador)",
}
PERMISSOES_POR_PAPEL = {
    "ORIENTADOR": set(PERMISSOES),
    "COORDENADOR": {"painel", "estagiarios", "contas", "cadastros", "candidaturas", "frequencias"},
}


def _versao_atual():
    """Contas novas começam em dia com as novidades (não recebem o histórico inteiro de uma vez)."""
    from .novidades import ultima_versao

    return ultima_versao()


class Usuario(AbstractUser):
    class Papel(models.TextChoices):
        ORIENTADOR = "ORIENTADOR", "Orientador(a)"
        COORDENADOR = "COORDENADOR", "Coordenador(a) de curso"
        SUPERVISOR = "SUPERVISOR", "Supervisor(a)"
        ESTAGIARIO = "ESTAGIARIO", "Estagiário(a)"
        RESPONSAVEL = "RESPONSAVEL", "Responsável legal"

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
    data_nascimento = models.DateField(
        "Data de nascimento", null=True, blank=True,
        help_text="Para estagiários: com o nome completo, é o que a pessoa usa no primeiro acesso para criar a senha.",
    )
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
    resumo_semanal = models.BooleanField(
        "Receber o resumo semanal por e-mail", default=True,
        help_text="Para orientadores e coordenadores: toda segunda-feira, quem está sem registro, faltas, presenças a "
                  "validar, termos vencendo e visitas da semana.",
    )
    token_agenda = models.CharField(max_length=40, blank=True, editable=False,
                                    help_text="Chave do link da agenda para Google Agenda / celular.")
    cursos_coordenados = models.ManyToManyField(
        "Curso", blank=True, related_name="coordenadores", verbose_name="Cursos que coordena",
        help_text="Vazio = todos os cursos.",
    )
    deve_trocar_senha = models.BooleanField(default=True, help_text="Ainda não criou a própria senha (primeiro acesso)")
    email_confirmado_em = models.DateTimeField(null=True, blank=True, editable=False,
                                               help_text="Quando a pessoa confirmou o e-mail pelo link (vale para recuperar a senha)")
    confirmacao_enviada_em = models.DateTimeField(null=True, blank=True, editable=False,
                                                  help_text="Último e-mail de confirmação enviado (evita mandar repetido)")
    # código de uso único do primeiro acesso (guardado só o resumo HMAC; o código aparece uma vez para a gestão)
    codigo_acesso = models.CharField(max_length=64, blank=True, editable=False)
    codigo_acesso_validade = models.DateTimeField(null=True, blank=True, editable=False)
    # Termos de Uso e Aviso de Privacidade: versão que a pessoa leu e aceitou (ver core/termos.py)
    termos_versao = models.CharField(max_length=20, blank=True, editable=False)
    termos_aceitos_em = models.DateTimeField(null=True, blank=True, editable=False)
    # verificação em duas etapas (código de 6 dígitos de um app autenticador; ver core/dois_fatores.py)
    totp_segredo = CampoCifrado(max_length=255, blank=True, editable=False,
                                help_text="Cifrado no banco com CHAVE_DADOS (core/cifragem.py)")
    totp_ativo_em = models.DateTimeField(null=True, blank=True, editable=False)
    totp_ultimo_passo = models.BigIntegerField(default=0, editable=False)
    codigos_recuperacao = models.JSONField(default=list, blank=True, editable=False)
    concedentes_geridas = models.ManyToManyField(
        "LocalEstagio", blank=True, related_name="responsaveis", verbose_name="Responsável pelas concedentes",
        help_text="Pode cadastrar a equipe da concedente (supervisores e funcionários) e dar permissões temporárias "
                  "para confirmar presenças quando o supervisor não estiver.",
    )
    modo_administrador = models.BooleanField(
        "Modo administrador", default=True,
        help_text="Só para administradores. Desligado, a conta funciona como a de um orientador comum: vê só os próprios "
                  "estagiários e esconde as telas de administração.",
    )
    lembrete_expediente = models.BooleanField(
        "Lembrar no fim do expediente", default=True,
        help_text="Se você esquecer de marcar a presença ou a saída, o celular avisa uma hora depois do horário de saída.",
    )
    class Tema(models.TextChoices):
        AUTO = "AUTO", "Automático (igual ao celular)"
        CLARO = "CLARO", "Claro"
        ESCURO = "ESCURO", "Escuro"

    tema = models.CharField("Tema", max_length=6, choices=Tema.choices, default=Tema.AUTO)
    novidades_vistas = models.CharField(max_length=20, blank=True, default=_versao_atual, editable=False,
                                        help_text="Última versão do “O que há de novo” que a pessoa viu")
    novidades_popup = models.BooleanField("Mostrar “O que há de novo” a cada atualização", default=True)
    anonimizado_em = models.DateTimeField(null=True, blank=True, editable=False,
                                          help_text="Dados pessoais apagados (LGPD) nesta data")
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["nome_completo"]
        verbose_name = "usuário"

    def __str__(self):
        return self.nome_completo or self.username

    @classmethod
    def from_db(cls, db, field_names, values):
        obj = super().from_db(db, field_names, values)
        obj._email_original = obj.__dict__.get("email")
        obj._ativo_original = obj.__dict__.get("is_active")
        obj._papel_original = obj.__dict__.get("papel")
        obj._superuser_original = obj.__dict__.get("is_superuser")
        return obj

    def save(self, *args, **kwargs):
        # Nesta requisição a conta pode estar com o papel e o "administrador" da escola atual
        # (escolas.middleware.aplicar_escola) ou no modo orientador (ModoAdministradorMiddleware). O banco grava
        # sempre os valores originais da conta.
        papel_req, super_req = self.papel, self.is_superuser
        if hasattr(self, "_papel_bd"):
            self.papel, self.is_superuser = self._papel_bd, self._superuser_bd
        elif getattr(self, "_admin_real", False):
            self.is_superuser = True
        try:
            return self._salvar(*args, **kwargs)
        finally:
            self.papel, self.is_superuser = papel_req, super_req

    def _salvar(self, *args, **kwargs):
        # e-mail trocado (pela pessoa ou pela gestão) precisa ser confirmado de novo
        antes = getattr(self, "_email_original", None)
        campos = kwargs.get("update_fields")
        if (self.pk and antes is not None and (campos is None or "email" in campos)
                and (self.email or "").strip().lower() != (antes or "").strip().lower()):
            self.email_confirmado_em = None
            if campos is not None:
                kwargs["update_fields"] = set(campos) | {"email_confirmado_em"}
        if self.is_superuser:
            self.papel = self.Papel.ORIENTADOR
        if not self.nome_completo:
            self.nome_completo = f"{self.first_name} {self.last_name}".strip() or self.username
        criado = self._state.adding
        super().save(*args, **kwargs)
        if not kwargs.get("using") or kwargs.get("using") == "default":
            from escolas.vinculos import sincronizar

            sincronizar(self, criado, getattr(self, "_papel_original", None), getattr(self, "_superuser_original", False))
        self._papel_original, self._superuser_original = self.papel, self.is_superuser
        self._email_original = self.email
        if getattr(self, "_ativo_original", None) and not self.is_active and (campos is None or "is_active" in campos):
            from .sessoes import desconectar_todas

            desconectar_todas(self)  # conta desativada sai de todos os aparelhos (não volta sozinha se reativar)
        self._ativo_original = self.is_active

    @property
    def is_orientador(self):
        return self.papel == self.Papel.ORIENTADOR

    @property
    def administrador_plataforma(self):
        """Administrador técnico da plataforma (o ``is_superuser`` gravado), separado do administrador da escola."""
        return getattr(self, "_superuser_bd", self.is_superuser or getattr(self, "_admin_real", False))

    @property
    def e_administrador(self):
        """Administrador de verdade, mesmo usando a conta no modo orientador."""
        return self.is_superuser or getattr(self, "_admin_real", False)

    @property
    def no_modo_orientador(self):
        return getattr(self, "_admin_real", False)

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

    def ids_geridas(self):
        """Concedentes de que a pessoa é responsável (cadastra a equipe e as substituições)."""
        if not hasattr(self, "_ids_geridas"):
            self._ids_geridas = (set(self.concedentes_geridas.values_list("pk", flat=True))
                                 if self.pk and self.is_supervisor else set())
        return self._ids_geridas

    @property
    def gere_concedente(self):
        return bool(self.ids_geridas())

    @property
    def vinculado_a_concedente(self):
        """Supervisor que já faz parte de uma concedente ativa. A conta criada na candidatura só passa a ser
        vinculada quando a escola aprova o cadastro: antes disso a pessoa só vê o andamento da candidatura."""
        if not self.is_supervisor:
            return False
        if not hasattr(self, "_vinculado"):
            self._vinculado = (self.concedentes.filter(ativa=True).exists() or self.concedentes_geridas.exists()
                               or self.estagios_supervisionados.filter(ativo=True).exists())
        return self._vinculado

    @property
    def dois_fatores_ativo(self):
        return bool(self.totp_ativo_em and self.totp_segredo)

    @property
    def is_estagiario(self):
        return self.papel == self.Papel.ESTAGIARIO

    @property
    def is_responsavel(self):
        """Responsável legal de um estudante: só acompanha o estágio (área própria, só leitura)."""
        return self.papel == self.Papel.RESPONSAVEL

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
    escola = models.ForeignKey("escolas.Escola", on_delete=models.PROTECT, related_name="+",
                               default=escola_corrente_id, editable=False)
    _caminho_escola = "escola"
    objects = EscopoEscolaManager()

    nome = models.CharField(max_length=120)
    carga_horaria = models.PositiveIntegerField("Carga horária total (h)", default=300)
    horas_por_dia_padrao = models.DecimalField("Horas por dia (padrão)", max_digits=4, decimal_places=2, default=Decimal("4"))
    na_captacao = models.BooleanField("Aparece na captação de concedentes", default=True,
                                      help_text="As concedentes só escolhem vagas dos cursos marcados.")

    class Meta:
        ordering = ["nome"]
        constraints = [models.UniqueConstraint(fields=["escola", "nome"], name="curso_nome_unico_na_escola")]

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

    _caminho_escola = "curso__escola"
    objects = EscopoEscolaManager()

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

    escola = models.ForeignKey("escolas.Escola", on_delete=models.PROTECT, related_name="+",
                               default=escola_corrente_id, editable=False)
    _caminho_escola = "escola"
    objects = EscopoEscolaManager()

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
    escola = models.ForeignKey("escolas.Escola", on_delete=models.PROTECT, related_name="+",
                               default=escola_corrente_id, editable=False)
    _caminho_escola = "escola"
    objects = EscopoEscolaManager()

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
    lembrete_em = models.DateField(null=True, blank=True, editable=False,
                                   help_text="Último dia em que o estagiário recebeu o lembrete de fim de expediente")
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

    def save(self, *args, **kwargs):
        if self.curso_id and not self.escola_id:
            self.escola_id = Curso._base_manager.filter(pk=self.curso_id).values_list("escola_id", flat=True).first()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        for campo in ("curso", "local"):
            obj = getattr(self, campo) if getattr(self, f"{campo}_id") else None
            if obj is not None and self.escola_id and obj.escola_id != self.escola_id:
                raise ValidationError({campo: "É de outra escola."})
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
        from escolas.escopo import TODAS, escola_corrente

        atual = escola_corrente(obrigatoria=False)
        if atual is not None and atual is not TODAS and self.escola_id != atual.pk:
            return False  # nunca, por nenhum caminho, um estágio de outra escola
        if usuario.is_superuser or usuario.coordena(self.curso_id):
            return True
        return usuario.pk in {self.estagiario_id, self.orientador_id, self.supervisor_id}

    def participantes(self):
        return [u for u in [self.estagiario, self.orientador, self.supervisor] if u]


class TrocaSupervisor(models.Model):
    """Histórico de troca do supervisor de um estágio (só o orientador/coordenador troca)."""

    _caminho_escola = "estagio__escola"
    objects = EscopoEscolaManager()

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

    _caminho_escola = "estagio__escola"
    objects = EscopoEscolaManager()

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


def horas_dos_horarios(entrada, saida_int, volta_int, saida):
    """Horas entre entrada e saída, descontado o intervalo. None se faltar entrada/saída ou se não fechar."""
    if not (entrada and saida):
        return None
    m = lambda t: t.hour * 60 + t.minute  # noqa: E731
    minutos = m(saida) - m(entrada)
    if saida_int and volta_int:
        minutos -= m(volta_int) - m(saida_int)
    if minutos <= 0:
        return None
    return (Decimal(minutos) / 60).quantize(Decimal("0.01"))


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


PALAVRAS_MINUSCULAS_MUNICIPIO = {"de", "da", "do", "das", "dos", "e"}


def nome_municipio(nome):
    """Município para mostrar ao usuário: “GENERAL SAMPAIO - CE” → “General Sampaio”.

    Tira a UF do fim (como ``chave_municipio``) e, se veio todo em maiúsculas ou todo em minúsculas, põe só as
    iniciais em maiúscula (“de”, “da”, “do”… ficam minúsculas). Quem já escreveu misturando fica como escreveu."""
    import re

    texto = re.sub(r"\s*[-/(]\s*[A-Za-z]{2}\)?\s*$", "", " ".join((nome or "").split()))
    if not (texto.isupper() or texto.islower()):
        return texto
    partes = re.split(r"([\s'’-])", texto.lower())
    return "".join(p if (i and p in PALAVRAS_MINUSCULAS_MUNICIPIO) else p[:1].upper() + p[1:]
                   for i, p in enumerate(partes))


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

    escola = models.ForeignKey("escolas.Escola", on_delete=models.PROTECT, related_name="+",
                               default=escola_corrente_id, editable=False)
    _caminho_escola = "escola"
    objects = EscopoEscolaManager()

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

    _caminho_escola = "estagio__escola"
    objects = EscopoEscolaManager()

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
    supervisor_presente = models.BooleanField(
        "O supervisor estava no local", null=True, blank=True,
        help_text="Informado pelo estagiário ao marcar a entrada (ou pelo QR code do supervisor). Vazio = não informou.")
    geo_entrada = models.JSONField("Localização da entrada", null=True, blank=True)
    geo_saida = models.JSONField("Localização da saída", null=True, blank=True)
    justificativa = models.ForeignKey("Justificativa", null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name="registros", help_text="Atestado/comprovante que cobre este dia")
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
        if antes is not None or "situacao" in depois:
            self._avisar_responsaveis(antes or {}, depois)
        self._antes = depois

    def _avisar_responsaveis(self, antes, depois):
        """Falta registrada ou presença contestada pelo supervisor: o responsável legal fica sabendo."""
        falta = depois.get("situacao") == self.Situacao.FALTA and antes.get("situacao") != self.Situacao.FALTA
        contestada = (depois.get("situacao") == self.Situacao.PRESENTE
                      and depois.get("confirmacao") == self.Confirmacao.CONTESTADA
                      and antes.get("confirmacao") != self.Confirmacao.CONTESTADA)
        if not (falta or contestada):
            return
        from django.db import transaction

        def avisar():
            from .responsaveis import notificar_responsaveis

            aluno = self.estagio.estagiario
            o_que = "uma falta" if falta else "que a presença foi contestada pelo supervisor"
            notificar_responsaveis(aluno, f"Estágio de {aluno.primeiro_nome}: registramos {o_que} em {self.data:%d/%m}.",
                                   reverse("responsavel_estagio", args=[self.estagio_id]))

        transaction.on_commit(avisar)

    def delete(self, *args, **kwargs):
        HistoricoRegistro.objects.create(
            estagio_id=self.estagio_id, data=self.data, usuario=getattr(self, "_autor", None),
            acao=getattr(self, "_acao", "") or "EXCLUIU", ip=getattr(self, "_ip", None),
            mudancas=[["Registro do dia", f"{self.get_situacao_display()} {self.horario_display}".strip(), "excluído"]]
            + ([["Motivo", "—", self._motivo_exclusao[:120]]] if getattr(self, "_motivo_exclusao", "") else []))
        return super().delete(*args, **kwargs)


def _pasta_da_escola(escola_id):
    """Arquivos novos ficam separados por escola (escolas/<id>/…). Os antigos continuam onde estão; o download
    sempre confere a escola pela linha do banco, não pelo caminho."""
    return f"escolas/{escola_id}" if escola_id else "plataforma"


def _ext(filename, padrao="bin"):
    return filename.rsplit(".", 1)[-1].lower()[:8] if "." in filename else padrao


def caminho_atestado(instance, filename):
    escola = Estagio._base_manager.filter(pk=instance.estagio_id).values_list("escola_id", flat=True).first()
    return f"{_pasta_da_escola(escola)}/atestados/{timezone.localdate():%Y/%m}/{get_random_string(20)}.{_ext(filename)}"


class Justificativa(models.Model):
    """Atestado ou comprovante enviado pelo estagiário para justificar um ou mais dias de falta.

    Os dias de estágio do período viram “ausência” aguardando análise. Aceito: ausência justificada (não conta como
    falta). Recusado: os dias passados viram falta. Atestado é dado de saúde (LGPD): só quem decide vê o arquivo.
    """

    _caminho_escola = "estagio__escola"
    objects = EscopoEscolaManager()

    class Tipo(models.TextChoices):
        ATESTADO = "ATESTADO", "Atestado médico"
        COMPARECIMENTO = "COMPARECIMENTO", "Declaração de comparecimento (consulta, exame)"
        OFICIAL = "OFICIAL", "Convocação ou documento oficial (justiça, alistamento, prova)"
        OUTRO = "OUTRO", "Outro comprovante"

    class Status(models.TextChoices):
        PENDENTE = "PENDENTE", "Aguardando análise"
        ACEITA = "ACEITA", "Aceito"
        RECUSADA = "RECUSADA", "Recusado"

    estagio = models.ForeignKey(Estagio, on_delete=models.CASCADE, related_name="justificativas")
    tipo = models.CharField("Tipo de documento", max_length=16, choices=Tipo.choices, default=Tipo.ATESTADO)
    data_inicio = models.DateField("Primeiro dia")
    data_fim = models.DateField("Último dia")
    motivo = models.TextField("Observação", blank=True)
    arquivo = models.FileField(upload_to=caminho_atestado)
    nome_original = models.CharField(max_length=255, blank=True)
    dias = models.JSONField(default=list, help_text="Dias de estágio cobertos (AAAA-MM-DD)")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDENTE)
    enviado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)
    decidido_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="+")
    decidido_em = models.DateTimeField(null=True, blank=True)
    parecer = models.TextField("Parecer", blank=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "atestado / justificativa"
        verbose_name_plural = "atestados / justificativas"

    def __str__(self):
        return f"{self.get_tipo_display()} de {self.estagio.estagiario} ({self.periodo_display})"

    def get_absolute_url(self):
        return reverse("atestado_detalhe", args=[self.pk])

    @property
    def periodo_display(self):
        if self.data_inicio == self.data_fim:
            return f"{self.data_inicio:%d/%m/%Y}"
        return f"{self.data_inicio:%d/%m} a {self.data_fim:%d/%m/%Y}"

    @property
    def datas(self):
        return [date.fromisoformat(d) for d in self.dias]

    @property
    def eh_imagem(self):
        return self.arquivo.name.lower().endswith((".jpg", ".jpeg", ".png"))

    @property
    def pendente(self):
        return self.status == self.Status.PENDENTE

    def pode_decidir(self, usuario):
        """Escola (orientador, coordenação do curso, administrador) e, se a configuração permitir, o supervisor."""
        e = self.estagio
        if usuario.is_superuser or e.orientador_id == usuario.pk or usuario.coordena(e.curso_id):
            return True
        return e.supervisor_id == usuario.pk and Configuracao.atual().atestados_supervisor

    def pode_ver(self, usuario):
        return usuario.pk == self.estagio.estagiario_id or self.pode_decidir(usuario)


class HistoricoRegistro(models.Model):
    """Quem mexeu no registro de um dia, quando e o que mudou (inclusive horários: de → para).

    Guardado por estágio + dia, para sobreviver mesmo se o registro for excluído (ex.: ausência cancelada).
    """

    _caminho_escola = "estagio__escola"
    objects = EscopoEscolaManager()

    class Acao(models.TextChoices):
        ENTRADA = "ENTRADA", "marcou a entrada pelo botão"
        PONTO = "PONTO", "marcou pelo botão"
        DIGITOU = "DIGITOU", "digitou os horários"
        AUSENCIA = "AUSENCIA", "informou ausência"
        LANCAMENTO = "LANCAMENTO", "lançou/ajustou o registro"
        VALIDACAO = "VALIDACAO", "validou"
        CANCELOU = "CANCELOU", "cancelou a ausência"
        REVOGOU = "REVOGOU", "revogou a presença"
        QRCODE = "QRCODE", "marcou pelo QR code do supervisor"
        LINK = "LINK", "confirmou pelo link do e-mail/WhatsApp"
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

    _caminho_escola = "estagio__escola"
    objects = EscopoEscolaManager()

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
    escola = models.ForeignKey("escolas.Escola", on_delete=models.PROTECT, related_name="+",
                               default=escola_corrente_id, editable=False)
    _caminho_escola = "escola"
    objects = EscopoEscolaManager()

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
    duracao = models.PositiveSmallIntegerField("Duração (min)", null=True, blank=True,
                                               help_text="Vazio = duração padrão do tipo (visita: 90 min).")
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

    DURACAO_PADRAO = {"VISITA": 90, "CONVERSA": 30, "REUNIAO": 60}

    @property
    def duracao_min(self):
        return self.duracao or self.DURACAO_PADRAO.get(self.tipo, 60)

    @property
    def fim(self):
        return self.data_hora + timedelta(minutes=self.duracao_min) if self.data_hora else None

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
    """Nome aleatório (o nome original fica em ``Documento.nome_original``): o disco e os backups não guardam nomes
    de pessoas no nome do arquivo."""
    hoje = timezone.localdate()
    return f"{_pasta_da_escola(instance.escola_id)}/documentos/{hoje:%Y/%m}/{get_random_string(20)}.{_ext(filename)}"


def caminho_modelo_documento(instance, filename):
    return f"{_pasta_da_escola(instance.escola_id)}/modelos/{get_random_string(12)}.{_ext(filename)}"


def caminho_config(instance, filename):
    return f"{_pasta_da_escola(instance.escola_id)}/config/{get_random_string(12)}.{_ext(filename, 'png')}"


class TipoDocumento(models.Model):
    """Documento que cada estagiário precisa ter na pasta (TCE, plano de atividades, relatório final…)."""

    escola = models.ForeignKey("escolas.Escola", on_delete=models.PROTECT, related_name="+",
                               default=escola_corrente_id, editable=False)
    _caminho_escola = "escola"
    objects = EscopoEscolaManager()

    class Momento(models.TextChoices):
        INICIO = "INICIO", "No início do estágio"
        FIM = "FIM", "No fim do estágio"
        LIVRE = "LIVRE", "Sem prazo"

    class Quem(models.TextChoices):
        ESTAGIARIO = "ESTAGIARIO", "Estagiário"
        SUPERVISOR = "SUPERVISOR", "Supervisor (concedente)"
        ESCOLA = "ESCOLA", "Escola (orientador)"

    nome = models.CharField(max_length=120)
    descricao = models.TextField("Orientações", blank=True, help_text="Aparece para quem vai enviar. Ex.: assinado por "
                                                                       "todos, em PDF ou foto legível.")
    momento = models.CharField("Quando", max_length=6, choices=Momento.choices, default=Momento.INICIO)
    prazo_dias = models.PositiveSmallIntegerField(
        "Prazo (dias)", default=15,
        help_text="No início: dias depois do início do estágio. No fim: dias depois do término previsto no termo.")
    quem_envia = models.CharField("Quem envia", max_length=10, choices=Quem.choices, default=Quem.ESTAGIARIO)
    obrigatorio = models.BooleanField("Obrigatório", default=True)
    curso = models.ForeignKey(Curso, null=True, blank=True, on_delete=models.CASCADE, help_text="Vazio = todos os cursos")
    modelo = models.FileField("Modelo para baixar (opcional)", upload_to=caminho_modelo_documento, blank=True,
                              help_text="Ex.: o formulário do plano de atividades em branco.")
    ativo = models.BooleanField("Em uso", default=True)
    ordem = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["ordem", "nome"]
        verbose_name = "tipo de documento"
        verbose_name_plural = "tipos de documento"

    def __str__(self):
        return self.nome

    def vale_para(self, estagio):
        return self.ativo and (self.curso_id is None or self.curso_id == estagio.curso_id)

    def prazo_para(self, estagio):
        from datetime import timedelta

        if self.momento == self.Momento.INICIO:
            return max(estagio.data_inicio, estagio.acompanhamento_desde or estagio.data_inicio) + timedelta(
                days=self.prazo_dias)
        if self.momento == self.Momento.FIM and estagio.data_fim:
            return estagio.data_fim + timedelta(days=self.prazo_dias)
        return None


class Documento(models.Model):
    escola = models.ForeignKey("escolas.Escola", on_delete=models.PROTECT, related_name="+",
                               default=escola_corrente_id, editable=False)
    _caminho_escola = "escola"
    objects = EscopoEscolaManager()

    class Situacao(models.TextChoices):
        ENVIADO = "ENVIADO", "Aguardando conferência"
        APROVADO = "APROVADO", "Conferido"
        RECUSADO = "RECUSADO", "Recusado"

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
    # pasta do estágio: entrega de um documento exigido, conferida pela escola
    tipo = models.ForeignKey(TipoDocumento, null=True, blank=True, on_delete=models.SET_NULL, related_name="entregas")
    situacao = models.CharField(max_length=10, choices=Situacao.choices, blank=True)
    analisado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name="+")
    analisado_em = models.DateTimeField(null=True, blank=True)
    parecer = models.TextField(blank=True)

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

    _caminho_escola = "estagio__escola"
    objects = EscopoEscolaManager()

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
    escola = models.ForeignKey("escolas.Escola", null=True, blank=True, on_delete=models.CASCADE,
                               related_name="+", default=escola_corrente_ou_nada, editable=False,
                               help_text="Vazio = da plataforma (sem escola)")

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notificacoes")
    texto = models.CharField(max_length=255)
    link = models.CharField(max_length=255, blank=True)
    lida = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]


class PerguntaAvaliacao(models.Model):
    """Pergunta de uma avaliação que o estagiário preenche (na mesma ordem e com o mesmo texto do SICE)."""

    escola = models.ForeignKey("escolas.Escola", on_delete=models.PROTECT, related_name="+",
                               default=escola_corrente_id, editable=False)
    _caminho_escola = "escola"
    objects = EscopoEscolaManager()

    class Tipo(models.TextChoices):
        AUTO = "AUTO", "Autoavaliação"
        ORIENTADOR = "ORIENTADOR", "Avaliação do orientador"
        PRATICA = "PRATICA", "Acompanhamento de visita: avaliação prática"
        ATITUDINAL = "ATITUDINAL", "Acompanhamento de visita: avaliação atitudinal"

    class Resposta(models.TextChoices):
        NOTA = "NOTA", "Escala de 1 a 5"
        ESCOLHA = "ESCOLHA", "Escolher uma opção"
        TEXTO = "TEXTO", "Texto livre"

    avaliacao = models.CharField("Avaliação", max_length=10, choices=Tipo.choices)
    enunciado = models.CharField("Pergunta", max_length=300, help_text="Copie o texto exatamente como está no SICE.")
    ajuda = models.CharField("Dica para o estagiário", max_length=300, blank=True)
    resposta = models.CharField("Tipo de resposta", max_length=8, choices=Resposta.choices, default=Resposta.NOTA)
    curso = models.ForeignKey(Curso, null=True, blank=True, on_delete=models.CASCADE,
                              help_text="Só para a avaliação prática (as atividades mudam por curso). Vazio = todos.")
    opcoes = models.TextField("Opções", blank=True, help_text="Uma por linha (só para “Escolher uma opção”).")
    limite = models.PositiveIntegerField("Limite de caracteres", null=True, blank=True,
                                         help_text="Para texto livre: o mesmo limite do campo no SICE, se houver.")
    obrigatoria = models.BooleanField("Obrigatória", default=True)
    ordem = models.PositiveSmallIntegerField(default=0)
    ativa = models.BooleanField("Em uso", default=True)

    class Meta:
        ordering = ["avaliacao", "ordem", "pk"]
        verbose_name = "pergunta de avaliação"
        verbose_name_plural = "perguntas de avaliação"

    def __str__(self):
        return self.enunciado

    @property
    def lista_opcoes(self):
        return [o.strip() for o in self.opcoes.splitlines() if o.strip()]


def primeiro_dia_do_mes():
    hoje = timezone.localdate()
    return date(hoje.year, hoje.month, 1)


class Avaliacao(models.Model):
    """Respostas do estagiário a uma avaliação de um mês, para copiar no SICE (lá elas também são mensais)."""

    _caminho_escola = "estagio__escola"
    objects = EscopoEscolaManager()

    estagio = models.ForeignKey(Estagio, on_delete=models.CASCADE, related_name="avaliacoes")
    tipo = models.CharField(max_length=10, choices=PerguntaAvaliacao.Tipo.choices)
    mes = models.DateField("Mês de referência", default=primeiro_dia_do_mes)
    respostas = models.JSONField(default=dict, help_text="{id da pergunta: resposta}")
    concluida_em = models.DateTimeField(null=True, blank=True)
    copiada_sice_em = models.DateTimeField("Copiada para o SICE em", null=True, blank=True)
    atualizada_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-mes"]
        constraints = [models.UniqueConstraint(fields=["estagio", "tipo", "mes"], name="avaliacao_unica_por_mes")]

    def __str__(self):
        return f"{self.get_tipo_display()} de {self.estagio.estagiario} ({self.mes:%m/%Y})"


def caminho_sugestao(instance, filename):
    escola = Sugestao._base_manager.filter(pk=instance.sugestao_id).values_list("escola_id", flat=True).first()
    return f"{_pasta_da_escola(escola)}/sugestoes/{timezone.localdate():%Y/%m}/{get_random_string(16)}.{_ext(filename)}"


class Sugestao(models.Model):
    """Sugestão, erro ou dúvida enviada pela página “Sugestões e erros” (vai por e-mail e fica guardada aqui)."""

    escola = models.ForeignKey("escolas.Escola", null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="+", default=escola_corrente_ou_nada, editable=False,
                               help_text="Vazio = da plataforma (sem escola)")
    _caminho_escola = "escola"
    objects = EscopoEscolaManager()

    class Tipo(models.TextChoices):
        ERRO = "ERRO", "Erro ou problema"
        SUGESTAO = "SUGESTAO", "Sugestão de melhoria"
        DUVIDA = "DUVIDA", "Dúvida"
        ELOGIO = "ELOGIO", "Elogio"
        OUTRO = "OUTRO", "Outro assunto"

    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.SUGESTAO)
    nome = models.CharField(max_length=150)
    email = models.EmailField("E-mail para resposta", blank=True)
    mensagem = models.TextField()
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="sugestoes")
    pagina = models.CharField("Página onde estava", max_length=300, blank=True)
    nota = models.PositiveSmallIntegerField("Nota (1 a 5)", null=True, blank=True,
                                            help_text="Do botão “Sua opinião” (período de testes)")
    navegador = models.CharField(max_length=300, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    enviada_em = models.DateTimeField("E-mail enviado em", null=True, blank=True)
    resolvida = models.BooleanField(default=False)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "sugestão ou erro"
        verbose_name_plural = "sugestões e erros"

    def __str__(self):
        return f"{self.get_tipo_display()} de {self.nome} ({self.criado_em:%d/%m/%Y})"


class AnexoSugestao(models.Model):
    sugestao = models.ForeignKey(Sugestao, on_delete=models.CASCADE, related_name="anexos")
    arquivo = models.FileField(upload_to=caminho_sugestao)
    nome_original = models.CharField(max_length=255)
    tamanho = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.nome_original


class AcompanhamentoVisita(models.Model):
    """“Acompanhamento de Visita” do SICE: o orientador avalia o estagiário na visita (prática e atitudinal)."""

    _caminho_escola = "estagio__escola"
    objects = EscopoEscolaManager()

    estagio = models.ForeignKey(Estagio, on_delete=models.CASCADE, related_name="acompanhamentos")
    agendamento = models.ForeignKey(Agendamento, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="acompanhamentos")
    data = models.DateField("Data da visita")
    respostas = models.JSONField(default=dict)
    # no SICE cada parte (prática e atitudinal) tem as suas Observações (obrigatória) e Intervenções, 300 caracteres
    observacoes = models.TextField("Observações da avaliação prática", blank=True)
    intervencoes = models.TextField("Intervenções da avaliação prática", blank=True)
    observacoes_atitudinal = models.TextField("Observações da avaliação atitudinal", blank=True)
    intervencoes_atitudinal = models.TextField("Intervenções da avaliação atitudinal", blank=True)
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    lancado_sice_em = models.DateTimeField("Lançado no SICE em", null=True, blank=True)

    class Meta:
        ordering = ["-data", "-criado_em"]
        verbose_name = "acompanhamento de visita"
        verbose_name_plural = "acompanhamentos de visita"

    def __str__(self):
        return f"Acompanhamento de {self.estagio.estagiario} em {self.data:%d/%m/%Y}"

    def get_absolute_url(self):
        return reverse("acompanhamento_ver", args=[self.pk])


class Encerramento(models.Model):
    """Registro de um encerramento de ano letivo, com o necessário para desfazê-lo."""

    escola = models.ForeignKey("escolas.Escola", on_delete=models.PROTECT, related_name="+",
                               default=escola_corrente_id, editable=False)
    _caminho_escola = "escola"
    objects = EscopoEscolaManager()

    ano = models.PositiveIntegerField("Ano do estágio")
    feito_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    feito_em = models.DateTimeField(auto_now_add=True)
    resumo = models.JSONField(default=dict, help_text="O que foi feito: ids de estágios, contas e turmas alterados")
    desfeito_em = models.DateTimeField(null=True, blank=True)
    desfeito_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="+")

    class Meta:
        ordering = ["-feito_em"]

    def __str__(self):
        return f"Encerramento de {self.ano}"


class Anonimizacao(models.Model):
    """Registro (sem dados pessoais) de cada anonimização feita."""

    escola = models.ForeignKey("escolas.Escola", on_delete=models.PROTECT, related_name="+",
                               default=escola_corrente_id, editable=False)
    _caminho_escola = "escola"
    objects = EscopoEscolaManager()

    feita_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    feita_em = models.DateTimeField(auto_now_add=True)
    anos = models.CharField(max_length=60, help_text="Anos de estágio anonimizados")
    pessoas = models.PositiveIntegerField(default=0)
    arquivos = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-feita_em"]


class Feedback(models.Model):
    """Feedback mensal do supervisor sobre o estagiário: notas por critério e comentários."""

    _caminho_escola = "estagio__escola"
    objects = EscopoEscolaManager()

    NOTAS = [(5, "Excelente"), (4, "Muito bom"), (3, "Bom"), (2, "Regular"), (1, "Insuficiente")]
    CRITERIOS = [
        ("assiduidade", "Assiduidade e pontualidade"),
        ("responsabilidade", "Responsabilidade e compromisso"),
        ("iniciativa", "Iniciativa e proatividade"),
        ("relacionamento", "Relacionamento com a equipe"),
        ("qualidade", "Qualidade do trabalho"),
        ("aprendizado", "Aprendizado e evolução"),
    ]

    estagio = models.ForeignKey(Estagio, on_delete=models.CASCADE, related_name="feedbacks")
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    mes = models.DateField(help_text="Primeiro dia do mês a que se refere")
    assiduidade = models.PositiveSmallIntegerField("Assiduidade e pontualidade", choices=NOTAS, null=True, blank=True)
    responsabilidade = models.PositiveSmallIntegerField("Responsabilidade e compromisso", choices=NOTAS, null=True, blank=True)
    iniciativa = models.PositiveSmallIntegerField("Iniciativa e proatividade", choices=NOTAS, null=True, blank=True)
    relacionamento = models.PositiveSmallIntegerField("Relacionamento com a equipe", choices=NOTAS, null=True, blank=True)
    qualidade = models.PositiveSmallIntegerField("Qualidade do trabalho", choices=NOTAS, null=True, blank=True)
    aprendizado = models.PositiveSmallIntegerField("Aprendizado e evolução", choices=NOTAS, null=True, blank=True)
    pontos_fortes = models.TextField("Pontos fortes", blank=True)
    melhorar = models.TextField("O que pode melhorar", blank=True)
    reservado = models.TextField("Comentário só para a escola", blank=True,
                                 help_text="O estagiário não vê. Use para algo que a escola precisa saber.")
    visivel_estagiario = models.BooleanField("O estagiário pode ver este feedback", default=True,
                                             help_text="Notas, pontos fortes e o que melhorar.")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-mes"]
        constraints = [models.UniqueConstraint(fields=["estagio", "mes"], name="feedback_unico_por_mes")]

    def __str__(self):
        return f"Feedback de {self.estagio.estagiario} em {self.mes:%m/%Y}"

    @property
    def notas(self):
        """[(rótulo, nota, texto da nota)] na ordem dos critérios."""
        textos = dict(self.NOTAS)
        return [(rotulo, getattr(self, campo), textos.get(getattr(self, campo), "não observado"))
                for campo, rotulo in self.CRITERIOS]

    @property
    def media(self):
        valores = [getattr(self, c) for c, _ in self.CRITERIOS if getattr(self, c)]
        return round(sum(valores) / len(valores), 1) if valores else None


class InscricaoPush(models.Model):
    """Um celular/navegador que aceitou receber notificações (Web Push). Uma pessoa pode ter vários."""

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="inscricoes_push")
    endpoint = models.CharField(max_length=600, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    navegador = models.CharField(max_length=200, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    ultimo_envio = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "celular com notificações"
        verbose_name_plural = "celulares com notificações"

    def __str__(self):
        return f"{self.usuario} · {self.navegador[:40]}"

    @property
    def dados(self):
        return {"endpoint": self.endpoint, "keys": {"p256dh": self.p256dh, "auth": self.auth}}


class Comunicado(models.Model):
    """Aviso que o orientador manda para uma turma, um curso, uma concedente ou todos os seus estagiários."""

    escola = models.ForeignKey("escolas.Escola", on_delete=models.PROTECT, related_name="+",
                               default=escola_corrente_id, editable=False)
    _caminho_escola = "escola"
    objects = EscopoEscolaManager()

    autor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="comunicados")
    titulo = models.CharField("Título", max_length=120)
    texto = models.TextField("Mensagem")
    para = models.CharField(max_length=200, help_text="Descrição dos destinatários")
    destinatarios = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="comunicados_recebidos")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]

    def __str__(self):
        return self.titulo

    def get_absolute_url(self):
        return reverse("comunicado", args=[self.pk])


class Configuracao(models.Model):
    """Configurações da escola (uma por escola), editadas pelo administrador da escola."""

    escola = models.OneToOneField("escolas.Escola", on_delete=models.CASCADE, related_name="configuracao")

    nome_escola = models.CharField("Escola", max_length=160, blank=True, help_text="Ex.: EEEP Deputado Fulano de Tal")
    municipio_escola = models.CharField("Município da escola", max_length=80, blank=True)
    cabecalho_folha = models.TextField(
        "Cabeçalho da folha de frequência", blank=True,
        default="Coordenadoria de Educação Profissional\nCélula de Estágio - CEPAE",
        help_text="Uma linha por linha do cabeçalho, acima do título “FREQUÊNCIA DE ESTÁGIO”.",
    )
    logo_folha = models.ImageField("Brasão / logotipo da folha", upload_to=caminho_config, blank=True,
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
    resumo_semanal = models.BooleanField(
        "Enviar o resumo semanal aos orientadores", default=True,
        help_text="Toda segunda-feira, a partir das 6h, cada orientador e coordenador recebe por e-mail os pontos de "
                  "atenção dos seus estagiários. Quem não quiser pode desligar em Meus dados.",
    )
    resumo_enviado_em = models.DateTimeField(null=True, blank=True, editable=False)
    avaliacoes_abertas = models.BooleanField(
        "Liberar as avaliações para os estagiários", default=False,
        help_text="Autoavaliação e avaliação do orientador, com o texto pronto para copiar no SICE.",
    )
    avaliacoes_prazo = models.DateField(
        "Avaliações a partir de", null=True, blank=True,
        help_text="Primeiro mês cobrado. Vazio = desde o início de cada estágio (como no SICE).")
    lembrete_avaliacoes_em = models.DateTimeField(null=True, blank=True, editable=False)
    sice_url = models.URLField("Endereço do SICE para o estagiário", blank=True,
                               help_text="Aparece como botão “Abrir o SICE” na tela de copiar as respostas.")
    periodo_testes = models.BooleanField(
        "Sistema em período de testes", default=True,
        help_text="Mostra a estagiários e supervisores o botão “Sua opinião” em todas as páginas, para avaliarem o "
                  "sistema com uma nota e um comentário. As respostas ficam em Comunicação → Opiniões sobre o sistema.",
    )
    email_sugestoes = models.EmailField(
        "E-mail que recebe as sugestões e os erros", blank=True,
        help_text="Tudo o que for enviado em “Sugestões e erros” chega aqui, com os anexos. Vazio = variável "
                  "SUGESTOES_EMAIL do servidor ou, se não houver, o e-mail dos administradores.",
    )
    tema_escuro = models.BooleanField(
        "Permitir o tema escuro", default=True,
        help_text="Cada pessoa escolhe no menu dela: automático (segue o celular), claro ou escuro. Desligado: o "
                  "sistema fica sempre claro, como os portais do governo.",
    )
    retencao_anos = models.PositiveSmallIntegerField(
        "Guardar dados pessoais por (anos)", default=5,
        help_text="Depois desse prazo, contado do fim do ano do estágio, os dados de estagiários encerrados podem ser "
                  "anonimizados em Encerramento do ano. Os números (horas, frequência) continuam nos indicadores.",
    )
    feedback_mensal = models.BooleanField(
        "Pedir feedback mensal aos supervisores", default=True,
        help_text="A partir do dia 20, quem ainda não deu o feedback do mês sobre seus estagiários recebe um lembrete.",
    )
    lembrete_feedback_em = models.DateTimeField(null=True, blank=True, editable=False)
    lembrete_expediente = models.BooleanField(
        "Lembrar os estagiários no fim do expediente", default=True,
        help_text="Quem não marcou a presença (ou a saída) recebe um aviso no celular e no sino algum tempo depois do "
                  "horário de saída. Cada estagiário pode desligar em Meus dados.",
    )
    lembrete_minutos = models.PositiveSmallIntegerField(
        "Minutos depois da saída para lembrar", default=60,
        help_text="Ex.: 60 = uma hora depois do horário de saída da escala.",
    )
    confirmacao_por_email = models.BooleanField(
        "Mandar aos supervisores o link “Confirmar todas”", default=True,
        help_text="Uma vez por semana, cada supervisor com presenças esperando recebe por e-mail a lista e um botão "
                  "para confirmar todas de uma vez, sem precisar entrar no sistema. O link vale 7 dias e uma vez só.",
    )
    dia_confirmacao = models.PositiveSmallIntegerField(
        "Dia do e-mail de confirmação", choices=DIAS_SEMANA, default=4,
        help_text="Sai a partir das 14h desse dia.",
    )
    confirmacao_enviada_em = models.DateTimeField(null=True, blank=True, editable=False)
    resumo_mensal_supervisor = models.BooleanField(
        "Mandar o resumo do mês aos supervisores", default=True,
        help_text="No dia 1º de cada mês, cada supervisor recebe por e-mail as presenças, faltas e horas do mês "
                  "anterior de cada estagiário.",
    )
    resumo_mensal_enviado_em = models.DateTimeField(null=True, blank=True, editable=False)
    exigir_dois_fatores = models.BooleanField(
        "Exigir verificação em duas etapas da gestão", default=False,
        help_text="Orientadores, coordenadores, administradores e responsáveis por concedentes passam a precisar de um "
                  "código do celular (app autenticador) para entrar. Quem ainda não configurou é levado à tela de "
                  "configuração no próximo acesso.",
    )
    contato_privacidade = models.CharField(
        "Contato para assuntos de dados pessoais", max_length=150, blank=True,
        help_text="E-mail ou telefone do encarregado/responsável pelos dados na escola. Aparece no Aviso de "
                  "Privacidade. Vazio = e-mail que recebe as sugestões.",
    )
    atestados_supervisor = models.BooleanField(
        "O supervisor da concedente também analisa os atestados", default=True,
        help_text="Desligado: só a escola (orientador, coordenação) vê o arquivo e decide; o supervisor vê apenas que o "
                  "dia foi justificado. Atestados são dados de saúde: na dúvida, deixe só com a escola.",
    )
    estagiarios_emitem_folha = models.BooleanField(
        "Estagiários emitem a própria folha de frequência", default=True,
        help_text="Desligado: o estagiário só baixa a folha que o orientador enviar para o mês.",
    )
    mostrar_codigo_folha = models.BooleanField(
        "Imprimir a data de emissão e o código no rodapé da folha", default=True,
        help_text="Linha “Emitida em … · cód. XXXX” no canto de baixo. Desligada, a folha sai sem nada fora do modelo "
                  "oficial. O sistema continua registrando quem abriu e imprimiu cada folha.",
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
        return f"Configurações de {self.escola}" if self.escola_id else "Configurações"

    def save(self, *args, **kwargs):
        if not self.escola_id:
            from escolas.escopo import escola_corrente

            self.escola = escola_corrente()
        super().save(*args, **kwargs)
        # nome e município continuam editáveis aqui (Configurações); a escola acompanha
        from escolas.escopo import limpar_cache_escola_unica
        from escolas.models import Escola

        mudou = Escola.objects.filter(pk=self.escola_id).exclude(
            nome=self.nome_escola or models.F("nome"), municipio=self.municipio_escola).update(
            nome=models.functions.Coalesce(models.Value(self.nome_escola or None), models.F("nome")),
            municipio=self.municipio_escola)
        if mudou:
            limpar_cache_escola_unica()
        cache = CACHE_REQUISICAO.get()
        if cache is not None:
            cache[f"configuracao:{self.escola_id}"] = self

    @classmethod
    def atual(cls, escola=None):
        """Configuração da escola em uso (da requisição, de ``escola_ativa`` ou a única do banco).

        Sem escola definida num banco com várias escolas (ex.: tela de entrar antes do login), devolve uma
        configuração padrão **não gravada**, só para leitura."""
        from escolas.escopo import TODAS, escola_corrente

        escola = escola or escola_corrente(obrigatoria=False)
        if escola is None or escola is TODAS:
            return cls()
        cache = CACHE_REQUISICAO.get()
        chave = f"configuracao:{escola.pk}"
        if cache is not None and chave in cache:
            return cache[chave]
        obj = cls.objects.filter(escola=escola).select_related("escola", "escola__rede").first()
        if obj is None:
            obj, _ = cls.objects.get_or_create(escola=escola)
        if cache is not None:
            cache[chave] = obj
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

    _caminho_escola = "estagio__escola"
    objects = EscopoEscolaManager()

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

    escola = models.ForeignKey("escolas.Escola", on_delete=models.PROTECT, related_name="+",
                               default=escola_corrente_id, editable=False)
    _caminho_escola = "escola"
    objects = EscopoEscolaManager()

    class Status(models.TextChoices):
        PENDENTE = "PENDENTE", "Aguardando análise"
        APROVADA = "APROVADA", "Aprovada"
        RECUSADA = "RECUSADA", "Recusada"

    class PreenchidoPor(models.TextChoices):
        REPRESENTANTE = "REPRESENTANTE", "O(a) representante legal da concedente"
        AUTORIZADO = "AUTORIZADO", "Pessoa autorizada pelo(a) representante legal"
        ESCOLA = "ESCOLA", "A escola (orientador ou coordenador), a pedido da concedente"

    TURNOS = [("MANHA", "Manhã"), ("TARDE", "Tarde"), ("NOITE", "Noite")]

    ano = models.PositiveIntegerField("Ano letivo")
    protocolo = models.CharField(max_length=6, unique=True, default=gerar_protocolo)
    # quem preencheu
    contato_nome = models.CharField("Nome", max_length=150)
    contato_cargo = models.CharField("Cargo", max_length=80, blank=True)
    contato_email = models.EmailField("E-mail", blank=True)
    contato_telefone = models.CharField("Telefone", max_length=30)
    contato_whatsapp = models.BooleanField("Este telefone tem WhatsApp", default=True)
    preenchido_por = models.CharField("Quem está preenchendo", max_length=13, choices=PreenchidoPor.choices, blank=True)
    conta = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name="candidaturas_feitas",
                              help_text="Conta de quem preencheu: acompanha a análise e, aprovada, vira responsável")
    cadastrada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                       related_name="+", help_text="Orientador/coordenador que preencheu pela concedente")
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
    alterada_em = models.DateTimeField(null=True, blank=True, help_text="Última alteração antes da análise")
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

    @property
    def pendente(self):
        return self.status == self.Status.PENDENTE

    def pode_alterar(self, usuario):
        """Os dados e as vagas mudam só enquanto a escola não decidiu: depois de aprovada, as vagas ficam como
        foram aceitas."""
        return self.pendente and usuario.is_authenticated and (usuario.pk == self.conta_id or self.pode_ver(usuario))


class VagaCandidatura(models.Model):
    _caminho_escola = "candidatura__escola"
    objects = EscopoEscolaManager()

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

    escola = models.ForeignKey("escolas.Escola", on_delete=models.PROTECT, related_name="+",
                               default=escola_corrente_id, editable=False)
    _caminho_escola = "escola"
    objects = EscopoEscolaManager()

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
    return f"{_pasta_da_escola(instance.escola_id)}/folhas/{instance.mes:%Y-%m}/{get_random_string(16)}.{_ext(filename, 'pdf')}"


class FolhaEnviada(models.Model):
    """Folha de frequência de um mês que o orientador envia para os estagiários baixarem e imprimirem."""

    escola = models.ForeignKey("escolas.Escola", on_delete=models.PROTECT, related_name="+",
                               default=escola_corrente_id, editable=False)
    _caminho_escola = "escola"
    objects = EscopoEscolaManager()

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


class TentativaLogin(models.Model):
    """Senha errada no login (para limitar tentativas). Registros com mais de um dia são apagados sozinhos."""

    username = models.CharField(max_length=150, db_index=True)
    ip = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    criado_em = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "tentativa de login com erro"
        verbose_name_plural = "tentativas de login com erro"


class ModeloEmail(models.Model):
    """Texto de um tipo de e-mail automático, editado pelo administrador. Sem registro, vale o texto padrão
    (core/emails.py). Variáveis entre chaves, ex.: {nome}, {link}."""

    escola = models.ForeignKey("escolas.Escola", null=True, blank=True, on_delete=models.CASCADE,
                               related_name="+", default=escola_corrente_ou_nada, editable=False,
                               help_text="Vazio = da plataforma (sem escola)")

    tipo = models.CharField(max_length=30)
    assunto = models.CharField(max_length=200)
    corpo = models.TextField()
    ativo = models.BooleanField("Enviar este e-mail", default=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    atualizado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                       related_name="+")

    class Meta:
        verbose_name = "modelo de e-mail"
        verbose_name_plural = "modelos de e-mail"
        constraints = [
            models.UniqueConstraint(fields=["escola", "tipo"], name="modelo_email_unico_na_escola"),
            models.UniqueConstraint(fields=["tipo"], condition=models.Q(escola__isnull=True),
                                    name="modelo_email_padrao_unico"),
        ]

    @classmethod
    def vigente(cls, tipo, escola=None):
        """O texto da escola, senão o padrão da plataforma (escola vazia), senão None (texto do código)."""
        from escolas.escopo import escola_corrente

        escola = escola or escola_corrente(obrigatoria=False)
        modelos = {m.escola_id: m for m in cls.objects.filter(tipo=tipo).filter(
            models.Q(escola__isnull=True) | models.Q(escola=escola) if escola else models.Q(escola__isnull=True))}
        return modelos.get(escola.pk if escola else None) or modelos.get(None)

    def __str__(self):
        return self.tipo


class ErroSistema(models.Model):
    """Erro do servidor (página que deu erro 500 ou tarefa em segundo plano que falhou), agrupado por origem."""

    escola = models.ForeignKey("escolas.Escola", null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="+", default=escola_corrente_ou_nada, editable=False,
                               help_text="Vazio = da plataforma (sem escola)")
    _caminho_escola = "escola"
    objects = EscopoEscolaManager()

    assinatura = models.CharField(max_length=64, unique=True)
    tipo = models.CharField(max_length=120)
    mensagem = models.TextField(blank=True)
    origem = models.CharField(max_length=255, blank=True, help_text="Arquivo, linha e função onde o erro aconteceu")
    caminho = models.CharField(max_length=255, blank=True)
    metodo = models.CharField(max_length=10, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="+")
    detalhe = models.TextField(blank=True)
    ocorrencias = models.PositiveIntegerField(default=1)
    primeiro_em = models.DateTimeField(default=timezone.now)
    ultimo_em = models.DateTimeField(default=timezone.now, db_index=True)
    avisado_em = models.DateTimeField(null=True, blank=True)
    resolvido = models.BooleanField(default=False)

    class Meta:
        ordering = ["resolvido", "-ultimo_em"]
        verbose_name = "erro do sistema"
        verbose_name_plural = "erros do sistema"

    def __str__(self):
        return f"{self.tipo}: {self.mensagem[:60]}"


class RegistroAcao(models.Model):
    """Registro de ações: quem fez o quê, quando e de onde (entradas, contas, senhas, cadastros, exportações)."""

    escola = models.ForeignKey("escolas.Escola", null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="+", default=escola_corrente_ou_nada, editable=False,
                               help_text="Vazio = da plataforma (sem escola)")
    _caminho_escola = "escola"
    objects = EscopoEscolaManager()

    quando = models.DateTimeField(default=timezone.now, db_index=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="acoes")
    quem = models.CharField(max_length=160, blank=True, help_text="Nome e usuário no momento da ação")
    tipo = models.CharField(max_length=30, db_index=True)
    descricao = models.CharField(max_length=255)
    alvo = models.CharField(max_length=255, blank=True)
    caminho = models.CharField(max_length=255, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    aparelho = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ["-quando", "-pk"]
        indexes = [models.Index(fields=["usuario", "-quando"])]
        verbose_name = "ação registrada"
        verbose_name_plural = "registro de ações"

    def __str__(self):
        return f"{self.quando:%d/%m/%Y %H:%M} {self.quem}: {self.descricao}"


class VinculoResponsavel(models.Model):
    """Responsável legal que acompanha o estágio de um estudante: o do TCE ou quem pediu à escola. Um responsável
    pode acompanhar mais de um estudante (irmãos)."""

    escola = models.ForeignKey("escolas.Escola", on_delete=models.PROTECT, related_name="+",
                               default=escola_corrente_id, editable=False)
    _caminho_escola = "escola"
    objects = EscopoEscolaManager()

    class Origem(models.TextChoices):
        TCE = "TCE", "Termo de compromisso (TCE)"
        PEDIDO = "PEDIDO", "A pedido do responsável"

    estagiario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="responsaveis_legais")
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                    related_name="estudantes_acompanhados")
    parentesco = models.CharField("Parentesco", max_length=40, blank=True, help_text="Ex.: mãe, pai, avó, tio")
    origem = models.CharField(max_length=6, choices=Origem.choices, default=Origem.TCE)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)
    encerrado_em = models.DateTimeField(null=True, blank=True, help_text="A escola tirou o acesso deste responsável")
    encerrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name="+")

    class Meta:
        ordering = ["estagiario__nome_completo", "responsavel__nome_completo"]
        constraints = [models.UniqueConstraint(fields=["estagiario", "responsavel"], name="vinculo_responsavel_unico")]
        verbose_name = "responsável legal"
        verbose_name_plural = "responsáveis legais"

    def __str__(self):
        return f"{self.responsavel} → {self.estagiario}"

    @property
    def ativo(self):
        return self.encerrado_em is None


class SessaoAparelho(models.Model):
    """Cada aparelho em que a pessoa está conectada. A sessão fica presa ao aparelho em que começou (navegador e
    sistema, mais um cookie próprio): usada em outro aparelho, é encerrada. Ver core/sessoes.py."""

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sessoes")
    chave = models.CharField(max_length=40, unique=True, help_text="Chave da sessão do Django")
    aparelho = models.CharField(max_length=80, blank=True)
    assinatura = models.CharField(max_length=64, blank=True, help_text="Resumo do navegador e do sistema do aparelho")
    ip = models.GenericIPAddressField(null=True, blank=True)
    criada_em = models.DateTimeField(default=timezone.now)
    ultimo_uso = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-ultimo_uso"]
        verbose_name = "aparelho conectado"
        verbose_name_plural = "aparelhos conectados"

    def __str__(self):
        return f"{self.usuario} — {self.aparelho or 'aparelho'}"


class Substituicao(models.Model):
    """Permissão temporária para um funcionário da concedente confirmar presenças no lugar do supervisor."""

    _caminho_escola = "concedente__escola"
    objects = EscopoEscolaManager()

    concedente = models.ForeignKey(LocalEstagio, on_delete=models.CASCADE, related_name="substituicoes")
    titular = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="substituido_em",
        verbose_name="No lugar de", help_text="Vazio = todos os estagiários da concedente",
    )
    substituto = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="substituicoes",
                                   verbose_name="Quem vai confirmar")
    inicio = models.DateField("De")
    fim = models.DateField("Até")
    motivo = models.CharField("Motivo", max_length=150, blank=True, help_text="Ex.: férias do supervisor")
    criada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    criada_em = models.DateTimeField(auto_now_add=True)
    revogada_em = models.DateTimeField(null=True, blank=True)
    revogada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="+")

    class Meta:
        ordering = ["-inicio", "-pk"]
        verbose_name = "substituição de supervisor"
        verbose_name_plural = "substituições de supervisor"

    def __str__(self):
        return f"{self.substituto} no lugar de {self.titular or 'todos'} ({self.inicio:%d/%m}–{self.fim:%d/%m})"

    def vale_em(self, dia):
        return self.revogada_em is None and self.inicio <= dia <= self.fim

    def cobre(self, estagio):
        return estagio.local_id == self.concedente_id and (not self.titular_id or estagio.supervisor_id == self.titular_id)

    @property
    def situacao(self):
        hoje = timezone.localdate()
        if self.revogada_em:
            return "revogada"
        if self.fim < hoje:
            return "encerrada"
        return "ativa" if self.inicio <= hoje else "agendada"


class LinkConfirmacao(models.Model):
    """Link de uso único para o supervisor confirmar as presenças pendentes sem entrar no sistema."""

    escola = models.ForeignKey("escolas.Escola", on_delete=models.PROTECT, related_name="+",
                               default=escola_corrente_id, editable=False)
    _caminho_escola = "escola"
    objects = EscopoEscolaManager()

    class Canal(models.TextChoices):
        EMAIL = "EMAIL", "E-mail"
        WHATSAPP = "WHATSAPP", "WhatsApp"

    resumo = models.CharField(max_length=64, unique=True, help_text="SHA-256 do código do link (o código não é guardado)")
    supervisor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="links_confirmacao")
    registros = models.JSONField(default=list)
    canal = models.CharField(max_length=10, choices=Canal.choices, default=Canal.EMAIL)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)
    expira_em = models.DateTimeField()
    usado_em = models.DateTimeField(null=True, blank=True)
    confirmados = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "link de confirmação"
        verbose_name_plural = "links de confirmação"
