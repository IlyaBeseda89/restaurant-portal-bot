"""Напоминания о тренингах: участникам уходит сообщение за сутки до начала."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from aiogram import Bot

from app.formatting import event_card
from app.keyboards import inline
from app.notify import event_audience, send_to
from app.storage.repository import Repository

log = logging.getLogger(__name__)

REMIND_BEFORE = timedelta(hours=24)
CHECK_EVERY = 600  # секунд


async def send_due_reminders(bot: Bot, repo: Repository) -> int:
    """Отправляет напоминания о тренингах, до которых осталось не больше суток. Возвращает число тренингов."""
    now = repo.now_local()
    done = 0
    for event in await repo.list_events():
        if event.reminded or not event.active or event.start is None:
            continue
        if not (timedelta(0) < event.start - now <= REMIND_BEFORE):
            continue
        topic = await repo.get_topic(event.topic_id)
        audience, _ = await event_audience(repo, event)
        # Помечаем до отправки: лучше пропустить напоминание, чем разослать его дважды
        await repo.update_event(event.id, напоминание="да")
        await send_to(
            bot, audience, "⏰ <b>Напоминание: тренинг завтра</b>\n\n" + event_card(event, topic),
            inline([[("📅 В мой календарь", f"tr:ics:{event.id}")]]),
        )
        done += 1
    return done


async def remind_forever(bot: Bot, repo: Repository) -> None:
    while True:
        try:
            await send_due_reminders(bot, repo)
        except Exception:
            log.exception("Ошибка при рассылке напоминаний")
        await asyncio.sleep(CHECK_EVERY)
