"""🎓 Тренинги для всех и 🗓 Расписание для менеджера по обучению (ТЗ, 3.1 и 3.4).

Расписание живёт в листе «Расписание». Сотрудник видит ближайшие тренинги, может скачать
календарь (.ics) и посмотреть расписание по месяцам. Менеджер по обучению дополнительно
отмечает тренинги проведёнными или отменяет их; дату, площадку и ведущего он правит прямо в таблице.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router, html
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.config import Config
from app.formatting import event_card, month_title, when
from app.handlers.common import HasAccess, Registered
from app.ics import build_ics
from app.keyboards import BTN_SCHEDULE, BTN_TRAININGS, cancel_kb, inline, main_menu
from app.models import Employee, Event, concept_matches, parse_datetime
from app.notify import event_audience, event_participants, send_to
from app.roles import Section
from app.scope import concept_key
from app.storage.repository import Repository

log = logging.getLogger(__name__)

router = Router(name="trainings")
router.message.filter(Registered())
router.callback_query.filter(Registered())

UPCOMING_LIMIT = 5
MANAGER_LIMIT = 10


async def _topics_by_id(repo: Repository) -> dict:
    return {t.id: t for t in await repo.list_topics(active_only=False)}


# ---------------------------------------------------------------- для всех


async def _visible(repo: Repository, employee: Employee, events: list[Event]) -> list[Event]:
    """Тренинги своей концепции и общие; ТУ, менеджер по обучению и HR видят все."""
    concept = await repo.concept_of(employee)
    return [e for e in events if concept_matches(e.concept_id or "все", concept)]


async def _main_view(repo: Repository, employee: Employee):
    events = (await _visible(repo, employee, await repo.upcoming_events()))[:UPCOMING_LIMIT]
    topics = await _topics_by_id(repo)
    if not events:
        text = "🎓 <b>Тренинги</b>\n\nБлижайших тренингов в расписании пока нет."
    else:
        text = "🎓 <b>Ближайшие тренинги</b>\n\n" + "\n\n".join(
            event_card(e, topics.get(e.topic_id)) for e in events
        )
    rows = []
    for e in events:
        name = topics[e.topic_id].name if e.topic_id in topics else "Тренинг"
        rows.append([(f"📅 В мой календарь: {name}, {e.start:%d.%m}", f"tr:ics:{e.id}")])
        if e.open:
            mine = await repo.get_enrollment(e.id, employee.id)
            if mine is not None and mine.status in {"записан", "очередь"}:
                label = "✅ Вы записаны" if mine.status == "записан" else "⏳ Вы в очереди"
                rows.append([(f"{label}. Отменить запись, {e.start:%d.%m}", f"tr:un:{e.id}")])
            else:
                full = 0 < e.capacity <= e.enrolled
                rows.append([(f"{'⏳ В очередь' if full else '✍️ Записаться'}: {name}, {e.start:%d.%m}", f"tr:en:{e.id}")])
    if events:
        rows.append([("📆 Скачать весь календарь (.ics)", "tr:ics:all")])
    rows.append([("🗓 Расписание по месяцам", "tr:months")])
    return text, inline(rows)


@router.message(F.text == BTN_TRAININGS)
async def trainings(message: Message, repo: Repository, employee: Employee) -> None:
    text, markup = await _main_view(repo, employee)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "tr:back")
async def back(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    text, markup = await _main_view(repo, employee)
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data.startswith("tr:ics:"))
async def send_ics(call: CallbackQuery, repo: Repository, config: Config, employee: Employee) -> None:
    key = call.data.removeprefix("tr:ics:")
    topics = await _topics_by_id(repo)
    if key == "all":
        events = await _visible(repo, employee, await repo.upcoming_events())
        filename = "trainings.ics"
    else:
        event = await repo.get_event(key)
        events = [event] if event and event.start else []
        filename = f"training-{key}.ics"
    if not events:
        await call.answer("Тренингов для календаря нет.", show_alert=True)
        return
    data = build_ics([(e, topics.get(e.topic_id)) for e in events], repo.tz)
    repo.log(employee.id, "календарь", key)
    await call.message.answer_document(
        BufferedInputFile(data, filename=filename),
        caption="Откройте файл, и тренинги добавятся в ваш календарь. "
        "Если расписание изменится, скачайте календарь заново.",
    )
    await call.answer()


@router.callback_query(F.data == "tr:months")
async def months(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    now = repo.now_local()
    found = sorted({(e.start.year, e.start.month) for e in await _visible(repo, employee, await repo.list_events())
                    if e.start and (e.start.year, e.start.month) >= (now.year, now.month)})
    if not found:
        await call.answer("В расписании пока нет тренингов.", show_alert=True)
        return
    rows = [[(month_title(y, m), f"tr:m:{y}-{m:02d}")] for y, m in found]
    rows.append([("⬅️ Назад", "tr:back")])
    await call.message.edit_text("🗓 <b>Расписание по месяцам</b>", reply_markup=inline(rows))
    await call.answer()


@router.callback_query(F.data.startswith("tr:m:"))
async def month(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    year, mon = (int(x) for x in call.data.removeprefix("tr:m:").split("-"))
    topics = await _topics_by_id(repo)
    events = [e for e in await _visible(repo, employee, await repo.list_events()) if e.start and (e.start.year, e.start.month) == (year, mon)]
    text = f"🗓 <b>{month_title(year, mon)}</b>\n\n" + (
        "\n\n".join(event_card(e, topics.get(e.topic_id)) for e in events) or "Тренингов нет."
    )
    await call.message.edit_text(text[:4000], reply_markup=inline([[("⬅️ К месяцам", "tr:months")]]))
    await call.answer()


# ------------------------------------------------- запись на тренинг


@router.callback_query(F.data.startswith("tr:en:"))
async def enroll(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    event = await repo.get_event(call.data.removeprefix("tr:en:"))
    visible = bool(event and await _visible(repo, employee, [event]))
    if event is None or not event.open or not event.active or not visible \
            or event.start is None or event.start < repo.now_local():
        await call.answer("Запись на этот тренинг закрыта.", show_alert=True)
        return
    result = await repo.enroll(event.id, employee.id)
    repo.log(employee.id, f"тренинг: {result}", event.id)
    notes = {
        "записан": "Вы записаны ✅",
        "очередь": "Мест нет, вы в очереди. Сообщим, если место освободится.",
        "уже": "Вы уже записаны.",
    }
    text, markup = await _main_view(repo, employee)
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer(notes.get(result, "Не удалось записаться."), show_alert=result == "очередь")


@router.callback_query(F.data.startswith("tr:un:"))
async def unenroll(call: CallbackQuery, repo: Repository, bot: Bot, employee: Employee) -> None:
    event = await repo.get_event(call.data.removeprefix("tr:un:"))
    if event is None:
        await call.answer("Тренинг не найден.", show_alert=True)
        return
    promoted = await repo.cancel_enrollment(event.id, employee.id)
    repo.log(employee.id, "тренинг: отмена записи", event.id)
    await _notify_promoted(bot, repo, event, promoted)
    text, markup = await _main_view(repo, employee)
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer("Запись отменена.")


async def _notify_promoted(bot: Bot, repo: Repository, event: Event, promoted: list[str]) -> None:
    if not promoted:
        return
    topic = await repo.get_topic(event.topic_id)
    found = [await repo.get_employee(i) for i in promoted]
    people = [e for e in found if e]
    await send_to(
        bot, people, "🎉 <b>Освободилось место, вы записаны на тренинг</b>\n\n" + event_card(event, topic),
    )


# ------------------------------------------------- менеджер по обучению

manager_msg = HasAccess(Section.SCHEDULE_EDIT)


def _manager_buttons(event: Event):
    if event.status == "проведён":
        return inline([[("📋 Присутствие и оценки", f"sch:att:{event.id}")]])
    if not event.active:
        return None
    return inline([
        [("✏️ Изменить", f"sch:ed:{event.id}"), ("👥 Записанные", f"sch:ls:{event.id}")],
        [("🔒 Закрыть запись" if event.open else "🔓 Открыть запись", f"sch:op:{event.id}")],
        [("✅ Проведён", f"sch:done:{event.id}"), ("❌ Отменить", f"sch:cancel:{event.id}")],
    ])


@router.message(F.text == BTN_SCHEDULE, manager_msg)
async def schedule(message: Message, repo: Repository) -> None:
    now = repo.now_local()
    topics = await _topics_by_id(repo)
    events = [e for e in await repo.list_events() if e.start is None or (now - e.start).days <= 14]
    events = events[:MANAGER_LIMIT]
    if not events:
        await message.answer(
            "🗓 В расписании нет тренингов. Тренинги появляются здесь после принятия заявки, "
            "а также если добавить строку в лист «Расписание»."
        )
        return
    await message.answer(
        "🗓 <b>Расписание</b>\nДату, площадку и ведущего меняйте прямо в таблице, лист «Расписание». "
        "Здесь можно отметить тренинг проведённым или отменить его."
    )
    for e in events:
        await message.answer(event_card(e, topics.get(e.topic_id)), reply_markup=_manager_buttons(e))


async def _event_and_topic(repo: Repository, event_id: str):
    event = await repo.get_event(event_id)
    topic = await repo.get_topic(event.topic_id) if event else None
    return event, topic


@router.callback_query(F.data.startswith("sch:done:"), HasAccess(Section.SCHEDULE_EDIT))
async def mark_done(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    event, topic = await _event_and_topic(repo, call.data.removeprefix("sch:done:"))
    if event is None or not event.active:
        await call.answer("Тренинг уже закрыт или не найден.", show_alert=True)
        return
    await repo.update_event(event.id, статус="проведён")
    request = next((r for r in await repo.list_requests() if r.event_id == event.id), None)
    if request:
        await repo.update_request(request.id, статус="проведена")
    repo.log(employee.id, "тренинг проведён", event.id)
    event.status = "проведён"
    await call.message.edit_text(event_card(event, topic), reply_markup=_manager_buttons(event))
    await call.answer("Отмечено ✅ Теперь можно отметить, кто был на тренинге.")


@router.callback_query(F.data.startswith("sch:cancel:"), HasAccess(Section.SCHEDULE_EDIT))
async def cancel_ask(call: CallbackQuery) -> None:
    event_id = call.data.removeprefix("sch:cancel:")
    await call.message.edit_reply_markup(reply_markup=inline([[
        ("Да, отменить и уведомить", f"sch:cancel!:{event_id}"), ("Нет", f"sch:keep:{event_id}"),
    ]]))
    await call.answer("Участники получат уведомление об отмене.")


@router.callback_query(F.data.startswith("sch:keep:"), HasAccess(Section.SCHEDULE_EDIT))
async def cancel_keep(call: CallbackQuery, repo: Repository) -> None:
    event = await repo.get_event(call.data.removeprefix("sch:keep:"))
    await call.message.edit_reply_markup(reply_markup=_manager_buttons(event) if event else None)
    await call.answer()


@router.callback_query(F.data.startswith("sch:cancel!:"), HasAccess(Section.SCHEDULE_EDIT))
async def cancel_do(call: CallbackQuery, repo: Repository, bot: Bot, employee: Employee) -> None:
    event, topic = await _event_and_topic(repo, call.data.removeprefix("sch:cancel!:"))
    if event is None or not event.active:
        await call.answer("Тренинг уже закрыт или не найден.", show_alert=True)
        return
    await repo.update_event(event.id, статус="отменён")
    audience, missing = await event_audience(repo, event)
    event.status = "отменён"
    name = html.quote(topic.name) if topic else "Тренинг"
    sent = await send_to(
        bot, audience,
        f"❌ <b>Тренинг отменён</b>\n{name}, {when(event.start)}.\nПодробности уточните у менеджера по обучению.",
    )
    repo.log(employee.id, "тренинг отменён", event.id)
    note = f"\nУведомлено: {sent}."
    if missing:
        note += f" Бот не нашёл: {html.quote(', '.join(missing))}. Сообщите им сами."
    await call.message.edit_text(event_card(event, topic) + note)
    await call.answer("Тренинг отменён")


# ------------------------------------------------- менеджер: правка тренинга


class EditEvent(StatesGroup):
    value = State()


FIELDS = {
    "date": ("📅 Дата и время", "Введите новую дату и время, например 15.12.2026 14:00."),
    "venue": ("📍 Площадка", "Введите площадку (адрес или «онлайн»)."),
    "host": ("👤 Ведущий", "Введите ведущего."),
    "cap": ("🪑 Число мест", "Введите число мест. «0» значит без ограничения."),
}


async def _show_card(message: Message, repo: Repository, event_id: str, note: str = "") -> None:
    event, topic = await _event_and_topic(repo, event_id)
    if event is not None:
        await message.answer(note + event_card(event, topic), reply_markup=_manager_buttons(event))


@router.callback_query(F.data.startswith("sch:op:"), HasAccess(Section.SCHEDULE_EDIT))
async def toggle_open(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    event, topic = await _event_and_topic(repo, call.data.removeprefix("sch:op:"))
    if event is None or not event.active:
        await call.answer("Тренинг уже закрыт или не найден.", show_alert=True)
        return
    event.open = not event.open
    await repo.update_event(event.id, запись="да" if event.open else "нет")
    repo.log(employee.id, "тренинг: запись открыта" if event.open else "тренинг: запись закрыта", event.id)
    await call.message.edit_text(event_card(event, topic), reply_markup=_manager_buttons(event))
    await call.answer("Запись открыта: тренинг виден сотрудникам с кнопкой «Записаться»." if event.open
                      else "Запись закрыта.", show_alert=event.open)


@router.callback_query(F.data.startswith("sch:ls:"), HasAccess(Section.SCHEDULE_EDIT))
async def participants(call: CallbackQuery, repo: Repository) -> None:
    event_id = call.data.removeprefix("sch:ls:")
    items = await repo.list_enrollments(event_id)
    names = {e.id: e.full_name for e in await repo.list_employees()}
    rows = {s: [names.get(i.employee_id, i.employee_id) for i in items if i.status == s]
            for s in ("записан", "очередь")}
    lines = [f"👥 <b>Записанные</b> ({len(rows['записан'])})"]
    lines += [f"{n}. {html.quote(x)}" for n, x in enumerate(rows["записан"], 1)] or ["Пока никого."]
    if rows["очередь"]:
        lines += ["", f"⏳ <b>Очередь</b> ({len(rows['очередь'])})"]
        lines += [f"{n}. {html.quote(x)}" for n, x in enumerate(rows["очередь"], 1)]
    await call.message.answer("\n".join(lines))
    await call.answer()


@router.callback_query(F.data.startswith("sch:ed:"), HasAccess(Section.SCHEDULE_EDIT))
async def edit_menu(call: CallbackQuery, repo: Repository) -> None:
    event = await repo.get_event(call.data.removeprefix("sch:ed:"))
    if event is None or not event.active:
        await call.answer("Тренинг уже закрыт или не найден.", show_alert=True)
        return
    rows = [[(title, f"sch:ef:{event.id}:{key}")] for key, (title, _) in FIELDS.items()]
    rows.append([("🏷 Концепция", f"sch:ec:{event.id}")])
    rows.append([("⬅️ Назад", f"sch:keep:{event.id}")])
    await call.message.edit_reply_markup(reply_markup=inline(rows))
    await call.answer()


@router.callback_query(F.data.startswith("sch:ef:"), HasAccess(Section.SCHEDULE_EDIT))
async def edit_field(call: CallbackQuery, state: FSMContext) -> None:
    event_id, _, field = call.data.removeprefix("sch:ef:").partition(":")
    if field not in FIELDS:
        await call.answer()
        return
    await state.clear()
    await state.set_state(EditEvent.value)
    await state.update_data(event_id=event_id, field=field)
    await call.message.answer(FIELDS[field][1], reply_markup=cancel_kb())
    await call.answer()


@router.message(EditEvent.value, F.text, manager_msg)
async def edit_value(
    message: Message, state: FSMContext, repo: Repository, bot: Bot, employee: Employee, is_newbie: bool,
) -> None:
    data = await state.get_data()
    event, topic = await _event_and_topic(repo, data["event_id"])
    if event is None or not event.active:
        await state.clear()
        await message.answer("Тренинг уже закрыт или не найден.", reply_markup=main_menu(employee.role, is_newbie))
        return
    field, text = data["field"], message.text.strip()
    promoted: list[str] = []
    notify = field in {"date", "venue", "host"}
    if field == "date":
        start = parse_datetime(text)
        if start is None or start < repo.now_local():
            await message.answer("Не понял дату. Напишите в формате 15.12.2026 14:00, дата должна быть в будущем.")
            return
        await repo.update_event(event.id, дата_время=start.strftime("%d.%m.%Y %H:%M"), напоминание="")
    elif field == "venue":
        await repo.update_event(event.id, площадка=text[:120])
    elif field == "host":
        await repo.update_event(event.id, ведущий=text[:100])
    else:
        if not text.isdigit() or int(text) > 500:
            await message.answer("Нужно число от 0 до 500.")
            return
        promoted = await repo.set_event_capacity(event.id, int(text))
    await state.clear()
    repo.log(employee.id, f"тренинг: изменено {field}", event.id)
    event, topic = await _event_and_topic(repo, event.id)
    await message.answer("Сохранено ✅", reply_markup=main_menu(employee.role, is_newbie))
    await _show_card(message, repo, event.id)
    if notify:
        audience, _ = await event_audience(repo, event)
        sent = await send_to(bot, audience, "ℹ️ <b>Тренинг изменён</b>\n\n" + event_card(event, topic))
        await message.answer(f"Участникам отправлено уведомление: {sent}.")
    await _notify_promoted(bot, repo, event, promoted)


@router.callback_query(F.data.startswith("sch:ec:"), HasAccess(Section.SCHEDULE_EDIT))
async def edit_concept(call: CallbackQuery, repo: Repository) -> None:
    event_id = call.data.removeprefix("sch:ec:")
    rows = [[("Для всех концепций", f"sch:ecv:{event_id}:all")]]
    rows += [[(c.name or c.id, f"sch:ecv:{event_id}:{concept_key(c.id)}")] for c in await repo.list_concepts()]
    rows.append([("⬅️ Назад", f"sch:ed:{event_id}")])
    await call.message.edit_reply_markup(reply_markup=inline(rows))
    await call.answer()


@router.callback_query(F.data.startswith("sch:ecv:"), HasAccess(Section.SCHEDULE_EDIT))
async def set_concept(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    event_id, _, key = call.data.removeprefix("sch:ecv:").partition(":")
    event, topic = await _event_and_topic(repo, event_id)
    concept = {concept_key(c.id): c.id for c in await repo.list_concepts()}.get(key)
    if event is None or (key != "all" and concept is None):
        await call.answer("Не получилось, откройте расписание заново.", show_alert=True)
        return
    event.concept_id = concept or ""
    await repo.update_event(event.id, концепция_id=event.concept_id)
    repo.log(employee.id, "тренинг: концепция", event.id)
    await call.message.edit_text(event_card(event, topic), reply_markup=_manager_buttons(event))
    await call.answer("Сохранено ✅")


# ------------------------------------------------- присутствие и оценки

MAX_ATTENDEES = 60
MARK = {"был": "✅", "не был": "❌"}


async def _attendance_view(repo: Repository, event: Event):
    topic = await repo.get_topic(event.topic_id)
    people, missing = await event_participants(repo, event)
    status = {e.employee_id: e for e in await repo.list_enrollments(event.id)}
    rows = []
    for person in people[:MAX_ATTENDEES]:
        mark = MARK.get(status[person.id].status if person.id in status else "", "⬜")
        rows.append([(f"{mark} {person.full_name}", f"sch:at:{event.id}:{person.id}")])
    came = [e for e in status.values() if e.status == "был"]
    rated = [e.rating for e in came if e.rating]
    lines = [event_card(event, topic), "", "📋 <b>Присутствие</b>", "Нажмите на имя, чтобы отметить: ⬜ не отмечен, ✅ был, ❌ не был."]
    if not people:
        lines.append("Участников нет: в заявке никого не нашлось и никто не записался.")
    if missing:
        lines.append("Не нашёл в боте: " + html.quote(", ".join(missing)))
    lines.append(f"Были: {len(came)}" + (f". Оценка: {sum(rated) / len(rated):.1f} из 5 ({len(rated)})" if rated else ""))
    if came:
        rows.append([("📨 Запросить оценки", f"sch:rate:{event.id}")])
    return "\n".join(lines), inline(rows) if rows else None


@router.callback_query(F.data.regexp(r"^sch:att:\w+$"), HasAccess(Section.SCHEDULE_EDIT))
async def attendance_open(call: CallbackQuery, repo: Repository) -> None:
    event = await repo.get_event(call.data.removeprefix("sch:att:"))
    if event is None or event.status != "проведён":
        await call.answer("Сначала отметьте тренинг проведённым.", show_alert=True)
        return
    text, markup = await _attendance_view(repo, event)
    await call.message.answer(text, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data.regexp(r"^sch:att:\w+:\w+$"), HasAccess(Section.SCHEDULE_EDIT))
async def attendance_toggle(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    event_id, _, person_id = call.data.removeprefix("sch:att:").partition(":")
    event = await repo.get_event(event_id)
    people, _ = await event_participants(repo, event) if event else ([], [])
    if event is None or event.status != "проведён" or person_id not in {p.id for p in people}:
        await call.answer("Не получилось, откройте список заново.", show_alert=True)
        return
    current = await repo.get_enrollment(event.id, person_id)
    await repo.set_attendance(event.id, person_id, came=not (current and current.status == "был"))
    repo.log(employee.id, "тренинг: присутствие", event.id)
    text, markup = await _attendance_view(repo, event)
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data.startswith("sch:rate:"), HasAccess(Section.SCHEDULE_EDIT))
async def ask_ratings(call: CallbackQuery, repo: Repository, bot: Bot, employee: Employee) -> None:
    event, topic = await _event_and_topic(repo, call.data.removeprefix("sch:rate:"))
    if event is None or event.status != "проведён":
        await call.answer("Тренинг не найден.", show_alert=True)
        return
    asked = 0
    for enrollment in await repo.list_enrollments(event.id):
        if enrollment.status != "был" or enrollment.rating:
            continue
        person = await repo.get_employee(enrollment.employee_id)
        if person is None:
            continue
        name = html.quote(topic.name) if topic else "тренинг"
        asked += await send_to(
            bot, [person], f"⭐ Как вам тренинг «{name}»? Оцените от 1 до 5.",
            inline([[(str(n), f"tr:rt:{event.id}:{n}") for n in range(1, 6)]]),
        )
    repo.log(employee.id, "тренинг: запрос оценок", event.id)
    await call.answer(f"Запрос отправлен: {asked}." if asked else "Всем отмеченным уже отправлено или оценки есть.",
                      show_alert=True)


@router.callback_query(F.data.startswith("tr:rt:"))
async def rate(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    event_id, _, value = call.data.removeprefix("tr:rt:").partition(":")
    ok = value.isdigit() and await repo.set_rating(event_id, employee.id, int(value))
    if not ok:
        await call.answer("Оценить может только участник тренинга.", show_alert=True)
        return
    repo.log(employee.id, "тренинг: оценка", event_id)
    await call.message.edit_text(f"Спасибо за оценку: {value} из 5 ⭐")
    await call.answer()
