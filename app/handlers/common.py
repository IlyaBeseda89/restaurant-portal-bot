from __future__ import annotations

from aiogram.filters import Filter
from aiogram.types import TelegramObject

from app.models import Employee
from app.roles import Section, can


class Registered(Filter):
    """Пропускает только зарегистрированных активных сотрудников."""

    async def __call__(self, event: TelegramObject, employee: Employee | None = None) -> bool:
        return employee is not None


class HasAccess(Filter):
    """Пропускает, если роль сотрудника открывает раздел (матрица 2.2)."""

    def __init__(self, section: Section) -> None:
        self.section = section

    async def __call__(
        self, event: TelegramObject, employee: Employee | None = None, is_newbie: bool = False,
    ) -> bool:
        return employee is not None and can(employee.role, self.section, is_newbie=is_newbie)
