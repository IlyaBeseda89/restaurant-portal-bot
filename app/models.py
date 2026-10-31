"""Объекты, с которыми работает логика бота. Сами по себе не знают, где лежат данные."""

from __future__ import annotations

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


@dataclass
class Concept:
    id: str
    name: str


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

    def visible_for_concept(self, concept_id: str | None) -> bool:
        cid = self.concept_id.strip().lower()
        if cid in {"", "все", "all", "*"} or concept_id is None:
            return True
        return cid == concept_id.lower()


@dataclass
class Feedback:
    category: str
    restaurant_id: str
    anonymous: bool
    contact: str
    text: str
    has_attachment: bool = False
    id: str = ""
