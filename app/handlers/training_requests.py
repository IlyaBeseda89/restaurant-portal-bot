"""📋 Заявка на тренинг (директор) и 🗂 Заявки (менеджер по обучению) (ТЗ, сценарии 5.3 и 5.4).

Директор выбирает тему, формат, площадку, желаемые даты и список участников. Менеджер получает
заявку, принимает её (назначает дату, и тренинг попадает в расписание), переносит или отклоняет
с комментарием. Заявитель и участники получают уведомления в бот.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router, html
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.formatting import event_card
from app.handlers.common import HasAccess, Registered
from app.keyboards import BTN_REQUEST, BTN_REQUESTS_INBOX, cancel_kb, inline, main_menu
from app.models import Employee, TrainingRequest, parse_datetime
from app.notify import send_to
from app.roles import Section
from app.storage.repository import Repository

log = logging.getLogger(__name__)

router = Router(name="training_requests")
router.message.filter(Registered())
router.callback_query.filter(Registered())

INBOX_LIMIT = 10
MAX_PARTICIPANTS = 50


class Req(StatesGroup):
    topic = State()
    format = State()
    venue = State()
    dates = State()
    people = State()
    confirm = State()


class Decide(StatesGroup):
    date = State()
    host = State()
    comment = State()


# ------------------------------------------------------------ директор


@router.message(F.text == BTN_REQUEST, HasAccess(Section.TRAINING_REQUEST))
async def start(message: Message, state: FSMContext, repo: Repository) -> None:
    await state.clear()
    topics = await repo.list_topics()
    if not topics:
        await message.answer("Тем тренингов пока нет. Их добавляет менеджер по обучению в таблице «Темы тренингов».")
        return
    await state.set_state(Req.topic)
    await message.answer(
        "📋 <b>Заявка на тренинг</b>\nВыберите тему:",
        reply_markup=inline([[(t.name, f"rq:t:{t.id}")] for t in topics]),
    )


@router.callback_query(Req.topic, F.data.startswith("rq:t:"))
async def choose_topic(call: CallbackQuery, state: FSMContext, repo: Repository) -> None:
    topic = await repo.get_topic(call.data.removeprefix("rq:t:"))
    if topic is None:
        await call.answer("Тема недоступна. Начните заново.", show_alert=True)
        return
    await state.update_data(topic_id=topic.id)
    await call.message.edit_text(f"Тема: <b>{html.quote(topic.name)}</b>")
    formats = [f for f in ("очно", "онлайн") if topic.allows(f)]
    await call.answer()
    if len(formats) == 1:
        await state.update_data(format=formats[0])
        await _ask_venue(call.message, state, formats[0])
        return
    await state.set_state(Req.format)
    await call.message.answer(
        "Какой формат?",
        reply_markup=inline([[("🏢 Очно", "rq:f:очно"), ("💻 Онлайн", "rq:f:онлайн")]]),
    )


async def _ask_venue(message: Message, state: FSMContext, fmt: str) -> None:
    if fmt == "онлайн":
        await state.update_data(venue="онлайн")
        await _ask_dates(message, state)
        return
    await state.set_state(Req.venue)
    await message.answer(
        "Где провести? Напишите ресторан или адрес.",
        reply_markup=cancel_kb(),
    )


async def _ask_dates(message: Message, state: FSMContext) -> None:
    await state.set_state(Req.dates)
    await message.answer(
        "Какие даты вам подходят? Напишите одним сообщением, например: «с 10 по 15 декабря, лучше утром».",
        reply_markup=cancel_kb(),
    )


@router.callback_query(Req.format, F.data.startswith("rq:f:"))
async def choose_format(call: CallbackQuery, state: FSMContext) -> None:
    fmt = call.data.removeprefix("rq:f:")
    if fmt not in ("очно", "онлайн"):
        await call.answer()
        return
    await state.update_data(format=fmt)
    await call.message.edit_text(f"Формат: <b>{fmt}</b>")
    await call.answer()
    await _ask_venue(call.message, state, fmt)


@router.message(Req.venue, F.text)
async def got_venue(message: Message, state: FSMContext) -> None:
    venue = message.text.strip()
    if not venue or len(venue) > 200:
        await message.answer("Напишите, пожалуйста, площадку короче 200 символов.")
        return
    await state.update_data(venue=venue)
    await _ask_dates(message, state)


@router.message(Req.dates, F.text)
async def got_dates(message: Message, state: FSMContext) -> None:
    dates = message.text.strip()
    if not dates or len(dates) > 300:
        await message.answer("Напишите, пожалуйста, даты короче 300 символов.")
        return
    await state.update_data(dates=dates)
    await state.set_state(Req.people)
    await message.answer(
        "Кто пойдёт? Напишите участников, каждого с новой строки, в виде «Иванов Иван — официант».\n"
        "Если они зарегистрированы в боте, им придут напоминания.",
        reply_markup=cancel_kb(),
    )


@router.message(Req.people, F.text)
async def got_people(message: Message, state: FSMContext, repo: Repository) -> None:
    text = message.text.strip()
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    if not lines:
        await message.answer("Напишите хотя бы одного участника.")
        return
    if len(lines) > MAX_PARTICIPANTS or len(text) > 3000:
        await message.answer(f"Слишком длинный список: не больше {MAX_PARTICIPANTS} человек.")
        return
    await state.update_data(people="\n".join(lines), count=len(lines))
    data = await state.get_data()
    topic = await repo.get_topic(data["topic_id"])
    await state.set_state(Req.confirm)
    await message.answer(
        "Проверьте заявку:\n\n"
        f"🎓 <b>{html.quote(topic.name if topic else '')}</b>\n"
        f"📍 {data['format']}, {html.quote(data['venue'])}\n"
        f"📅 {html.quote(data['dates'])}\n"
        f"👥 Участников: {len(lines)}\n{html.quote(chr(10).join(lines))}",
        reply_markup=inline([[("✅ Отправить", "rq:send"), ("✖️ Отменить", "rq:abort")]]),
    )


@router.callback_query(Req.confirm, F.data == "rq:abort")
async def abort(call: CallbackQuery, state: FSMContext, employee: Employee, is_newbie: bool) -> None:
    await state.clear()
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer("Заявка отменена.", reply_markup=main_menu(employee.role, is_newbie))
    await call.answer()


@router.callback_query(Req.confirm, F.data == "rq:send")
async def send(
    call: CallbackQuery, state: FSMContext, repo: Repository, bot: Bot,
    employee: Employee, is_newbie: bool,
) -> None:
    data = await state.get_data()
    await state.clear()
    await call.message.edit_reply_markup(reply_markup=None)
    request_id = await repo.add_request(
        employee.restaurant_id, employee.id, data["topic_id"], data["format"], data["venue"],
        data["dates"], data["people"], data["count"],
    )
    repo.log(employee.id, "заявка на тренинг", request_id)
    request = await repo.get_request(request_id)
    managers = await repo.training_managers()
    if request is not None and managers:
        text, markup = await _request_card(repo, request, with_buttons=True)
        await send_to(bot, managers, "🆕 <b>Новая заявка на тренинг</b>\n\n" + text, markup)
    tail = "" if managers else "\nМенеджер по обучению увидит её в таблице."
    await call.message.answer(
        f"✅ Заявка №{request_id} отправлена. О решении сообщим в боте.{tail}",
        reply_markup=main_menu(employee.role, is_newbie),
    )
    await call.answer()


# ---------------------------------------------------- менеджер: заявки

STATUS_ICON = {"новая": "🆕", "принята": "✅", "перенесена": "🔁", "отклонена": "❌", "проведена": "🏁"}


async def _request_card(repo: Repository, r: TrainingRequest, with_buttons: bool):
    topic = await repo.get_topic(r.topic_id)
    applicant = await repo.get_employee(r.applicant_id)
    restaurant = await repo.get_restaurant(r.restaurant_id) if r.restaurant_id else None
    lines = [
        f"{STATUS_ICON.get(r.status, '•')} <b>Заявка №{html.quote(r.id)}</b>, {html.quote(r.status)}",
        f"🎓 {html.quote(topic.name) if topic else 'тема не найдена'}",
        f"📍 {html.quote(' · '.join(x for x in (r.format, r.venue) if x))}",
        f"📅 Желаемые даты: {html.quote(r.desired_dates)}",
        f"👤 {html.quote(applicant.full_name) if applicant else '—'}"
        + (f", {html.quote(restaurant.name)}" if restaurant else ""),
        f"👥 Участников: {r.count}",
    ]
    if r.participants:
        lines.append(html.quote(r.participants))
    if r.comment:
        lines.append(f"💬 {html.quote(r.comment)}")
    markup = None
    if with_buttons and r.status == "новая":
        markup = inline([
            [("✅ Принять", f"rd:ok:{r.id}")],
            [("🔁 Перенести", f"rd:mv:{r.id}"), ("❌ Отклонить", f"rd:no:{r.id}")],
        ])
    return "\n".join(lines), markup


@router.message(F.text == BTN_REQUESTS_INBOX, HasAccess(Section.REQUESTS_PROCESS))
async def inbox(message: Message, repo: Repository) -> None:
    new = [r for r in await repo.list_requests() if r.status == "новая"]
    if not new:
        await message.answer("🗂 Новых заявок нет.")
        return
    await message.answer(f"🗂 Новых заявок: {len(new)}")
    for r in new[:INBOX_LIMIT]:
        text, markup = await _request_card(repo, r, with_buttons=True)
        await message.answer(text, reply_markup=markup)
    if len(new) > INBOX_LIMIT:
        await message.answer(f"Показаны первые {INBOX_LIMIT}. Остальные появятся после обработки этих.")


async def _open_request(call: CallbackQuery, repo: Repository, request_id: str) -> TrainingRequest | None:
    r = await repo.get_request(request_id)
    if r is None or r.status != "новая":
        await call.answer("Заявка уже обработана.", show_alert=True)
        if call.message:
            await call.message.edit_reply_markup(reply_markup=None)
        return None
    return r


@router.callback_query(F.data.startswith("rd:ok:"), HasAccess(Section.REQUESTS_PROCESS))
async def accept(call: CallbackQuery, state: FSMContext, repo: Repository) -> None:
    r = await _open_request(call, repo, call.data.removeprefix("rd:ok:"))
    if r is None:
        return
    await state.clear()
    await state.set_state(Decide.date)
    await state.update_data(request_id=r.id)
    await call.message.answer(
        f"Заявка №{html.quote(r.id)}: когда проводим? Напишите дату и время в виде <code>15.12.2026 14:00</code>.\n"
        f"Желаемые даты директора: {html.quote(r.desired_dates)}",
        reply_markup=cancel_kb(),
    )
    await call.answer()


@router.message(Decide.date, F.text)
async def got_date(message: Message, state: FSMContext, repo: Repository) -> None:
    start = parse_datetime(message.text)
    if start is None or (start.hour, start.minute) == (0, 0):
        await message.answer("Не понял. Напишите дату и время так: <code>15.12.2026 14:00</code>.")
        return
    if start < repo.now_local():
        await message.answer("Эта дата уже прошла. Напишите будущую дату.")
        return
    await state.update_data(start=start.strftime("%d.%m.%Y %H:%M"))
    await state.set_state(Decide.host)
    await message.answer("Кто ведёт тренинг? Напишите имя или «-», если пока не определено.")


@router.message(Decide.host, F.text)
async def got_host(
    message: Message, state: FSMContext, repo: Repository, bot: Bot,
    employee: Employee, is_newbie: bool,
) -> None:
    data = await state.get_data()
    await state.clear()
    r = await repo.get_request(data["request_id"])
    if r is None or r.status != "новая":
        await message.answer("Заявка уже обработана.", reply_markup=main_menu(employee.role, is_newbie))
        return
    host = message.text.strip()
    host = "" if host == "-" else host[:100]
    start = parse_datetime(data["start"])
    event_id = await repo.add_event(r.topic_id, start, r.format, r.venue, host, enrolled=r.count)
    await repo.update_request(
        r.id, статус="принята", событие_id=event_id, дата_решения=repo.now_local().strftime("%d.%m.%Y %H:%M"),
    )
    repo.log(employee.id, "заявка принята", r.id)
    event = await repo.get_event(event_id)
    topic = await repo.get_topic(r.topic_id)
    applicant = await repo.get_employee(r.applicant_id)
    found, missing = await repo.match_participants(r.participant_names)
    people = {e.id: e for e in found}
    if applicant and applicant.telegram_id:
        people[applicant.id] = applicant
    sent = await send_to(
        bot, list(people.values()),
        "✅ <b>Заявка на тренинг принята</b>\n\n" + event_card(event, topic),
        inline([[("📅 В мой календарь", f"tr:ics:{event_id}")]]),
    )
    note = f"Тренинг добавлен в расписание. Уведомлено: {sent}."
    if missing:
        note += f"\nБот не нашёл: {html.quote(', '.join(missing))}. Сообщите им сами."
    await message.answer(note, reply_markup=main_menu(employee.role, is_newbie))


async def _ask_comment(call: CallbackQuery, state: FSMContext, repo: Repository, prefix: str, verb: str) -> None:
    r = await _open_request(call, repo, call.data.removeprefix(prefix))
    if r is None:
        return
    await state.clear()
    await state.set_state(Decide.comment)
    await state.update_data(request_id=r.id, verdict=verb)
    await call.message.answer(
        f"Заявка №{html.quote(r.id)}: напишите комментарий для директора (например, предложите другие даты).",
        reply_markup=cancel_kb(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("rd:mv:"), HasAccess(Section.REQUESTS_PROCESS))
async def postpone(call: CallbackQuery, state: FSMContext, repo: Repository) -> None:
    await _ask_comment(call, state, repo, "rd:mv:", "перенесена")


@router.callback_query(F.data.startswith("rd:no:"), HasAccess(Section.REQUESTS_PROCESS))
async def decline(call: CallbackQuery, state: FSMContext, repo: Repository) -> None:
    await _ask_comment(call, state, repo, "rd:no:", "отклонена")


@router.message(Decide.comment, F.text)
async def got_comment(
    message: Message, state: FSMContext, repo: Repository, bot: Bot,
    employee: Employee, is_newbie: bool,
) -> None:
    data = await state.get_data()
    await state.clear()
    r = await repo.get_request(data["request_id"])
    if r is None or r.status != "новая":
        await message.answer("Заявка уже обработана.", reply_markup=main_menu(employee.role, is_newbie))
        return
    comment = message.text.strip()[:500]
    verdict = data["verdict"]
    await repo.update_request(
        r.id, статус=verdict, комментарий_менеджера=comment,
        дата_решения=repo.now_local().strftime("%d.%m.%Y %H:%M"),
    )
    repo.log(employee.id, f"заявка {verdict}", r.id)
    topic = await repo.get_topic(r.topic_id)
    applicant = await repo.get_employee(r.applicant_id)
    head = "🔁 Заявка перенесена" if verdict == "перенесена" else "❌ Заявка отклонена"
    sent = 0
    if applicant:
        sent = await send_to(
            bot, [applicant],
            f"{head}\n🎓 {html.quote(topic.name) if topic else ''}\n💬 {html.quote(comment)}",
        )
    note = "Директору отправлено." if sent else "Директору не удалось отправить в бот, сообщите ему сами."
    await message.answer(f"Готово. {note}", reply_markup=main_menu(employee.role, is_newbie))
