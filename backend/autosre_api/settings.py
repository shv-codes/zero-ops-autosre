"""
AutoSRE settings.

Everything that differs between machines (secrets, hosts, paths, modes) comes from
environment variables or the repo-level `.env` file. Nothing secret lives in code (NFR-S1).
"""
import os
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
REPO_ROOT = BASE_DIR.parent


def _load_env(path: Path) -> None:
    """Load `.env`. django-environ keeps an unquoted ` # comment` as part of the value."""
    if not path.exists():
        return
    environ.Env.read_env(path)
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key, raw_value = key.strip(), raw_value.strip()
        if not key or not raw_value or raw_value[0] in "\"'":
            continue
        if " #" not in raw_value:
            continue
        current = os.environ.get(key)
        if current is not None and current.strip() == raw_value:
            os.environ[key] = raw_value.split(" #", 1)[0].rstrip()


env = environ.Env()
_load_env(REPO_ROOT / ".env")

VAR_DIR = Path(env("AUTOSRE_VAR_DIR", default=str(REPO_ROOT / "var"))).resolve()
VAR_DIR.mkdir(parents=True, exist_ok=True)

SECRET_KEY = env("DJANGO_SECRET_KEY", default="autosre-dev-only-not-secret")
DEBUG = env.bool("DEBUG", default=True)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["*"])
# Render sets this to the service's public hostname.
if env("RENDER_EXTERNAL_HOSTNAME", default=""):
    ALLOWED_HOSTS.append(env("RENDER_EXTERNAL_HOSTNAME"))

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "incidents",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "autosre_api.urls"
ASGI_APPLICATION = "autosre_api.asgi.application"
WSGI_APPLICATION = "autosre_api.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# AutoSRE keeps its own state in SQLite on purpose: the database we are rescuing
# (the victim's PostgreSQL) is exactly the thing that is full during an incident.
# WAL mode + IMMEDIATE transactions let the agent thread, the monitor thread and
# web requests write at the same time without "database is locked" errors.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": env("AUTOSRE_DB_PATH", default=str(VAR_DIR / "autosre.sqlite3")),
        "OPTIONS": {
            "timeout": 30,
            "transaction_mode": "IMMEDIATE",
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Behind a hosting proxy (Render) the original scheme arrives in this header.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "incidents.api.envelope.exception_handler",
}

CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=["http://localhost:5173", "http://127.0.0.1:5173"],
)
# e.g. ^https://zero-ops-autosre(-[a-z0-9-]+)?\.vercel\.app$ to also allow Vercel preview URLs
CORS_ALLOWED_ORIGIN_REGEXES = env.list("CORS_ALLOWED_ORIGIN_REGEXES", default=[])

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
    "loggers": {"httpx": {"level": "WARNING"}, "urllib3": {"level": "WARNING"}},
}

# ---------------------------------------------------------------------------
# AutoSRE runtime configuration
# ---------------------------------------------------------------------------
AUTOSRE = {
    # cached = scripted agent brain (no API keys needed), live = real LLM, replay = play back a recorded run
    "MODE": env("AUTOSRE_MODE", default="cached"),
    "MAX_ATTEMPTS": env.int("AUTOSRE_MAX_ATTEMPTS", default=3),
    "AGENT_MAX_STEPS": env.int("AUTOSRE_AGENT_MAX_STEPS", default=30),
    # Outer loop (watching the PR until it is ready to merge)
    "PR_MAX_ROUNDS": env.int("AUTOSRE_PR_MAX_ROUNDS", default=5),
    "PR_POLL_SECONDS": env.float("AUTOSRE_PR_POLL_SECONDS", default=10),
    "PR_WATCH_TIMEOUT_SECONDS": env.int("AUTOSRE_PR_WATCH_TIMEOUT_SECONDS", default=1800),
    # Review mode: how long to wait for a human decision before escalating / skipping
    "APPROVAL_TIMEOUT_SECONDS": env.int("AUTOSRE_APPROVAL_TIMEOUT_SECONDS", default=900),
    # Alert monitor
    "MONITOR_ENABLED": env.bool("AUTOSRE_MONITOR_ENABLED", default=True),
    "MONITOR_INTERVAL_SECONDS": env.float("AUTOSRE_MONITOR_INTERVAL_SECONDS", default=2),
    "ALERT_THRESHOLD": env.float("AUTOSRE_ALERT_THRESHOLD", default=0.9),
    "IDLE_IN_TX_MIN_SECONDS": env.int("AUTOSRE_IDLE_IN_TX_MIN_SECONDS", default=5),
}

# Target (monitored) database. AutoSRE uses its own least-privilege role
# (pg_monitor + pg_signal_backend), never the application's credentials.
TARGET_DB = {
    "ENGINE": env("TARGET_DB_ENGINE", default="postgres"),
    "HOST": env("TARGET_DB_HOST", default="localhost"),
    "PORT": env.int("TARGET_DB_PORT", default=5432),
    "NAME": env("TARGET_DB_NAME", default="victim_db"),
    "USER": env("TARGET_DB_USER", default="autosre_agent"),
    "PASSWORD": env("TARGET_DB_PASSWORD", default="autosre_agent_pw"),
    # Only sessions whose application_name starts with this are ever terminated (NFR-F4).
    "APP_NAME_PREFIX": env("TARGET_APP_NAME_PREFIX", default="victim-service"),
}

