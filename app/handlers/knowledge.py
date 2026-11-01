"""📚 База знаний: категории → материалы (ТЗ, 3.1).

Материалы фильтруются по концепции сотрудника. Открытие материала
записывается в журнал: из него строится статистика «самые открываемые».
"""

from __future__ import annotations

import logging

from aiogram import F, Router, html
from aiogram.types import BufferedInputFile, CallbackQuery, InputMediaPhoto, Message

from app.drive import direct_download_url, download_drive_file
from app.groups import allows, group_of
from app.handlers.common import Registered
from app.keyboards import BTN_KNOWLEDGE, inline
from app.models import Employee
from app.scope import choose, effective_concept, label, picker
from app.slides import render_pdf_async
from app.storage.repository import Repository

log = logging.getLogger(__name__)

# id материала → file_id в Telegram: повторная отправка мгновенная, без скачивания
_sent_files: dict[str, str] = {}  # исходный файл-документ
_sent_slides: dict[str, list[str]] = {}  # слайды-картинки презентации
ALBUM_SIZE = 10  # больше 10 фото в одном альбоме Telegram не принимает

router = Router(name="knowledge")
router.message.filter(Registered())
router.callback_query.filter(Registered())

KIND_ICON = {"ссылка": "🔗", "файл": "📎", "статья": "📄"}


async def _categories_view(repo: Repository, employee: Employee) -> tuple[str, object]:
    concept = await effective_concept(repo, employee)
    materials = await repo.list_materials(concept, group=group_of(employee))
    used = {m.category_id for m in materials}
    cats = [c for c in await repo.list_categories() if c.id in used]
    head = html.quote(await label(repo, employee))
    rows = [[(c.name, f"kb:cat:{c.id}")] for c in cats]
    # Карточки продуктов живут внутри базы знаний
    if await repo.list_product_categories(concept):
        rows.append([("🍽 Карточки продуктов", "pr:cats")])
    if not rows:
        return f"📚 {head}В базе знаний пока нет материалов.", None
    if await picker(repo, employee, "kb"):
        rows.append([("🔀 Другая концепция", "kb:pick")])
    return f"📚 <b>База знаний</b>\n{head}Выберите раздел:", inline(rows)


@router.message(F.text == BTN_KNOWLEDGE)
async def knowledge(message: Message, repo: Repository, employee: Employee) -> None:
    pick = await picker(repo, employee, "kb")
    if pick:  # ТУ, менеджер по обучению и HR сначала выбирают концепцию
        await message.answer("📚 <b>База знаний</b>\n" + pick[0], reply_markup=pick[1])
        return
    text, markup = await _categories_view(repo, employee)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "kb:pick")
