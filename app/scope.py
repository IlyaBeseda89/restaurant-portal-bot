"""Какую концепцию сейчас видит сотрудник.

Обычный сотрудник и директор видят свою концепцию (по ресторану) плюс общие материалы.
ТУ, менеджер по обучению и HR работают со всеми концепциями: перед разделами
«База знаний» и «Карточки продуктов» им предлагается выбрать концепцию.
Выбор помнится, пока бот не перезапущен.
"""

from __future__ import annotations

import hashlib

from app.keyboards import inline
from app.models import Concept, Employee
from app.storage.repository import Repository

# id сотрудника → id выбранной концепции
_VIEW: dict[str, str] = {}


def concept_key(concept_id: str) -> str:
    return hashlib.sha1(concept_id.encode()).hexdigest()[:6]


async def is_cross_concept(repo: Repository, employee: Employee) -> bool:
    return await repo.concept_of(employee) is None


async def effective_concept(repo: Repository, employee: Employee) -> str | None:
    """Концепция, по которой фильтруется контент прямо сейчас."""
    base = await repo.concept_of(employee)
    if base is not None:
        return base
    return _VIEW.get(employee.id)  # None, пока не выбрана


async def picker(repo: Repository, employee: Employee, section: str):
    """Кнопки выбора концепции для тех, кто работает со всеми. None, если выбирать нечего."""
    if not await is_cross_concept(repo, employee):
        return None
    concepts = await repo.list_concepts()
    if not concepts:
        return None
    rows = [[(c.name or c.id, f"sc:{section}:{concept_key(c.id)}")] for c in concepts]
    return "Выберите концепцию:", inline(rows)


async def choose(repo: Repository, employee: Employee, key: str) -> Concept | None:
    for c in await repo.list_concepts():
        if concept_key(c.id) == key:
            _VIEW[employee.id] = c.id
            return c
    return None


async def label(repo: Repository, employee: Employee) -> str:
    """Строка «Концепция: …» для тех, кто работает со всеми концепциями."""
    if not await is_cross_concept(repo, employee):
        return ""
    chosen = _VIEW.get(employee.id)
    if not chosen:
        return ""
    for c in await repo.list_concepts():
        if c.id == chosen:
            return f"Концепция: {c.name or c.id}\n"
    return ""


def reset() -> None:
    _VIEW.clear()