TARGET_APP = {
    "BASE_URL": env("VICTIM_BASE_URL", default="http://localhost:8001"),
    "LOG_PATH": env("VICTIM_LOG_PATH", default=str(VAR_DIR / "logs" / "victim.log")),
}

# Target repository. REPO_PATH is a working clone used for reading history;
# fixes are always made in a temporary clone, never here (FR-4.4).
TARGET_REPO = {
    "PATH": env("TARGET_REPO_PATH", default=str(VAR_DIR / "victim_repo")),
    "BASE_BRANCH": env("TARGET_BASE_BRANCH", default="main"),
    "LOOKBACK_COMMITS": env.int("CORRELATION_LOOKBACK_COMMITS", default=20),
    "LOOKBACK_DAYS": env.int("CORRELATION_LOOKBACK_DAYS", default=7),
}

DELIVERY = {
    # local = bare git repo acting as "origin" (works offline); github = real PRs
    "PROVIDER": env("DELIVERY_PROVIDER", default="local"),
    "LOCAL_ORIGIN": env("LOCAL_ORIGIN_PATH", default=str(VAR_DIR / "victim_origin.git")),
    # Recommended: a GitHub App (its own bot identity, per-repo install, 1-hour tokens).
    "GITHUB_APP_ID": env("GITHUB_APP_ID", default=""),
    "GITHUB_APP_PRIVATE_KEY_PATH": env("GITHUB_APP_PRIVATE_KEY_PATH", default=str(REPO_ROOT / "secrets" / "github-app.pem")),
    "GITHUB_APP_INSTALLATION_ID": env("GITHUB_APP_INSTALLATION_ID", default=""),
    # Fallback: a fine-grained personal access token.
    "GITHUB_TOKEN": env("GITHUB_TOKEN", default=""),
    "GITHUB_REPO": env("GITHUB_REPO", default=""),
    "LABELS": env.list("PR_LABELS", default=["autosre", "verified"]),
}

LLM = {
    "PROVIDER": env("LLM_PROVIDER", default="groq"),
    "TIMEOUT_SECONDS": env.float("LLM_TIMEOUT_SECONDS", default=60),
    "MAX_OUTPUT_TOKENS": env.int("LLM_MAX_OUTPUT_TOKENS", default=1024),
    "REASONING_EFFORT": env("LLM_REASONING_EFFORT", default="low"),
    # Prompt-injection classifier (Meta Llama Prompt Guard 2 on Groq), used in live mode
    "PROMPT_GUARD_ENABLED": env.bool("PROMPT_GUARD_ENABLED", default=True),
    "PROMPT_GUARD_MODEL": env("PROMPT_GUARD_MODEL", default="meta-llama/llama-prompt-guard-2-86m"),
    "PROVIDERS": {
        "groq": {
            "BASE_URL": env("GROQ_BASE_URL", default="https://api.groq.com/openai/v1"),
            "API_KEY": env("GROQ_API_KEY", default=""),
            "MODEL": env("GROQ_MODEL", default="openai/gpt-oss-120b"),
            # Free tier caps tokens per minute; AutoSRE paces itself and trims old context to fit.
            "TOKENS_PER_MINUTE": env.int("GROQ_TOKENS_PER_MINUTE", default=8000),
            # Tried in order when the primary model's quota (e.g. free daily cap) runs out
            "FALLBACK_MODELS": env.list("GROQ_FALLBACK_MODELS", default=["openai/gpt-oss-20b", "qwen/qwen3.8-27b"]),
        },
        "nvidia": {
            "BASE_URL": env("NVIDIA_BASE_URL", default="https://integrate.api.nvidia.com/v1"),
            "API_KEY": env("NVIDIA_API_KEY", default=""),
            "MODEL": env("NVIDIA_MODEL", default="nvidia/llama-3.3-nemotron-super-49b-v1.5"),
            "TOKENS_PER_MINUTE": env.int("NVIDIA_TOKENS_PER_MINUTE", default=0),
            "FALLBACK_MODELS": env.list("NVIDIA_FALLBACK_MODELS", default=[]),
        },
    },
}

# Where the GitHub App install flow sends the browser back to.
FRONTEND_URL = env("FRONTEND_URL", default="http://127.0.0.1:5173")

SANDBOX = {
    # cached = recorded check/test results (prototype, no Docker). auto = Docker if it is running.
    "ENGINE": env("SANDBOX_ENGINE", default="cached"),
    "TIMEOUT_SECONDS": env.int("SANDBOX_TIMEOUT_SECONDS", default=120),
    "MEMORY": env("SANDBOX_MEMORY", default="512m"),
    "CPUS": env.float("SANDBOX_CPUS", default=1.0),
    "WORK_DIR": str(VAR_DIR / "sandbox"),
}
