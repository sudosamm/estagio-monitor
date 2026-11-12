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
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.TrocaSenhaObrigatoriaMiddleware",
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

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "db.sqlite3",
        "OPTIONS": {
            "transaction_mode": "IMMEDIATE",
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000;",
        },
    }
}

AUTH_USER_MODEL = "core.Usuario"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 6}},
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
]
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
SENHA_PADRAO = os.environ.get("SENHA_PADRAO", "estagio123")
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

# Notificações no celular (Web Push, pelo app instalado ou pelo navegador). As chaves VAPID são criadas
# sozinhas em DATA_DIR/vapid_privada.pem na primeira vez; troque-as e quem ativou precisa ativar de novo.
PUSH_ATIVO = env_bool("PUSH_ATIVO", True)
VAPID_ARQUIVO = Path(os.environ.get("VAPID_ARQUIVO", DATA_DIR / "vapid_privada.pem"))
# contato exigido pelos serviços de push (Google, Apple, Mozilla): mailto:… ou https://…
VAPID_CONTATO = os.environ.get("VAPID_CONTATO") or (
    SITE_URL if SITE_URL.startswith("https://") else f"mailto:{DEFAULT_FROM_EMAIL.split('<')[-1].strip('> ')}")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
