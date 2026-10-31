"""Группы сотрудников для доступа к материалам.

Три уровня, старшие видят всё, что предназначено нижним:
«сотрудники» (все) < «менеджмент» < «руководители».
Материал с группой «менеджмент» видят менеджмент и руководители; материал без группы видят все.
У сотрудника группа берётся из колонки «группа» таблицы «Сотрудники»; если она пуста,
определяется по роли и должности.
"""

from __future__ import annotations

from app.models import Employee
from app.roles import Role

STAFF, MANAGEMENT, LEADERS = "сотрудники", "менеджмент", "руководители"
GROUPS = [STAFF, MANAGEMENT, LEADERS]  # по возрастанию уровня
TITLES = {
    STAFF: "Сотрудники ресторана",
    MANAGEMENT: "Менеджмент",
    LEADERS: "Руководители",
}
SHORT_KEY = {STAFF: "staff", MANAGEMENT: "mgmt", LEADERS: "lead"}
BY_KEY = {v: k for k, v in SHORT_KEY.items()}

_ALIASES = {
    "сотрудники": STAFF, "сотрудник": STAFF, "сотрудники ресторана": STAFF, "staff": STAFF,
    "менеджмент": MANAGEMENT, "менеджеры": MANAGEMENT, "management": MANAGEMENT, "mgmt": MANAGEMENT,
    "руководители": LEADERS, "руководитель": LEADERS, "leaders": LEADERS, "lead": LEADERS,
}

# Роли бота, которые работают сразу со всем: им доступны все материалы
_TOP_ROLES = {Role.DIRECTOR, Role.TU, Role.TRAINING_MANAGER, Role.MODERATOR, Role.HR}
_LEADER_WORDS = ("шеф", "су-шеф", "сушеф", "директор", "территориальный", "управляющий")
_MANAGER_WORDS = ("менеджер", "старший бармен", "старшая", "администратор", "управляющ")


def parse_group(value: str | None) -> str | None:
    """Понимает группу из таблицы. Пусто или непонятное значение: None (тогда по должности)."""
    if not value:
        return None
    return _ALIASES.get(" ".join(value.lower().replace("ё", "е").split()))


def default_group(role: Role, position: str) -> str:
    if role in _TOP_ROLES:
        return LEADERS
    pos = " ".join((position or "").lower().replace("ё", "е").split())
    if any(w in pos for w in _LEADER_WORDS):
        return LEADERS
    if any(w in pos for w in _MANAGER_WORDS):
        return MANAGEMENT
    return STAFF


def group_of(employee: Employee) -> str:
    return parse_group(employee.group) or default_group(employee.role, employee.position)


def level(group: str | None) -> int:
    return GROUPS.index(group) if group in GROUPS else 0


def allows(material_group: str | None, employee_group: str) -> bool:
    """Видит ли сотрудник этой группы материал, предназначенный группе material_group."""
    if not (material_group or "").strip():
        return True
    # Опечатка в таблице не должна открывать материал всем: непонятное значение считаем «руководители»
    wanted = parse_group(material_group) or LEADERS
    return level(employee_group) >= level(wanted)
