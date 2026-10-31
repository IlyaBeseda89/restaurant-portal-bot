"""Рассылка уведомлений по тренингам: кто получает и как отправляется."""

from __future__ import annotations

import logging

from aiogram import Bot

from app.models import Employee, Event
from app.storage.repository import Repository

log = logging.getLogger(__name__)


async def event_audience(repo: Repository, event: Event) -> tuple[list[Employee], list[str]]:
    """Заявитель и участники события, которых бот может найти среди зарегистрированных.

    Второй результат: имена участников, которых бот не нашёл (они не зарегистрированы
    или ФИО в заявке записано иначе), менеджер по обучению может сообщить им сам.
    """
    request = next((r for r in await repo.list_requests() if r.event_id == event.id), None)
    people: dict[str, Employee] = {}
    missing: list[str] = []
    if request is not None:
        applicant = await repo.get_employee(request.applicant_id)
        if applicant and applicant.telegram_id and applicant.active:
            people[applicant.id] = applicant
        found, missing = await repo.match_participants(request.participant_names)
        for e in found:
            people[e.id] = e
    for enrollment in await repo.list_enrollments(event.id):  # записавшиеся сами
        if enrollment.status in {"записан", "был", "не был"}:
            e = await repo.get_employee(enrollment.employee_id)
            if e and e.telegram_id and e.active:
                people[e.id] = e
    return list(people.values()), missing


async def send_to(bot: Bot, employees: list[Employee], text: str, markup=None) -> int:
    """Отправляет каждому в личку. Недоступных (заблокировали бота) пропускает, возвращает число доставленных."""
    sent = 0
    for e in employees:
        if not e.telegram_id:
            continue
        try:
            await bot.send_message(e.telegram_id, text, reply_markup=markup)
            sent += 1
        except Exception:
            log.warning("Не удалось отправить сообщение сотруднику %s", e.id, exc_info=True)
    return sent


async def event_participants(repo: Repository, event: Event) -> tuple[list[Employee], list[str]]:
    """Те, кто должен прийти на тренинг: названные в заявке и записавшиеся. Без заявителя.

    Второй результат: имена из заявки, которых бот не нашёл.
    """
    people: dict[str, Employee] = {}
    missing: list[str] = []
    request = next((r for r in await repo.list_requests() if r.event_id == event.id), None)
    if request is not None:
        found, missing = await repo.match_participants(request.participant_names)
        for e in found:
            people[e.id] = e
    for enrollment in await repo.list_enrollments(event.id):
        if enrollment.status in {"записан", "был", "не был"}:
            e = await repo.get_employee(enrollment.employee_id)
            if e:
                people[e.id] = e
    return sorted(people.values(), key=lambda e: e.full_name), missing
