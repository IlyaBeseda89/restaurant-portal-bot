"""➕ Добавление тренинга в расписание прямо из бота (менеджер по обучению и HR).

Шаги: тема (выбрать или создать) → формат (онлайн / офлайн / гибрид) → дата и время →
площадка → ведущий → концепция → число мест → открыть ли запись сразу.
"""

from __future__ import annotations

import logging

from aiogram import F, Router, html
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.formatting import event_card
from app.handlers.common import HasAccess, Registered
from app.handlers.trainings import _manager_buttons
from app.keyboards import cancel_kb, inline, main_menu
from app.models import Employee, parse_datetime
from app.roles import Section
from app.scope import concept_key
from app.storage.repository import Repository

log = logging.getLogger(__name__)

router = Router(name="schedule_add")
router.message.filter(Registered(), HasAccess(Section.SCHEDULE_EDIT))
router.callback_query.filter(Registered(), HasAccess(Section.SCHEDULE_EDIT))

FORMATS = {"online": ("💻 Онлайн", "онлайн"), "offline": ("🏢 Офлайн", "очно"), "hybrid": ("🔀 Гибрид", "гибрид")}


class AddEvent(StatesGroup):
    new_topic = State()
    date = State()
    venue = State()
    host = State()
    capacity = State()


@router.callback_query(F.data == "ev:add")
async def start(call: CallbackQuery, state: FSMContext, repo: Repository) -> None:
    await state.clear()
    rows = [[(t.name[:50], f"ev:t:{t.id}")] for t in await repo.list_topics()]
    rows.append([("➕ Новая тема", "ev:t:new")])
    await call.message.answer("➕ <b>Новый тренинг</b>\nВыберите тему:", reply_markup=inline(rows))
    await call.answer()


async def _ask_format(message: Message) -> None:
    rows = [[(title, f"ev:f:{key}") for key, (title, _) in FORMATS.items()]]
    await message.answer("Формат тренинга?", reply_markup=inline(rows))


@router.callback_query(F.data.startswith("ev:t:"))
async def topic_chosen(call: CallbackQuery, state: FSMContext, repo: Repository) -> None:
    key = call.data.removeprefix("ev:t:")
    if key == "new":
        await state.set_state(AddEvent.new_topic)
        await call.message.answer("Название новой темы?", reply_markup=cancel_kb())
        await call.answer()
        return
    topic = await repo.get_topic(key)
    if topic is None:
        await call.answer("Тема не найдена.", show_alert=True)
        return
    await state.update_data(topic_id=topic.id, topic_name=topic.name)
    await call.message.edit_text(f"Тема: <b>{html.quote(topic.name)}</b>")
    await _ask_format(call.message)
    await call.answer()


@router.message(AddEvent.new_topic, F.text)
async def new_topic(message: Message, state: FSMContext, repo: Repository) -> None:
    name = " ".join(message.text.split())[:100]
    if len(name) < 3:
        await message.answer("Название слишком короткое.")
        return
    topic_id = await repo.add_topic(name)
    await state.update_data(topic_id=topic_id, topic_name=name)
    await state.set_state(None)
    await message.answer(f"Тема «{html.quote(name)}» создана.")
    await _ask_format(message)


@router.callback_query(F.data.startswith("ev:f:"))
async def format_chosen(call: CallbackQuery, state: FSMContext) -> None:
    item = FORMATS.get(call.data.removeprefix("ev:f:"))
    data = await state.get_data()
    if item is None or "topic_id" not in data:
        await call.answer("Начните заново: «🗓 Расписание» → «➕ Добавить тренинг».", show_alert=True)
        return
    await state.update_data(format=item[1])
    await state.set_state(AddEvent.date)
    await call.message.edit_text(f"Формат: {item[0]}")
    await call.message.answer("Дата и время начала, например 15.12.2026 14:00.", reply_markup=cancel_kb())
    await call.answer()


