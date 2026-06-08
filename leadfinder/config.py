from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    serper_api_key: str
    apollo_api_key: str
    hunter_api_key: str
    comtrade_api_key: str
    comtrade_api_key_secondary: str
    crm_url: str
    db_path: Path
    max_pages: int
    timeout_seconds: float


def settings(env_path: str | Path = ".env") -> Settings:
    load_dotenv(env_path)
    return Settings(
        serper_api_key=os.getenv("SERPER_API_KEY", "").strip(),
        apollo_api_key=os.getenv("APOLLO_API_KEY", "").strip(),
        hunter_api_key=os.getenv("HUNTER_API_KEY", "").strip(),
        comtrade_api_key=os.getenv("COMTRADE_API_KEY", "").strip(),
        comtrade_api_key_secondary=os.getenv("COMTRADE_API_KEY_SECONDARY", "").strip(),
        crm_url=os.getenv("LEADFINDER_CRM_URL", "http://127.0.0.1:5173").strip(),
        db_path=Path(os.getenv("LEADFINDER_DB_PATH", "data/leadfinder.sqlite")),
        max_pages=max(1, min(int(os.getenv("LEADFINDER_MAX_PAGES", "5")), 12)),
        timeout_seconds=max(1.0, float(os.getenv("LEADFINDER_TIMEOUT_SECONDS", "12"))),
    )
