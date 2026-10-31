"""Главное меню: помощь, ответ на непонятные сообщения и незарегистрированным."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import keyboards as kb
from app.handlers.common import Registered
from app.models import Employee
from app.storage.repository import Repository
from app.texts import DEFAULTS

router = Router(name="menu")


@router.message(Registered(), F.text == kb.BTN_HELP)
@router.message(Registered(), Command("help"))
async def help_(message: Message, repo: Repository) -> None:
    await message.answer(await repo.get_text("помощь", DEFAULTS["помощь"]))


@router.message(Registered(), Command("menu"))
async def menu(message: Message, state: FSMContext, employee: Employee, is_newbie: bool) -> None:
    await state.clear()
    await message.answer("Главное меню", reply_markup=kb.main_menu(employee.role, is_newbie))


@router.message(Command("id"))
async def chat_id(message: Message) -> None:
    """Подсказка при настройке: узнать id чата для FEEDBACK_CHAT_ID / HR_CHAT_ID."""
    await message.answer(f"id этого чата: <code>{message.chat.id}</code>")


@router.message(Registered())
async def unknown(message: Message, employee: Employee, is_newbie: bool) -> None:
    await message.answer(
        "Не понял команду. Пользуйтесь кнопками меню.",
        reply_markup=kb.main_menu(employee.role, is_newbie),
    )


@router.message(F.chat.type == "private")
async def not_registered(message: Message, repo: Repository) -> None:
    await message.answer(await repo.get_text("нет_доступа", DEFAULTS["нет_доступа"]))


@router.callback_query()
async def stale_callback(call: CallbackQuery) -> None:
    await call.answer("Кнопка устарела. Откройте раздел из меню заново.", show_alert=False)
