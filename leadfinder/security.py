from __future__ import annotations

import os
import re


SECRET_QUERY_RE = re.compile(
    r"(?i)(api[_-]?key|subscription[_-]?key|token|authorization)=([^&\s]+)"
)


def sanitize_error(value: object, secrets: tuple[str, ...] = ()) -> str:
    text = str(value or "")
    text = SECRET_QUERY_RE.sub(r"\1=[redacted]", text)
    known_secrets = secrets or tuple(
        os.getenv(name, "")
        for name in (
            "SERPER_API_KEY",
            "APOLLO_API_KEY",
            "HUNTER_API_KEY",
            "COMTRADE_API_KEY",
            "COMTRADE_API_KEY_SECONDARY",
        )
    )
    for secret in known_secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text[:1000]
