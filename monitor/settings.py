"""Configurações do Estágio Monitor.

Tudo que muda entre ambientes vem de variáveis de ambiente (ver .env.example).
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "sim", "on"}


def env_list(name, default=""):
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


SECRET_KEY = os.environ.get("SECRET_KEY", "dev-inseguro-troque-em-producao")
DEBUG = env_bool("DEBUG", False)
if not DEBUG and SECRET_KEY == "dev-inseguro-troque-em-producao" and "test" not in sys.argv:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("Defina SECRET_KEY (uma chave longa e aleatória) nas variáveis de ambiente.")
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
# O healthcheck do container acessa http://127.0.0.1:8000/saude/
for _h in ("localhost", "127.0.0.1"):
    if _h not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_h)
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "")

# Atrás do Cloudflare Tunnel / proxy do Coolify
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
SESSION_COOKIE_SECURE = env_bool("COOKIES_SEGUROS", not DEBUG)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14  # 14 dias
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
# HTTPS obrigatório (FORCAR_HTTPS=1): redireciona http→https e manda HSTS. Ligue depois de confirmar que o site abre
# por https; o healthcheck interno (/saude/) continua em http.
SECURE_SSL_REDIRECT = env_bool("FORCAR_HTTPS", False)
SECURE_REDIRECT_EXEMPT = [r"^saude/$"]
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365 if SECURE_SSL_REDIRECT else 0

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "core.middleware.CaractereNuloMiddleware",  # o PostgreSQL recusa NUL: 400 em vez de erro 500
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "core.middleware.CacheDaRequisicaoMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.ModoAdministradorMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "core.sessoes.SessaoAparelhoMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.TrocaSenhaObrigatoriaMiddleware",
    "core.middleware.AreaDoResponsavelMiddleware",
    "core.auditoria.AuditoriaMiddleware",
    "core.middleware.ResumoSemanalMiddleware",
]

ROOT_URLCONF = "monitor.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.globais",
            ],
        },
    },
]

WSGI_APPLICATION = "monitor.wsgi.application"

# Dados persistentes (banco + anexos) ficam em DATA_DIR -> volume no Docker
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Banco: com DATABASE_URL (postgres://usuario:senha@host:5432/nome), PostgreSQL; sem ela, o SQLite de sempre em
# DATA_DIR. Tirar a variável é a reversão do deploy do PostgreSQL (ver docs/operacao/migracao-postgresql.md).
from .banco import config_da_url, config_sqlite  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
DATABASES = {
    "default": config_da_url(DATABASE_URL, int(os.environ.get("DB_CONN_MAX_AGE", "60")))
    if DATABASE_URL else config_sqlite(DATA_DIR / "db.sqlite3")
}

# dumpdata/loaddata sem perder os microssegundos das datas (troca de banco; ver core/serializacao_precisa.py)
SERIALIZATION_MODULES = {"jsonlp": "core.serializacao_precisa"}

# Backup do volume de dados para fora do servidor (Cloudflare R2 ou outro S3). Ver docs/operacao/backup.md.
BACKUP_CHAVE = os.environ.get("BACKUP_CHAVE", "")
BACKUP_S3_ENDPOINT = os.environ.get("BACKUP_S3_ENDPOINT", "")  # https://<conta>.r2.cloudflarestorage.com
BACKUP_S3_BUCKET = os.environ.get("BACKUP_S3_BUCKET", "")
BACKUP_S3_CHAVE_ID = os.environ.get("BACKUP_S3_CHAVE_ID", "")
BACKUP_S3_SEGREDO = os.environ.get("BACKUP_S3_SEGREDO", "")
BACKUP_S3_REGIAO = os.environ.get("BACKUP_S3_REGIAO", "auto")
BACKUP_PREFIXO = os.environ.get("BACKUP_PREFIXO", "volume-dados")
BACKUP_PASTA = os.environ.get("BACKUP_PASTA", "")  # alternativa ao S3: uma pasta (disco externo montado)
BACKUP_SQLITE = os.environ.get("BACKUP_SQLITE", "")  # arquivo SQLite a copiar (padrão: o banco em uso, se for SQLite)
BACKUP_TRABALHO = os.environ.get("BACKUP_TRABALHO", "")  # pasta temporária (padrão: DATA_DIR/.backup-trabalho)
BACKUP_RETENCAO_DIAS = int(os.environ.get("BACKUP_RETENCAO_DIAS", "7"))
BACKUP_RETENCAO_SEMANAS = int(os.environ.get("BACKUP_RETENCAO_SEMANAS", "4"))
BACKUP_RETENCAO_MESES = int(os.environ.get("BACKUP_RETENCAO_MESES", "6"))

AUTH_USER_MODEL = "core.Usuario"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "core.seguranca.SenhaDiferenteDaPadrao"},
]
# Limite de tentativas de login (core/seguranca.py), também no /admin/
AUTHENTICATION_BACKENDS = ["core.seguranca.BackendComLimite"]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "inicio"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "pt-br"
TIME_ZONE = os.environ.get("TZ", "America/Fortaleza")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not (DEBUG or "test" in sys.argv)
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

# Anexos NÃO são servidos publicamente: passam por uma view que checa permissão.
MEDIA_ROOT = DATA_DIR / "anexos"
MEDIA_URL = "/nao-publico/"
DATA_UPLOAD_MAX_MEMORY_SIZE = 15 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
TAMANHO_MAX_ANEXO_MB = int(os.environ.get("TAMANHO_MAX_ANEXO_MB", "10"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Regras do sistema
# Senha que as contas antigas recebiam ao ser criadas. Ela não abre mais contas que ainda não fizeram o primeiro
# acesso (agora é nome + nascimento ou código de uso único). ACEITAR_SENHA_PADRAO=1 reabre, só para emergência.
SENHA_PADRAO = os.environ.get("SENHA_PADRAO", "estagio123")
ACEITAR_SENHA_PADRAO = env_bool("ACEITAR_SENHA_PADRAO", False)
PASSWORD_RESET_TIMEOUT = 2 * 3600  # link de “Esqueci minha senha” vale 2 horas
NOME_SISTEMA = os.environ.get("NOME_SISTEMA", "Estágio Monitor")
NOME_INSTITUICAO = os.environ.get("NOME_INSTITUICAO", "Secretaria da Educação do Ceará")

# Avisos por e-mail (SMTP). Sem EMAIL_HOST, os avisos ficam só no sino do sistema.
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", EMAIL_PORT == 465)
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", not EMAIL_USE_SSL)
EMAIL_TIMEOUT = 20
DEFAULT_FROM_EMAIL = os.environ.get("EMAIL_REMETENTE") or (
    f"{NOME_SISTEMA} <{EMAIL_HOST_USER}>" if "@" in EMAIL_HOST_USER else "nao-responda@localhost")
# EMAIL_CONSOLE=1 mostra os e-mails no terminal em vez de enviar (para testar sem servidor de e-mail)
if env_bool("EMAIL_CONSOLE", False):
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
EMAIL_ATIVO = bool(EMAIL_HOST) or env_bool("EMAIL_CONSOLE", False)
EMAIL_ASSINCRONO = "test" not in sys.argv  # envia em segundo plano para não atrasar a página
# Resumo semanal: sai sozinho no primeiro acesso depois de segunda, 6h. RESUMO_AUTOMATICO=0 desliga esse
# disparo (por exemplo, se preferir agendar  python manage.py enviar_resumo_semanal  no cron/Coolify).
RESUMO_AUTOMATICO = env_bool("RESUMO_AUTOMATICO", "test" not in sys.argv)
# Endereço público do sistema, usado nos links dos e-mails. Vazio = o primeiro de CSRF_TRUSTED_ORIGINS.
SITE_URL = (os.environ.get("SITE_URL") or (CSRF_TRUSTED_ORIGINS[0] if CSRF_TRUSTED_ORIGINS else "")).rstrip("/")

# Destino da página “Sugestões e erros” (o administrador também pode definir em Configurações)
SUGESTOES_EMAIL = os.environ.get("SUGESTOES_EMAIL", "")
SUGESTOES_MAX_ARQUIVOS = 5
SUGESTOES_MAX_MB = 20  # soma dos anexos de um envio

# Notificações no celular (Web Push, pelo app instalado ou pelo navegador). As chaves VAPID são criadas
# sozinhas em DATA_DIR/vapid_privada.pem na primeira vez; troque-as e quem ativou precisa ativar de novo.
PUSH_ATIVO = env_bool("PUSH_ATIVO", True)
VAPID_ARQUIVO = Path(os.environ.get("VAPID_ARQUIVO", DATA_DIR / "vapid_privada.pem"))
# contato exigido pelos serviços de push (Google, Apple, Mozilla): mailto:… ou https://…
VAPID_CONTATO = os.environ.get("VAPID_CONTATO") or (
    SITE_URL if SITE_URL.startswith("https://") else f"mailto:{DEFAULT_FROM_EMAIL.split('<')[-1].strip('> ')}")

# Termos de Uso e Aviso de Privacidade: quem ainda não aceitou a versão atual é levado à tela de aceite.
# Nos testes fica desligado (cada teste que precisa liga com override_settings).
EXIGIR_ACEITE_TERMOS = env_bool("EXIGIR_ACEITE_TERMOS", "test" not in sys.argv)

# Só nos testes: tira da saída os logs esperados (403, 404, backup sem chave). Ver core/executor_testes.py.
TEST_RUNNER = "core.executor_testes.ExecutorDeTestes"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
        # erros de página (500) e das tarefas em segundo plano viram aviso para os administradores (core/alertas.py)
        "alerta": {"class": "core.alertas.AlertaErroHandler", "level": "ERROR"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.request": {"handlers": ["alerta"], "level": "WARNING"},
        "core": {"handlers": ["alerta"], "level": "INFO"},
    },
}
