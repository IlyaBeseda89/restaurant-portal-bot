"""Ссылки Google Диска: id файла, прямая ссылка и скачивание файла ботом."""

from __future__ import annotations

import re
from urllib.parse import unquote

import aiohttp

_ID = re.compile(r"(?:/file/d/|[?&]id=)([\w-]{10,})")
MAX_BYTES = 45 * 1024 * 1024  # потолок Telegram для ботов 50 МБ, оставляем запас
_NAME = re.compile(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", re.IGNORECASE)


class DriveError(Exception):
    """Файл не удалось получить: закрыт доступ, слишком большой или не файл."""


def drive_file_id(url: str) -> str | None:
    if "drive.google.com" not in url:
        return None
    m = _ID.search(url)
    return m.group(1) if m else None


def direct_download_url(url: str) -> str | None:
    file_id = drive_file_id(url)
    if not file_id:
        return None
    return f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"


async def download_drive_file(url: str, limit: int = MAX_BYTES) -> tuple[bytes, str | None]:
    """Скачивает общедоступный файл с Диска. Возвращает (содержимое, имя файла из ответа)."""
    direct = direct_download_url(url)
    if direct is None:
        raise DriveError("не ссылка на Диск")
    timeout = aiohttp.ClientTimeout(total=90)
    async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session, session.get(direct) as resp:
        if resp.status != 200:
            raise DriveError(f"Диск ответил {resp.status}")
        if "text/html" in resp.headers.get("Content-Type", ""):
            raise DriveError("Диск вернул страницу вместо файла (нет общего доступа?)")
        if resp.content_length and resp.content_length > limit:
            raise DriveError("файл слишком большой")
        data = await resp.content.read(limit + 1)
        if len(data) > limit:
            raise DriveError("файл слишком большой")
    name = None
    m = _NAME.search(resp.headers.get("Content-Disposition", ""))
    if m:
        name = unquote(m.group(1))
    return data, name