@router.message(AddEvent.date, F.text)
async def got_date(message: Message, state: FSMContext, repo: Repository) -> None:
    start = parse_datetime(message.text.strip())
    if start is None or start < repo.now_local():
        await message.answer("Не понял дату. Формат 15.12.2026 14:00, дата должна быть в будущем.")
        return
    data = await state.get_data()
    await state.update_data(start=start.strftime("%d.%m.%Y %H:%M"))
    if data["format"] == "онлайн":
        await state.update_data(venue="онлайн")
        await state.set_state(AddEvent.host)
        await message.answer("Ведущий? Если пока не назначен, напишите «-».")
        return
    await state.set_state(AddEvent.venue)
    prompt = "Площадка (адрес или ресторан)?" if data["format"] == "очно" else "Площадка для очной части (адрес или ресторан)?"
    await message.answer(prompt + " Если пока не выбрана, напишите «-».")


@router.message(AddEvent.venue, F.text)
async def got_venue(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    await state.update_data(venue="" if text in {"-", "—"} else text[:120])
    await state.set_state(AddEvent.host)
    await message.answer("Ведущий? Если пока не назначен, напишите «-».")


@router.message(AddEvent.host, F.text)
async def got_host(message: Message, state: FSMContext, repo: Repository) -> None:
    text = message.text.strip()
    await state.update_data(host="" if text in {"-", "—"} else text[:100])
    await state.set_state(None)
    concepts = await repo.list_concepts()
    rows = [[("Для всех концепций", "ev:c:all")]]
    rows += [[(c.name or c.id, f"ev:c:{concept_key(c.id)}")] for c in concepts]
    await message.answer("Для какой концепции тренинг?", reply_markup=inline(rows))


@router.callback_query(F.data.startswith("ev:c:"))
async def concept_chosen(call: CallbackQuery, state: FSMContext, repo: Repository) -> None:
    key = call.data.removeprefix("ev:c:")
    mapping = {concept_key(c.id): c.id for c in await repo.list_concepts()}
    if key != "all" and key not in mapping:
        await call.answer("Выберите из списка.", show_alert=True)
        return
    data = await state.get_data()
    if "start" not in data:
        await call.answer("Начните заново: «🗓 Расписание» → «➕ Добавить тренинг».", show_alert=True)
        return
    await state.update_data(concept="" if key == "all" else mapping[key])
    await state.set_state(AddEvent.capacity)
    await call.message.edit_text("Концепция выбрана.")
    await call.message.answer("Сколько мест? «0» значит без ограничения.", reply_markup=cancel_kb())
    await call.answer()


@router.message(AddEvent.capacity, F.text)
async def got_capacity(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not text.isdigit() or int(text) > 500:
        await message.answer("Нужно число от 0 до 500.")
        return
    await state.update_data(capacity=int(text))
    await state.set_state(None)
    await message.answer(
        "Открыть запись сразу? Сотрудники увидят тренинг с кнопкой «Записаться».",
        reply_markup=inline([[("Да, открыть", "ev:o:1"), ("Нет, позже", "ev:o:0")]]),
    )


@router.callback_query(F.data.startswith("ev:o:"))
async def finish(
    call: CallbackQuery, state: FSMContext, repo: Repository, employee: Employee, is_newbie: bool,
) -> None:
    data = await state.get_data()
    if "capacity" not in data:
        await call.answer("Начните заново: «🗓 Расписание» → «➕ Добавить тренинг».", show_alert=True)
        return
    await state.clear()
    start = parse_datetime(data["start"])
    event_id = await repo.add_event(
        data["topic_id"], start, data["format"], data.get("venue", ""), data.get("host", ""),
        capacity=data["capacity"], open_enrollment=call.data.endswith("1"), concept_id=data.get("concept", ""),
    )
    repo.log(employee.id, "тренинг: добавлен", event_id)
    event = await repo.get_event(event_id)
    topic = await repo.get_topic(data["topic_id"])
    await call.message.edit_text("Запись открыта." if event.open else "Запись пока закрыта.")
    await call.message.answer("Тренинг добавлен ✅", reply_markup=main_menu(employee.role, is_newbie))
    await call.message.answer(event_card(event, topic), reply_markup=_manager_buttons(event))
    await call.answer()
