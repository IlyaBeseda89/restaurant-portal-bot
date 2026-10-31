"""Тексты для тренингов: даты по-русски и карточка события."""

from __future__ import annotations

from datetime import datetime

from aiogram import html

from app.models import Event, Topic

MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
              "сентября", "октября", "ноября", "декабря"]
MONTHS_NOM = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август",
              "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

STATUS_MARK = {"отменён": "❌ отменён", "проведён": "✅ проведён"}


def when(dt: datetime | None) -> str:
    if dt is None:
        return "дата не указана"
    time = "" if (dt.hour, dt.minute) == (0, 0) else f", {dt:%H:%M}"
    return f"{dt.day} {MONTHS_GEN[dt.month - 1]} ({WEEKDAYS[dt.weekday()]}){time}"


def month_title(year: int, month: int) -> str:
    return f"{MONTHS_NOM[month - 1]} {year}"


def event_card(event: Event, topic: Topic | None) -> str:
    title = html.quote(topic.name) if topic else "Тренинг"
    lines = [f"🎓 <b>{title}</b>"]
    if event.status in STATUS_MARK:
        lines.append(STATUS_MARK[event.status])
    lines.append(f"📅 {when(event.start)}")
    place = " · ".join(x for x in (event.format, event.venue) if x)
    if place:
        lines.append(f"📍 {html.quote(place)}")
    if event.host:
        lines.append(f"👤 Ведущий: {html.quote(event.host)}")
    if event.capacity > 0:
        lines.append(f"🪑 Записано {event.enrolled} из {event.capacity}")
    return "\n".join(lines)
