"""Объекты, с которыми работает логика бота. Сами по себе не знают, где лежат данные."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from app.roles import Role


def parse_bool(value: str | None, default: bool = True) -> bool:
    """«да / нет» из таблицы. Пустая ячейка = значение по умолчанию."""
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in {"да", "yes", "true", "1", "+", "y", "д"}


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    value = str(value).strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def parse_datetime(value: str | None) -> datetime | None:
    """«15.11.2026 14:00» (или без времени, тогда 00:00). Время локальное, без часового пояса."""
    if not value:
        return None
    value = str(value).strip()
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H.%M", "%Y-%m-%d %H:%M", "%d.%m.%y %H:%M",
                "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def parse_int(value: str | None, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def normalize_name(value: str) -> str:
    """Для сравнения ФИО: без регистра, ё = е, лишние пробелы убраны."""
    return " ".join(value.lower().replace("ё", "е").split())


@dataclass
class Employee:
    id: str
    telegram_id: int | None
    full_name: str
    phone: str
    restaurant_id: str
    position: str
    role: Role
    start_date: date | None
    active: bool
    invite_code: str
    newbie_override: bool | None  # None = считать по дате старта
    all_concepts: bool | None = None  # None = решает роль; True/False = задано в таблице
    group: str = ""  # руководители / менеджмент / сотрудники; пусто = по роли и должности
    trainer: bool = False  # ведёт тренинги: можно назначить ведущим

    def is_newbie(self, today: date, newbie_days: int) -> bool:
        if self.newbie_override is not None:
            return self.newbie_override
        if not self.start_date:
            return False
        return 0 <= (today - self.start_date).days < newbie_days

    @property
    def first_name(self) -> str:
        parts = self.full_name.split()
        return parts[1] if len(parts) > 1 else (parts[0] if parts else "")


COMMON = {"", "все", "all", "*"}


def concept_matches(item_concept: str, employee_concept: str | None) -> bool:
    """Видна ли запись сотруднику.

    - employee_concept = None: сотрудник работает со всеми концепциями (ТУ, HR, менеджер по обучению)
    - employee_concept = "": концепция сотрудника не определена, ему видны только общие записи
    - иначе: общие записи («все» или пусто) и записи его концепции, чужие скрыты
    """
    cid = item_concept.strip().lower()
    if cid in COMMON or employee_concept is None:
        return True
    return cid == employee_concept.strip().lower()


@dataclass
class Concept:
    id: str
    name: str
    moderator_id: str = ""


@dataclass
class Restaurant:
    id: str
    name: str
    concept_id: str
    city: str
    address: str
    active: bool


@dataclass
class Category:
    id: str
    name: str
    order: int


@dataclass
class Material:
    id: str
    category_id: str
    title: str
    kind: str  # ссылка / файл / статья
    url: str
    concept_id: str  # id концепции или «все»
    for_newbies: bool
    order: int
    group: str = ""  # для кого: пусто = всем

    def visible_for_concept(self, concept_id: str | None) -> bool:
        return concept_matches(self.concept_id, concept_id)


@dataclass
class Product:
    id: str
    concept_id: str
    category: str
    name: str
    photo_url: str
    ingredients: str
    allergens: str
    method: str
    pairings: str
    storytelling: str

    def visible_for_concept(self, concept_id: str | None) -> bool:
        return concept_matches(self.concept_id, concept_id)


@dataclass
class Feedback:
    category: str
    restaurant_id: str
    anonymous: bool
    contact: str
    text: str
    has_attachment: bool = False
    id: str = ""


@dataclass
class NewsPost:
    id: str
    date: str
    author_id: str
    author: str
    title: str
    text: str
    concept_id: str  # пусто = для всех концепций
    photo: str = ""
    visible: bool = True
    sent: int = 0
    edited: str = ""  # когда правили после публикации


@dataclass
class Topic:
    id: str
    name: str
    format: str  # офлайн / онлайн / оба
    description: str
    duration: str

    def allows(self, fmt: str) -> bool:
        f = self.format.strip().lower()
        return f in {"", "оба", "обе", "любой"} or f == fmt


@dataclass
class Event:
    id: str
    topic_id: str
    start: datetime | None
    format: str
    venue: str
    host: str
    capacity: int
    enrolled: int
    status: str  # план / подтверждён / проведён / отменён
    reminded: bool = False
    open: bool = False  # открыта самозапись
    concept_id: str = ""  # пусто = всем концепциям

    @property
    def active(self) -> bool:
        return self.status.strip().lower() in {"план", "подтверждён", "подтвержден"}


@dataclass
class TrainingRequest:
    id: str
    created: str
    restaurant_id: str
    applicant_id: str
    topic_id: str
    format: str
    venue: str
    desired_dates: str
    participants: str
    count: int
    status: str  # новая / принята / перенесена / отклонена / проведена
    comment: str = ""
    decided: str = ""
    event_id: str = ""

    @property
    def participant_names(self) -> list[str]:
        """ФИО участников из строк вида «Иванов Иван — официант»."""
        names = []
        for line in self.participants.splitlines():
            name = re.split(r"\s+[—–-]\s+|\s*,\s*", line.strip(), maxsplit=1)[0].strip()
            if name:
                names.append(name)
        return names


@dataclass
class Enrollment:
    id: str
    event_id: str
    employee_id: str
    status: str  # записан / очередь / отменил / был / не был
    created: str = ""
    rating: int = 0

    @property
    def holds_seat(self) -> bool:
        return self.status in {"записан", "был", "не был"}
