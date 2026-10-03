import os
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
INSTALLED_APPS = ["django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles", "rest_framework", "rest_framework.authtoken", "rest_framework_simplejwt.token_blacklist", "corsheaders", "channels", "django_celery_beat", "crm"]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware", "corsheaders.middleware.CorsMiddleware", "django.contrib.sessions.middleware.SessionMiddleware", "django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware", "django.contrib.auth.middleware.AuthenticationMiddleware", "django.contrib.messages.middleware.MessageMiddleware", "django.middleware.clickjacking.XFrameOptionsMiddleware"]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [], "APP_DIRS": True, "OPTIONS": {"context_processors": ["django.template.context_processors.request", "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages"]}}]
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {"default": {"ENGINE": "django.db.backends.postgresql", "NAME": os.getenv("POSTGRES_DB", "crm"), "USER": os.getenv("POSTGRES_USER", "crm"), "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""), "HOST": os.getenv("POSTGRES_HOST", "localhost"), "PORT": os.getenv("POSTGRES_PORT", "5432")}}
if os.getenv("TEST_SQLITE") == "1":
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "test.sqlite3"}}
# Dois esquemas de autenticação, cada um pra um consumidor diferente:
# - JWTAuthentication: usuários humanos no frontend (access token de vida curta
#   + refresh token, ver SIMPLE_JWT abaixo). Nunca usa cookie/sessão, então não
#   tem o mesmo risco de CSRF que SessionAuthentication tinha (ver histórico).
# - TokenAuthentication: mantido só pela conta de serviço do agente Axioma, que
#   usa um token fixo pré-provisionado (nunca passa por /api/login/).
REST_FRAMEWORK = {"DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework_simplejwt.authentication.JWTAuthentication", "rest_framework.authentication.TokenAuthentication"], "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"], "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination", "PAGE_SIZE": 100, "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"], "DEFAULT_THROTTLE_RATES": {"agent-incoming": "60/minute"}}

from datetime import timedelta
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=14),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}
CORS_ALLOWED_ORIGINS = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",")
# Necessário pro cookie httpOnly do refresh token (ver crm/views.py) ir e
# voltar em requisições cross-origin -- caso de dev local sem Docker, onde o
# Vite (porta 5173) e o Django (porta 8000) são origens diferentes.
CORS_ALLOW_CREDENTIALS = True
# Secure=true (cookie só trafega em HTTPS) é o padrão -- correto em produção,
# onde o navegador sempre fala com o Caddy via HTTPS. Em dev local sem TLS
# (compose.yaml), setar COOKIE_SECURE=false no ambiente do backend, senão o
# navegador nunca manda o cookie de volta e o refresh sempre falha.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() == "true"
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Fortaleza"
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_PASSWORD_VALIDATORS = [{"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"}, {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"}, {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"}, {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"}]

ASGI_APPLICATION = "config.asgi.application"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Foto de perfil (crm.Profile.avatar). Caddy serve isso em /media/* a partir
# do mesmo volume (ver compose.prod.yaml e deploy/Caddyfile.prod).
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
CSRF_TRUSTED_ORIGINS = os.getenv("CSRF_TRUSTED_ORIGINS", "http://localhost:8080").split(",")

# E-mail (convite de atendente e credenciais provisórias). Backend padrão é o
# console (aparece no log, sem precisar de SMTP real) — em produção, setar
# EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend e as credenciais
# reais via variável de ambiente protegida, nunca no código.
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "true").lower() == "true"
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "naoresponda@axiomaia.com.br")
# Base do frontend usada para montar o link de validação de convite enviado por e-mail.
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")

# Em produção, setar DJANGO_HTTPS=true no ambiente do backend (quando o Caddy já estiver
# emitindo TLS para um domínio real) para forçar redirecionamento HTTPS e cookies seguros.
DJANGO_HTTPS = os.getenv("DJANGO_HTTPS") == "true"
SECURE_SSL_REDIRECT = DJANGO_HTTPS
SESSION_COOKIE_SECURE = DJANGO_HTTPS
CSRF_COOKIE_SECURE = DJANGO_HTTPS
SECURE_HSTS_SECONDS = 31536000 if DJANGO_HTTPS else 0
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if DJANGO_HTTPS else None
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CHANNEL_LAYERS = {"default": {"BACKEND": "channels_redis.core.RedisChannelLayer", "CONFIG": {"hosts": [os.getenv("CHANNEL_REDIS_URL", "redis://localhost:6379/2")]}}}
