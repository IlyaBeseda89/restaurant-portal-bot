"""🌱 Мой старт: чек-лист для новичка (ТЗ, 3.2).

Чек-лист собирается из материалов с отметкой «для_новичков = да» для концепции сотрудника
(и общих). Сотрудник открывает материал, изучает его и отмечает «Изучил(а)»; отметки лежат
на листе «Прогресс». Когда весь чек-лист пройден, менеджеры по обучению получают уведомление.
Приветствие можно задать для каждой концепции: лист «Тексты», ключ «старт_приветствие_<id концепции>».
"""

from __future__ import annotations

import logging
from pathlib import Path

from aiogram import Bot, F, Router, html
from aiogram.types import BufferedInputFile, CallbackQuery, InputMediaPhoto, Message

from app.groups import group_of
from app.handlers.common import HasAccess, Registered
from app.keyboards import BTN_START, inline
from app.models import Employee, Material
from app.notify import send_to
from app.roles import Section
from app.scope import choose, effective_concept, label, picker
from app.storage.repository import Repository
from app.texts import DEFAULTS

log = logging.getLogger(__name__)

KIND = "материал"
GUIDE_DIR = Path(__file__).resolve().parent.parent / "assets" / "guide"
GUIDE_BTN = [("📖 Как пользоваться ботом", "st:guide")]

router = Router(name="start")
router.message.filter(Registered(), HasAccess(Section.ONBOARDING))
router.callback_query.filter(Registered(), HasAccess(Section.ONBOARDING))


async def _checklist(repo: Repository, employee: Employee) -> list[Material]:
    concept = await effective_concept(repo, employee)
    return [m for m in await repo.list_materials(concept, group=group_of(employee)) if m.for_newbies]


def _bar(done: int, total: int) -> str:
    filled = round(10 * done / total) if total else 0
    return "🟩" * filled + "⬜" * (10 - filled)


async def _view(repo: Repository, employee: Employee):
    items = await _checklist(repo, employee)
    concept = await effective_concept(repo, employee)
    greeting = await repo.get_text(f"старт_приветствие_{concept}", "") if concept else ""
    greeting = greeting or await repo.get_text("старт_приветствие", DEFAULTS["старт_приветствие"])
    head = f"🌱 <b>Мой старт</b>\n{html.quote(await label(repo, employee))}\n{html.quote(greeting)}\n"
    if not items:
        return head + "\nЧек-лист пока пуст: материалы для новичков ещё не добавлены.", inline([GUIDE_BTN])
    done_ids = await repo.done_ids(employee.id, KIND)
    done = sum(1 for m in items if m.id in done_ids)
    text = f"{head}\n{_bar(done, len(items))} {done} из {len(items)}"
    rows = [[(f"{'✅' if m.id in done_ids else '⬜'} {m.title[:50]}", f"st:m:{m.id}")] for m in items]
    rows.append(GUIDE_BTN)
    if await picker(repo, employee, "st"):
        rows.append([("🔀 Другая концепция", "st:pick")])
    return text, inline(rows)


@router.message(F.text == BTN_START)
async def open_start(message: Message, repo: Repository, employee: Employee) -> None:
    pick = await picker(repo, employee, "st")
    if pick:  # ТУ, менеджер по обучению, HR: сначала выбирают концепцию
        await message.answer("🌱 <b>Мой старт</b>\n" + pick[0], reply_markup=pick[1])
        return
    text, markup = await _view(repo, employee)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "st:pick")
async def pick_again(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    pick = await picker(repo, employee, "st")
    if pick:
        await call.message.edit_text("🌱 <b>Мой старт</b>\n" + pick[0], reply_markup=pick[1])
    await call.answer()


@router.callback_query(F.data.startswith("sc:st:"))
async def concept_chosen(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    if await choose(repo, employee, call.data.removeprefix("sc:st:")) is None:
        await call.answer("Список концепций изменился. Откройте раздел заново.", show_alert=True)
        return
    text, markup = await _view(repo, employee)
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data == "st:guide")
async def guide(call: CallbackQuery, employee: Employee, repo: Repository) -> None:
    await call.answer()
    files = sorted(GUIDE_DIR.glob("*.png"))
    if not files:
        await call.message.answer("Инструкция пока недоступна.")
        return
    media = [InputMediaPhoto(media=BufferedInputFile(f.read_bytes(), f.name)) for f in files[:10]]
    await call.message.answer_media_group(media)
    repo.log(employee.id, "старт: инструкция")


@router.callback_query(F.data == "st:back")
async def back(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    text, markup = await _view(repo, employee)
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()


async def _item(repo: Repository, employee: Employee, material_id: str) -> Material | None:
    return next((m for m in await _checklist(repo, employee) if m.id == material_id), None)


@router.callback_query(F.data.startswith("st:m:"))
async def open_item(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    m = await _item(repo, employee, call.data.removeprefix("st:m:"))
    if m is None:
        await call.answer("Материал недоступен.", show_alert=True)
        return
    is_done = m.id in await repo.done_ids(employee.id, KIND)
    rows = [[("📖 Открыть материал", f"kb:mat:{m.id}")]]
    if not is_done:
        rows.append([("✅ Изучил(а)", f"st:ok:{m.id}")])
    rows.append([("⬅️ К чек-листу", "st:back")])
    await call.message.edit_text(
        f"{'✅' if is_done else '⬜'} <b>{html.quote(m.title)}</b>\n"
        + ("Вы уже отметили этот материал." if is_done else "Откройте материал, изучите его и нажмите «Изучил(а)»."),
        reply_markup=inline(rows),
    )
    await call.answer()


@router.callback_query(F.data.startswith("st:ok:"))
async def mark_done(call: CallbackQuery, repo: Repository, bot: Bot, employee: Employee) -> None:
    m = await _item(repo, employee, call.data.removeprefix("st:ok:"))
    if m is None:
        await call.answer("Материал недоступен.", show_alert=True)
        return
    if await repo.mark_done(employee.id, KIND, m.id):
        repo.log(employee.id, "старт: изучено", m.id)
        items = await _checklist(repo, employee)
        done_ids = await repo.done_ids(employee.id, KIND)
        if items and all(i.id in done_ids for i in items):
            repo.log(employee.id, "старт: чек-лист пройден")
            await send_to(
                bot, await repo.training_managers(),
                f"🎉 {html.quote(employee.full_name)} прошёл(ла) весь чек-лист «Мой старт» ({len(items)} из {len(items)}).",
            )
            await call.message.answer("🎉 Вы прошли весь чек-лист «Мой старт». Менеджер по обучению уже знает!")
    text, markup = await _view(repo, employee)
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer("Отмечено ✅")
