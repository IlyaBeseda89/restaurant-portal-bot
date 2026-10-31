"""📚 База знаний: категории → материалы (ТЗ, 3.1).

Материалы фильтруются по концепции сотрудника. Открытие материала
записывается в журнал: из него строится статистика «самые открываемые».
"""

from __future__ import annotations

from aiogram import F, Router, html
from aiogram.types import CallbackQuery, Message

from app.handlers.common import Registered
from app.keyboards import BTN_KNOWLEDGE, inline
from app.models import Employee
from app.storage.repository import Repository

router = Router(name="knowledge")
router.message.filter(Registered())
router.callback_query.filter(Registered())

KIND_ICON = {"ссылка": "🔗", "файл": "📎", "статья": "📄"}


async def _categories_view(repo: Repository, employee: Employee) -> tuple[str, object]:
    concept = await repo.concept_of(employee)
    materials = await repo.list_materials(concept)
    used = {m.category_id for m in materials}
    cats = [c for c in await repo.list_categories() if c.id in used]
    if not cats:
        return "📚 В базе знаний пока нет материалов.", None
    rows = [[(c.name, f"kb:cat:{c.id}")] for c in cats]
    return "📚 <b>База знаний</b>\nВыберите раздел:", inline(rows)


@router.message(F.text == BTN_KNOWLEDGE)
async def knowledge(message: Message, repo: Repository, employee: Employee) -> None:
    text, markup = await _categories_view(repo, employee)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "kb:cats")
async def back_to_categories(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    text, markup = await _categories_view(repo, employee)
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data.startswith("kb:cat:"))
async def category(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    category_id = call.data.removeprefix("kb:cat:")
    concept = await repo.concept_of(employee)
    materials = await repo.list_materials(concept, category_id)
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
    concept = await repo.concept_of(employee)
    if m is None or not m.visible_for_concept(concept):
        await call.answer("Материал недоступен или скрыт.", show_alert=True)
        return
    repo.log(employee.id, "просмотр материала", m.id)
    icon = KIND_ICON.get(m.kind.lower(), "🔗")
    if m.url.startswith(("http://", "https://")):
        await call.message.answer(
            f"{icon} <b>{html.quote(m.title)}</b>",
            reply_markup=inline([[("Открыть", m.url)]]),
        )
    else:
        await call.message.answer(f"{icon} <b>{html.quote(m.title)}</b>\n\nСсылка пока не указана.")
    await call.answer()
