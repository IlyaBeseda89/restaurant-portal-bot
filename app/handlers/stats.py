"""📊 Статистика (ТЗ, 3.5): сводка для ТУ, менеджера по обучению, модератора и HR.

Модератор видит только свою концепцию, остальные роли всю компанию.
Источник: листы «Сотрудники», «Прогресс», «Журнал активности», «Заявки на тренинги», «Обратная связь».
"""

from __future__ import annotations

import logging
from collections import Counter

from aiogram import F, Router, html
from aiogram.types import CallbackQuery, Message

from app.config import Config
from app.groups import group_of
from app.handlers.common import HasAccess, Registered
from app.keyboards import BTN_STATS, inline
from app.models import Employee
from app.roles import Section
from app.storage.repository import Repository

log = logging.getLogger(__name__)

router = Router(name="stats")
router.message.filter(Registered(), HasAccess(Section.STATS))
router.callback_query.filter(Registered(), HasAccess(Section.STATS))

DAYS = 7
FEEDBACK_DAYS = 30
TOP = 5
OPEN_ACTION = "просмотр материала"


async def _scope(repo: Repository, viewer: Employee):
    """(сотрудники в области видимости, id их ресторанов, подпись). None вместо ресторанов: все."""
    concept = await repo.concept_of(viewer)
    employees = [e for e in await repo.list_employees() if e.active]
    if concept is None:
        return employees, None, "вся компания"
    restaurants = {r.id for r in await repo.list_restaurants(active_only=False) if r.concept_id == concept}
    names = {c.id: c.name for c in await repo.list_concepts()}
    return [e for e in employees if e.restaurant_id in restaurants], restaurants, f"концепция {names.get(concept, concept)}"


def _newbies(repo: Repository, config: Config, employees: list[Employee]) -> list[Employee]:
    today = repo.now().date()
    return [e for e in employees if e.is_newbie(today, config.newbie_days)]


async def _checklist_size(repo: Repository, employee: Employee) -> int:
    concept = await repo.concept_of(employee)
    return len([m for m in await repo.list_materials(concept, group=group_of(employee)) if m.for_newbies])


async def _summary(repo: Repository, config: Config, viewer: Employee) -> str:
    employees, restaurants, caption = await _scope(repo, viewer)
    if not employees:
        return f"📊 <b>Статистика</b> ({html.quote(caption)})\n\nСотрудников в этой области пока нет."
    ids = {e.id for e in employees}
    entered = sum(1 for e in employees if e.telegram_id)
    newbies = _newbies(repo, config, employees)
    lines = [
        f"📊 <b>Статистика</b> ({html.quote(caption)})",
        "",
        "👥 <b>Сотрудники</b>",
        f"Активных: {len(employees)}, вошли в бота: {entered}, ещё не заходили: {len(employees) - entered}",
        f"Новичков сейчас: {len(newbies)}",
    ]

    activity = [r for r in await repo.activity_since(DAYS) if r.get("пользователь_id") in ids]
    lines += ["", f"📈 <b>Активность за {DAYS} дн.</b>"]
    if activity:
        users = {r["пользователь_id"] for r in activity}
        lines.append(f"Действий: {len(activity)}, активных сотрудников: {len(users)} из {entered}")
        titles = {m.id: m.title for m in await repo.list_materials(None)}
        top = Counter(r["объект"] for r in activity if r.get("действие") == OPEN_ACTION and r.get("объект"))
        if top:
            lines.append("Чаще открывали:")
            lines += [f"• {html.quote(titles.get(i, 'материал ' + i))}: {n}" for i, n in top.most_common(TOP)]
    else:
        lines.append("Пока нет данных.")

    requests = [r for r in await repo.list_requests() if restaurants is None or r.restaurant_id in restaurants]
    lines += ["", "🎓 <b>Заявки на тренинги</b>"]
    if requests:
        by_status = Counter(r.status for r in requests)
        lines.append(", ".join(f"{status}: {n}" for status, n in by_status.most_common()))
    else:
        lines.append("Заявок нет.")

    events = {e.id: e for e in await repo.list_events() if e.status == "проведён"}
    enrollments = [e for e in await repo.list_enrollments() if e.event_id in events and e.employee_id in ids]
    if events:
        came = [e for e in enrollments if e.status == "был"]
        rated = [e.rating for e in came if e.rating]
        lines.append(f"Проведено тренингов: {len(events)}, посещений: {len(came)}"
                     + (f", средняя оценка {sum(rated) / len(rated):.1f} из 5" if rated else ""))

    feedback = [
        f for f in await repo.feedback_since(FEEDBACK_DAYS)
        if restaurants is None or f.get("ресторан_id", "").strip() in restaurants
    ]
    lines += ["", f"💬 <b>Обратная связь за {FEEDBACK_DAYS} дн.</b>"]
    if feedback:
        by_cat = Counter(f.get("категория", "").strip() or "без категории" for f in feedback)
        lines.append(f"Всего: {len(feedback)}. " + ", ".join(f"{html.quote(c)}: {n}" for c, n in by_cat.most_common()))
    else:
        lines.append("Обращений нет.")
    return "\n".join(lines)


@router.message(F.text == BTN_STATS)
async def open_stats(message: Message, repo: Repository, config: Config, employee: Employee) -> None:
    repo.log(employee.id, "статистика")
    await message.answer(
        await _summary(repo, config, employee),
        reply_markup=inline([[("🌱 Новички и их прогресс", "stt:new")]]),
    )


@router.callback_query(F.data == "stt:new")
async def newbies_view(call: CallbackQuery, repo: Repository, config: Config, employee: Employee) -> None:
    employees, _, caption = await _scope(repo, employee)
    newbies = _newbies(repo, config, employees)
    head = f"🌱 <b>Новички</b> ({html.quote(caption)})\n\n"
    if not newbies:
        text = head + "Сейчас новичков нет."
    else:
        done = await repo.all_progress("материал")
        restaurants = {r.id: r.name for r in await repo.list_restaurants(active_only=False)}
        lines = []
        for e in sorted(newbies, key=lambda x: x.start_date or repo.now().date(), reverse=True)[:20]:
            total = await _checklist_size(repo, e)
            got = len(done.get(e.id, set()))
            progress = f"{min(got, total)} из {total}" if total else "чек-лист пуст"
            lines.append(
                f"• {html.quote(e.full_name)}, {html.quote(restaurants.get(e.restaurant_id, '—'))}: {progress}"
            )
        text = head + "\n".join(lines)
    await call.message.edit_text(text, reply_markup=inline([[("⬅️ К сводке", "stt:back")]]))
    await call.answer()


@router.callback_query(F.data == "stt:back")
async def back(call: CallbackQuery, repo: Repository, config: Config, employee: Employee) -> None:
    await call.message.edit_text(
        await _summary(repo, config, employee),
        reply_markup=inline([[("🌱 Новички и их прогресс", "stt:new")]]),
    )
    await call.answer()
