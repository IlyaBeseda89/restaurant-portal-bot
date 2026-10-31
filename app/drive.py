"""Ссылки Google Диска: id файла и прямая ссылка на скачивание."""

from __future__ import annotations

import re

_ID = re.compile(r"(?:/file/d/|[?&]id=)([\w-]{10,})")


def drive_file_id(url: str) -> str | None:
    if "drive.google.com" not in url:
        return None
    m = _ID.search(url)
    return m.group(1) if m else None


def direct_download_url(url: str) -> str | None:
    file_id = drive_file_id(url)
    return f"https://drive.google.com/uc?export=download&id={file_id}" if file_id else None
