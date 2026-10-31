"""Ссылки Google Диска: id файла, прямая ссылка и скачивание файла ботом."""

from __future__ import annotations

import html
import logging
import re
import ssl
from urllib.parse import unquote

import aiohttp
import certifi

log = logging.getLogger(__name__)

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


_FORM_ACTION = re.compile(r'<form[^>]*action="([^"]+)"', re.IGNORECASE)
_FORM_FIELD = re.compile(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', re.IGNORECASE)


def looks_like_html(data: bytes) -> bool:
    """HTML, XML или JSON вместо файла: так Диск отвечает на ошибки и страницы подтверждения."""
    return data[:512].lstrip().lower().startswith((b"<!doctype", b"<html", b"<head", b"<?xml", b"{", b"[", b")]}"))


def parse_confirm_form(html_text: str) -> tuple[str, dict[str, str]] | None:
    """Страница «Диск не может проверить файл на вирусы»: адрес и скрытые поля формы скачивания."""
    action = _FORM_ACTION.search(html_text)
    if not action:
        return None
    fields = dict(_FORM_FIELD.findall(html_text))
    return html.unescape(action.group(1)), {k: html.unescape(v) for k, v in fields.items()}


async def _fetch(session: aiohttp.ClientSession, url: str, params: dict[str, str] | None, limit: int):
    async with session.get(url, params=params) as resp:
        if resp.status != 200:
            raise DriveError(f"Диск ответил {resp.status}")
        if resp.content_length and resp.content_length > limit:
            raise DriveError("файл слишком большой")
        data = await resp.content.read(limit + 1)
        if len(data) > limit:
            raise DriveError("файл слишком большой")
        return data, resp.headers.get("Content-Disposition", "")


async def download_drive_file(url: str, limit: int = MAX_BYTES) -> tuple[bytes, str | None]:
    """Скачивает общедоступный файл с Диска. Возвращает (содержимое, имя файла из ответа).

    Если Диск вместо файла отдаёт HTML-страницу с формой подтверждения, проходит её один раз.
    Если в итоге получилась HTML-страница или пустой файл, бросает DriveError.
    """
    direct = direct_download_url(url)
    if direct is None:
        raise DriveError("не ссылка на Диск")
    timeout = aiohttp.ClientTimeout(total=90)
    # Свои сертификаты (certifi), как у Telegram-клиента: на Mac системных Python их часто нет
    connector = aiohttp.TCPConnector(ssl=ssl.create_default_context(cafile=certifi.where()))
    async with aiohttp.ClientSession(timeout=timeout, connector=connector, trust_env=True) as session:
        data, disposition = await _fetch(session, direct, None, limit)
        if looks_like_html(data):
            form = parse_confirm_form(data.decode("utf-8", "replace"))
            if form is None:
                log.warning("Диск вернул страницу вместо файла: %r", data[:300])
                raise DriveError("Диск вернул страницу вместо файла (нет общего доступа?)")
            action, fields = form
            data, disposition = await _fetch(session, action, fields, limit)
            if looks_like_html(data):
                log.warning("Диск снова вернул страницу вместо файла: %r", data[:300])
                raise DriveError("Диск вернул страницу вместо файла")
    if not data:
        raise DriveError("пустой файл")
    if len(data) < 20_000:
        log.info("Скачан небольшой файл (%d байт), начало: %r", len(data), data[:60])
    name = None
    m = _NAME.search(disposition)
    if m:
        name = unquote(m.group(1))
    return data, name
