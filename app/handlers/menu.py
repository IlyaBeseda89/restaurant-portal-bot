"""Главное меню: помощь, заглушки разделов следующих этапов, ответ незарегистрированным."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import keyboards as kb
from app.handlers.common import Registered
from app.models import Employee
from app.roles import Section, can
from app.storage.repository import Repository
from app.texts import DEFAULTS

router = Router(name="menu")

# Разделы, которые появятся на этапах 2–3 плана (ТЗ, раздел 9)
_LATER = {
    kb.BTN_ADMIN: (Section.MANAGE_CONTENT, "Админка появится на этапе 2. Пока сотрудников и материалы правьте прямо в таблице."),
    kb.BTN_STATS: (Section.STATS, "Статистика и сводные таблицы появятся на этапе 3."),
    kb.BTN_START: (Section.ONBOARDING, "Чек-лист «Мой старт» появится на этапе 3."),
}


@router.message(Registered(), F.text == kb.BTN_HELP)
@router.message(Registered(), Command("help"))
async def help_(message: Message, repo: Repository) -> None:
    await message.answer(await repo.get_text("помощь", DEFAULTS["помощь"]))


@router.message(Registered(), Command("menu"))
async def menu(message: Message, state: FSMContext, employee: Employee, is_newbie: bool) -> None:
    await state.clear()
    await message.answer("Главное меню", reply_markup=kb.main_menu(employee.role, is_newbie))


@router.message(Registered(), F.text.in_(set(_LATER)))
async def later(message: Message, employee: Employee, is_newbie: bool) -> None:
    section, text = _LATER[message.text]
    if not can(employee.role, section, is_newbie=is_newbie):
        await message.answer("Этот раздел вам недоступен.")
        return
    await message.answer(f"🛠 {text}")


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
