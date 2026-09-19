import os
import re

DEFAULT_API_URL = "http://127.0.0.1:8000"
ENV_API_URL_VAR = "IRTRIXAI_API_URL"

URL_CREDENTIAL_PATTERN = re.compile(r"://([^:]+):([^@]+)@")


def sanitize_url_for_display(url: str) -> str:
    """Strips any embedded credentials from URLs before display or logging."""
    return URL_CREDENTIAL_PATTERN.sub("://[REDACTED]:[REDACTED]@", url)


def resolve_api_url(explicit_url: str | None = None) -> str:
    """
    Resolves the target backend API URL according to strict precedence:
    1. Explicit CLI argument (--api-url)
    2. Environment variable (IRTRIXAI_API_URL)
    3. Default local development server (http://127.0.0.1:8000)
    """
    if explicit_url and explicit_url.strip():
        url = explicit_url.strip()
    elif os.environ.get(ENV_API_URL_VAR, "").strip():
        url = os.environ[ENV_API_URL_VAR].strip()
    else:
        url = DEFAULT_API_URL

    return url.rstrip("/")
