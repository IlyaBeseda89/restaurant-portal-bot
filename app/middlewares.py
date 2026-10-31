"""Перед каждым сообщением бот узнаёт, кто пишет, и передаёт это обработчику."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from app.config import Config
from app.keyboards import MENU_BUTTONS
from app.storage.repository import Repository


class EmployeeMiddleware(BaseMiddleware):
    """Кладёт в data: repo, config, employee (или None), is_newbie.

    Уволенный сотрудник (активен = нет) считается незарегистрированным:
    доступ отзывается одной правкой в таблице.
    """

    def __init__(self, repo: Repository, config: Config) -> None:
        self.repo = repo
        self.config = config

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["repo"] = self.repo
        data["config"] = self.config
        user: User | None = data.get("event_from_user")
        employee = None
        if user is not None:
            employee = await self.repo.get_employee_by_telegram(user.id)
            if employee is not None and not employee.active:
                employee = None
        data["employee"] = employee
        data["is_newbie"] = bool(
            employee and employee.is_newbie(self.repo.now().date(), self.config.newbie_days)
        )
        return await handler(event, data)


class MenuResetMiddleware(BaseMiddleware):
    """Нажатие кнопки главного меню прерывает любой начатый диалог.

    Иначе, например, нажатие «📚 База знаний» посреди обратной связи
    ушло бы как текст обращения.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        text = getattr(event, "text", None)
        state = data.get("state")
        if text in MENU_BUTTONS and state is not None and data.get("raw_state") is not None:
            await state.clear()
            data["raw_state"] = None
        return await handler(event, data)
