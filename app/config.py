"""Настройки берутся из переменных окружения (файл .env). Секретов в коде нет."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _int_or_none(value: str | None) -> int | None:
    value = (value or "").strip()
    return int(value) if value else None


@dataclass(frozen=True)
class Config:
    bot_token: str
    storage: str  # sqlite | sheets
    sqlite_path: str
    google_credentials_file: str
    spreadsheet_id: str
    feedback_chat_id: int | None  # служебный чат ТУ и собственника
    hr_chat_id: int | None  # куда приходят заявки на добавление сотрудника
    newbie_days: int
    cache_ttl: float
    timezone: str

    @classmethod
    def from_env(cls) -> Config:
        load_dotenv()
        return cls(
            bot_token=os.getenv("BOT_TOKEN", "").strip(),
            storage=os.getenv("STORAGE", "sqlite").strip().lower(),
            sqlite_path=os.getenv("SQLITE_PATH", "data/portal.sqlite3"),
            google_credentials_file=os.getenv("GOOGLE_CREDENTIALS_FILE", "secrets/google.json"),
            spreadsheet_id=os.getenv("SPREADSHEET_ID", "").strip(),
            feedback_chat_id=_int_or_none(os.getenv("FEEDBACK_CHAT_ID")),
            hr_chat_id=_int_or_none(os.getenv("HR_CHAT_ID")),
            newbie_days=int(os.getenv("NEWBIE_DAYS", "28")),
            cache_ttl=float(os.getenv("CACHE_TTL_SECONDS", "60")),
            timezone=os.getenv("TIMEZONE", "Europe/Moscow"),
        )


def build_repository(config: Config):
    from app.storage.backend import CachedBackend
    from app.storage.repository import Repository

    if config.storage == "sheets":
        from app.storage.sheets_backend import SheetsBackend

        inner = SheetsBackend(config.google_credentials_file, config.spreadsheet_id)
        ttl = config.cache_ttl
    elif config.storage == "sqlite":
        from app.storage.sqlite_backend import SqliteBackend

        inner = SqliteBackend(config.sqlite_path)
        ttl = 0.0  # локальная база быстрая, кэш не нужен
    else:
        raise ValueError(f"Неизвестное STORAGE={config.storage!r}: ожидается sqlite или sheets")
    return Repository(CachedBackend(inner, ttl=ttl), timezone=config.timezone)
