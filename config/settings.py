"""
Django settings for Farsh Operations.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


def env_list(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def env_str(name: str, default: str = "") -> str:
    """Read env value; strip whitespace, BOM, and surrounding quotes (Dokploy-safe)."""
    raw = os.environ.get(name)
    if raw is None:
        # Case-insensitive fallback (some panels alter casing)
        target = name.lower()
        for key, value in os.environ.items():
            if key.lower() == target:
                raw = value
                break
    if raw is None:
        return default
    val = str(raw).replace("\ufeff", "").strip()
    # Strip matching quotes: "…" or '…' or “…” 
    if len(val) >= 2 and val[0] in ('"', "'", "“", "”", "‘", "’") and val[-1] in ('"', "'", "“", "”", "‘", "’"):
        val = val[1:-1].strip()
    # Ignore placeholder bullets copied from UI
    if val.replace("•", "").strip() == "":
        return default
    return val


SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "django-insecure-7!i_(tq2-o(w-fq77$f79%rn&1ro*67zun%=9rn7g6*3p95x9@",
)

DEBUG = env_bool("DEBUG", True)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_htmx",
    "accounts",
    "ops",
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
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "config.urls"

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
                "ops.context_processors.branch_defaults",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

_db_engine = os.environ.get("DB_ENGINE", "").lower()
_mysql_host = os.environ.get("MYSQL_HOST") or os.environ.get("DB_HOST")
_postgres_host = os.environ.get("POSTGRES_HOST")

if _db_engine in ("mysql", "mariadb") or (_mysql_host and _db_engine != "postgres"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.environ.get("MYSQL_DATABASE", os.environ.get("DB_NAME", "f_dba")),
            "USER": os.environ.get("MYSQL_USER", os.environ.get("DB_USER", "fuser")),
            "PASSWORD": os.environ.get(
                "MYSQL_PASSWORD", os.environ.get("DB_PASSWORD", "")
            ),
            "HOST": _mysql_host or "localhost",
            "PORT": os.environ.get("MYSQL_PORT", os.environ.get("DB_PORT", "3306")),
            "OPTIONS": {
                "charset": "utf8mb4",
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }
elif _postgres_host or os.environ.get("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "farsh"),
            "USER": os.environ.get("POSTGRES_USER", "farsh"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": _postgres_host or "db",
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.environ.get("SQLITE_PATH", str(BASE_DIR / "db.sqlite3")),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ar"
TIME_ZONE = "Asia/Riyadh"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
# رفع صور ردود المهام (عدة صور في طلب واحد)
DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "ops:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

# Behind Dokploy / Traefik reverse proxy
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

if not DEBUG:
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", False)
    CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", False)
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", False)

# Evolution API (WhatsApp notifications)
# يتوافق مع أسماء النظام الآخر: EVOLUTION_API_URL / EVOLUTION_INSTANCE / AUTHENTICATION_API_KEY
EVOLUTION_SERVER_URL = (
    env_str("EVOLUTION_SERVER_URL")
    or env_str("EVOLUTION_API_URL")
    or "http://72.61.107.230:8081"
).rstrip("/")
EVOLUTION_API_KEY = (
    env_str("EVOLUTION_API_KEY")
    or env_str("AUTHENTICATION_API_KEY")
)
EVOLUTION_INSTANCE_NAME = (
    env_str("EVOLUTION_INSTANCE_NAME")
    or env_str("EVOLUTION_INSTANCE")
    or ""
)
EVOLUTION_NOTIFY_ENABLED = env_bool(
    "EVOLUTION_NOTIFY_ENABLED",
    env_bool("WHATSAPP_ENABLED", bool(EVOLUTION_API_KEY and EVOLUTION_INSTANCE_NAME)),
)
# شهادات sslip.io / self-signed — للمنفذ HTTP المحلي اترك False
EVOLUTION_VERIFY_SSL = env_bool("EVOLUTION_VERIFY_SSL", False)

# رابط عام للمهام والـ PDF (واتساب) — https://fresh.alrsheed.net
PUBLIC_BASE_URL = env_str("PUBLIC_BASE_URL", "https://fresh.alrsheed.net").rstrip("/")


def _public_url_hosts(base_url: str) -> list[str]:
    """Hosts for ALLOWED_HOSTS — domain + sslip.io fallback if PUBLIC_BASE_URL is still an IP."""
    import re
    from urllib.parse import urlparse

    host = (urlparse(base_url).hostname or "").strip()
    if not host:
        return []
    hosts = [host]
    if not host.startswith("www.") and "." in host and not re.fullmatch(
        r"(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})", host
    ):
        hosts.append(f"www.{host}")
    match = re.fullmatch(r"(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})", host)
    if match:
        hosts.append("-".join(match.groups()) + ".sslip.io")
    return hosts


def _public_url_origins(base_url: str) -> list[str]:
    """CSRF origins for forms behind Dokploy / Traefik."""
    from urllib.parse import urlparse

    if not base_url:
        return []
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        return [base_url.rstrip("/")]

    def _origin(scheme: str, hostname: str, port: int | None) -> str:
        if port and port not in (80, 443):
            netloc = f"{hostname}:{port}"
        else:
            netloc = hostname
        return f"{scheme}://{netloc}".rstrip("/")

    host = parsed.hostname or ""
    port = parsed.port
    origins = [
        _origin(parsed.scheme, host, port),
        _origin("https" if parsed.scheme == "http" else "http", host, port),
    ]
    for alt_host in _public_url_hosts(base_url):
        if alt_host != host:
            origins.append(_origin(parsed.scheme, alt_host, port))
            origins.append(_origin("https" if parsed.scheme == "http" else "http", alt_host, port))
    return list(dict.fromkeys(o for o in origins if o))


def _merge_allowed_hosts() -> list[str]:
    """Avoid DisallowedHost (400) — merge env, PUBLIC_BASE_URL, and local dev."""
    merged: list[str] = []
    for host in env_list("ALLOWED_HOSTS", "fresh.alrsheed.net,localhost,127.0.0.1"):
        if host and host != "*":
            merged.append(host)
    merged.extend(_public_url_hosts(PUBLIC_BASE_URL))
    # Dokploy/nginx often forwards with Host=Compose service name (web) without X-Forwarded-Host.
    for host in (
        "localhost",
        "127.0.0.1",
        "fresh.alrsheed.net",
        "www.fresh.alrsheed.net",
        ".alrsheed.net",
        "web",
    ):
        if host not in merged:
            merged.append(host)
    return list(dict.fromkeys(merged))


ALLOWED_HOSTS = _merge_allowed_hosts()

_csrf_origins = env_list(
    "CSRF_TRUSTED_ORIGINS",
    "https://fresh.alrsheed.net,http://fresh.alrsheed.net",
)
for _origin in _public_url_origins(PUBLIC_BASE_URL):
    if _origin not in _csrf_origins:
        _csrf_origins.append(_origin)
# Legacy IP access during migration
for _legacy in ("http://72.61.107.230:7080", "https://72.61.107.230:7080"):
    if _legacy not in _csrf_origins:
        _csrf_origins.append(_legacy)
CSRF_TRUSTED_ORIGINS = list(dict.fromkeys(_csrf_origins))