async def pick_again(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    pick = await picker(repo, employee, "kb")
    if pick:
        await call.message.edit_text("📚 <b>База знаний</b>\n" + pick[0], reply_markup=pick[1])
    await call.answer()


@router.callback_query(F.data.startswith("sc:kb:"))
async def concept_chosen(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    if await choose(repo, employee, call.data.removeprefix("sc:kb:")) is None:
        await call.answer("Список концепций изменился. Откройте раздел заново.", show_alert=True)
        return
    text, markup = await _categories_view(repo, employee)
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data == "kb:cats")
async def back_to_categories(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    text, markup = await _categories_view(repo, employee)
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data.startswith("kb:cat:"))
async def category(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    category_id = call.data.removeprefix("kb:cat:")
    concept = await effective_concept(repo, employee)
    materials = await repo.list_materials(concept, category_id, group=group_of(employee))
    cat = next((c for c in await repo.list_categories() if c.id == category_id), None)
    title = html.quote(cat.name) if cat else "Раздел"
    rows = [
        [(f"{KIND_ICON.get(m.kind.lower(), '🔗')} {m.title}{' 🌱' if m.for_newbies else ''}", f"kb:mat:{m.id}")]
        for m in materials
    ]
    rows.append([("⬅️ Ко всем разделам", "kb:cats")])
    note = "\n🌱 — особенно полезно новичкам" if any(m.for_newbies for m in materials) else ""
    text = f"📚 <b>{title}</b>{note}" if materials else f"📚 <b>{title}</b>\nЗдесь пока пусто."
    await call.message.edit_text(text, reply_markup=inline(rows))
    await call.answer()


@router.callback_query(F.data.startswith("kb:mat:"))
async def material(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    material_id = call.data.removeprefix("kb:mat:")
    m = await repo.get_material(material_id)
    concept = await effective_concept(repo, employee)
    if m is None or not m.visible_for_concept(concept) or not allows(m.group, group_of(employee)):
        await call.answer("Материал недоступен или скрыт.", show_alert=True)
        return
    repo.log(employee.id, "просмотр материала", m.id)
    icon = KIND_ICON.get(m.kind.lower(), "🔗")
    if m.kind.lower() == "файл" and direct_download_url(m.url):
        # Файл с Google Диска показываем прямо в чате: сотруднику не нужен вход в Google
        try:
            await _send_drive_material(call, m, icon)
            await call.answer()
            return
        except Exception:
            log.warning("Не удалось отправить файл материала %s, даю ссылку", m.id, exc_info=True)
    if m.url.startswith(("http://", "https://")):
        await call.message.answer(
            f"{icon} <b>{html.quote(m.title)}</b>",
            reply_markup=inline([[("Открыть", m.url)]]),
        )
    else:
        await call.message.answer(f"{icon} <b>{html.quote(m.title)}</b>\n\nСсылка пока не указана.")
    await call.answer()


PDF_BUTTON = "📄 Скачать PDF"


async def _send_slides(message: Message, caption: str, photos: list) -> list[str]:
    """Шлёт слайды альбомами по 10. photos: file_id или BufferedInputFile. Возвращает file_id отправленных."""
    total = len(photos)
    file_ids: list[str] = []
    for start in range(0, total, ALBUM_SIZE):
        chunk = photos[start:start + ALBUM_SIZE]
        cap = caption if total <= ALBUM_SIZE else f"{caption}\nСлайды {start + 1}–{start + len(chunk)} из {total}"
        if len(chunk) == 1:
            sent = [await message.answer_photo(chunk[0], caption=cap)]
        else:
            media = [InputMediaPhoto(media=p, caption=cap if i == 0 else None) for i, p in enumerate(chunk)]
            sent = await message.answer_media_group(media)
        file_ids += [msg.photo[-1].file_id for msg in sent if msg.photo]
    return file_ids


async def _send_drive_material(call: CallbackQuery, m, icon: str) -> None:
    caption = f"{icon} <b>{html.quote(m.title)}</b>"
    pdf_markup = inline([[(PDF_BUTTON, f"kb:pdf:{m.id}")]])
    cached = _sent_slides.get(m.id)
    if cached:
        await _send_slides(call.message, caption, cached)
        await call.message.answer("Это вся презентация.", reply_markup=pdf_markup)
        return
    status = await call.message.answer("⏳ Готовлю слайды, это займёт несколько секунд…")
    try:
        data, name = await download_drive_file(m.url)
        if not data.startswith(b"%PDF"):
            filename = name or m.title
            await call.message.answer_document(BufferedInputFile(data, filename=filename), caption=caption)
            return
        try:
            pages = await render_pdf_async(data)
        except Exception:
            log.warning("Не удалось разбить PDF материала %s на слайды, шлю файлом", m.id, exc_info=True)
            await call.message.answer_document(BufferedInputFile(data, filename=name or f"{m.title}.pdf"), caption=caption)
            return
        photos = [BufferedInputFile(jpg, filename=f"slide-{i}.jpg") for i, jpg in enumerate(pages, 1)]
        ids = await _send_slides(call.message, caption, photos)
        if len(ids) == len(pages):
            _sent_slides[m.id] = ids
        await call.message.answer("Это вся презентация.", reply_markup=pdf_markup)
    finally:
        try:
            await status.delete()
        except Exception:
            log.debug("Не удалось удалить служебное сообщение", exc_info=True)


@router.callback_query(F.data.startswith("kb:pdf:"))
async def material_pdf(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    m = await repo.get_material(call.data.removeprefix("kb:pdf:"))
    concept = await effective_concept(repo, employee)
    if m is None or not m.visible_for_concept(concept) or not allows(m.group, group_of(employee)) \
            or not direct_download_url(m.url):
        await call.answer("Материал недоступен или скрыт.", show_alert=True)
        return
    caption = f"📎 <b>{html.quote(m.title)}</b>"
    cached = _sent_files.get(m.id)
    try:
        if cached:
            await call.message.answer_document(cached, caption=caption)
        else:
            data, name = await download_drive_file(m.url)
            sent = await call.message.answer_document(
                BufferedInputFile(data, filename=name or f"{m.title}.pdf"), caption=caption,
            )
            if sent.document:
                _sent_files[m.id] = sent.document.file_id
    except Exception:
        log.warning("Не удалось отправить PDF материала %s", m.id, exc_info=True)
        await call.message.answer("Не получилось отправить файл. Попробуйте позже.")
    await call.answer()
