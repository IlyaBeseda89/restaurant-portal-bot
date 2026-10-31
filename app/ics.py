"""Файл календаря .ics для тренингов.

Открывается двойным щелчком в Календаре iPhone/Mac/Google/Outlook и добавляет события.
Живой «подписки» с автообновлением бот дать не может: для неё нужен сайт, а бот его не держит.
Поэтому после изменений в расписании нужно скачать календарь заново.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.models import Event, Topic

DEFAULT_DURATION = timedelta(hours=2)  # в таблице хранится только начало тренинга


def _esc(text: str) -> str:
    return (
        text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
        .replace("\r\n", "\\n").replace("\n", "\\n")
    )


def _fold(line: str, limit: int = 60) -> list[str]:
    """Длинные строки по стандарту переносятся: продолжение начинается с пробела."""
    if len(line) <= limit:
        return [line]
    parts = [line[:limit]]
    rest = line[limit:]
    while rest:
        parts.append(" " + rest[: limit - 1])
        rest = rest[limit - 1:]
    return parts


def _utc(dt: datetime, tz: ZoneInfo) -> str:
    return dt.replace(tzinfo=tz).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def build_ics(items: list[tuple[Event, Topic | None]], tz: ZoneInfo, now: datetime | None = None) -> bytes:
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Restaurant Portal//Trainings//RU",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:Тренинги",
    ]
    for event, topic in items:
        if event.start is None:
            continue
        title = topic.name if topic else "Тренинг"
        where = event.venue or ("онлайн" if event.format == "онлайн" else "")
        desc = [f"Формат: {event.format}"] if event.format else []
        if event.host:
            desc.append(f"Ведущий: {event.host}")
        if topic and topic.description:
            desc.append(topic.description)
        lines += [
            "BEGIN:VEVENT",
            f"UID:training-{event.id}@restaurant-portal",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{_utc(event.start, tz)}",
            f"DTEND:{_utc(event.start + DEFAULT_DURATION, tz)}",
            f"SUMMARY:{_esc(title)}",
        ]
        if where:
            lines.append(f"LOCATION:{_esc(where)}")
        if desc:
            lines.append(f"DESCRIPTION:{_esc(chr(10).join(desc))}")
        if event.status == "отменён":
            lines.append("STATUS:CANCELLED")
        lines += [
            "BEGIN:VALARM", "TRIGGER:-PT1H", "ACTION:DISPLAY", "DESCRIPTION:Скоро тренинг", "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    folded = [part for line in lines for part in _fold(line)]
    return ("\r\n".join(folded) + "\r\n").encode("utf-8")
