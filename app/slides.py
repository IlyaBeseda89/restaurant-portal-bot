"""Презентация PDF → картинки-слайды (JPEG), чтобы сотрудник листал их прямо в Telegram."""

from __future__ import annotations

import asyncio

import pymupdf

MAX_PAGES = 60
MAX_WIDTH_PX = 1600
JPEG_QUALITY = 82


def render_pdf(data: bytes, max_pages: int = MAX_PAGES) -> list[bytes]:
    """JPEG каждой страницы. Бросает исключение, если это не PDF или страниц нет."""
    pages: list[bytes] = []
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        if doc.page_count == 0:
            raise ValueError("в PDF нет страниц")
        if doc.page_count > max_pages:
            raise ValueError(f"в PDF {doc.page_count} страниц, больше {max_pages}")
        for page in doc:
            zoom = min(2.0, MAX_WIDTH_PX / max(page.rect.width, 1))
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            pages.append(pix.tobytes("jpg", jpg_quality=JPEG_QUALITY))
    return pages


async def render_pdf_async(data: bytes, max_pages: int = MAX_PAGES) -> list[bytes]:
    """Рендер тяжёлый: уводим в поток, чтобы бот не замирал для остальных."""
    return await asyncio.to_thread(render_pdf, data, max_pages)
