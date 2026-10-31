"""🎓 Тренинги для всех и 🗓 Расписание для менеджера по обучению (ТЗ, 3.1 и 3.4).

Расписание живёт в листе «Расписание». Сотрудник видит ближайшие тренинги, может скачать
календарь (.ics) и посмотреть расписание по месяцам. Менеджер по обучению дополнительно
отмечает тренинги проведёнными или отменяет их; дату, площадку и ведущего он правит прямо в таблице.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router, html
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.config import Config
from app.formatting import event_card, month_title, when
from app.handlers.common import HasAccess, Registered
from app.ics import build_ics
from app.keyboards import BTN_SCHEDULE, BTN_TRAININGS, inline
from app.models import Employee, Event
from app.notify import event_audience, send_to
from app.roles import Section
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


async def _main_view(repo: Repository):
    events = (await repo.upcoming_events())[:UPCOMING_LIMIT]
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
    if events:
        rows.append([("📆 Скачать весь календарь (.ics)", "tr:ics:all")])
    rows.append([("🗓 Расписание по месяцам", "tr:months")])
    return text, inline(rows)


@router.message(F.text == BTN_TRAININGS)
async def trainings(message: Message, repo: Repository) -> None:
    text, markup = await _main_view(repo)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "tr:back")
async def back(call: CallbackQuery, repo: Repository) -> None:
    text, markup = await _main_view(repo)
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data.startswith("tr:ics:"))
async def send_ics(call: CallbackQuery, repo: Repository, config: Config, employee: Employee) -> None:
    key = call.data.removeprefix("tr:ics:")
    topics = await _topics_by_id(repo)
    if key == "all":
        events = await repo.upcoming_events()
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
async def months(call: CallbackQuery, repo: Repository) -> None:
    now = repo.now_local()
    found = sorted({(e.start.year, e.start.month) for e in await repo.list_events()
                    if e.start and (e.start.year, e.start.month) >= (now.year, now.month)})
    if not found:
        await call.answer("В расписании пока нет тренингов.", show_alert=True)
        return
    rows = [[(month_title(y, m), f"tr:m:{y}-{m:02d}")] for y, m in found]
    rows.append([("⬅️ Назад", "tr:back")])
    await call.message.edit_text("🗓 <b>Расписание по месяцам</b>", reply_markup=inline(rows))
    await call.answer()


@router.callback_query(F.data.startswith("tr:m:"))
async def month(call: CallbackQuery, repo: Repository) -> None:
    year, mon = (int(x) for x in call.data.removeprefix("tr:m:").split("-"))
    topics = await _topics_by_id(repo)
    events = [e for e in await repo.list_events() if e.start and (e.start.year, e.start.month) == (year, mon)]
    text = f"🗓 <b>{month_title(year, mon)}</b>\n\n" + (
        "\n\n".join(event_card(e, topics.get(e.topic_id)) for e in events) or "Тренингов нет."
    )
    await call.message.edit_text(text[:4000], reply_markup=inline([[("⬅️ К месяцам", "tr:months")]]))
    await call.answer()


# ------------------------------------------------- менеджер по обучению

manager_msg = HasAccess(Section.SCHEDULE_EDIT)


def _manager_buttons(event: Event):
    if not event.active:
        return None
    return inline([[("✅ Проведён", f"sch:done:{event.id}"), ("❌ Отменить", f"sch:cancel:{event.id}")]])


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
    await call.message.edit_text(event_card(event, topic))
    await call.answer("Отмечено ✅")


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
