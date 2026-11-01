"""Кнопки бота. Главное меню собирается по роли сотрудника."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.roles import Role, Section, can

# Тексты кнопок главного меню (ТЗ, раздел 3)
BTN_KNOWLEDGE = "📚 База знаний"
BTN_PRODUCTS = "🍽 Карточки продуктов"
BTN_TRAININGS = "🎓 Тренинги"
BTN_FEEDBACK = "💬 Обратная связь"
BTN_HELP = "❓ Помощь и контакты"
BTN_START = "🌱 Мой старт"
BTN_NEWS = "📰 Новости"
BTN_REQUEST = "📋 Заявка на тренинг"
BTN_REQUESTS_INBOX = "🗂 Заявки"
BTN_SCHEDULE = "🗓 Расписание"
BTN_ADMIN = "⚙️ Админка"
BTN_STATS = "📊 Статистика"
BTN_CANCEL = "✖️ Отмена"

MENU_BUTTONS = {
    BTN_KNOWLEDGE, BTN_PRODUCTS, BTN_TRAININGS, BTN_FEEDBACK, BTN_HELP, BTN_START,
    BTN_REQUEST, BTN_REQUESTS_INBOX, BTN_SCHEDULE, BTN_ADMIN, BTN_STATS, BTN_NEWS,
}


def main_menu(role: Role, is_newbie: bool) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if is_newbie:
        rows.append([BTN_START])
    rows.append([BTN_KNOWLEDGE, BTN_NEWS])
    rows.append([BTN_TRAININGS, BTN_FEEDBACK])

    extra: list[str] = []
    if can(role, Section.TRAINING_REQUEST):
        extra.append(BTN_REQUEST)
    if can(role, Section.REQUESTS_PROCESS):
        extra.append(BTN_REQUESTS_INBOX)
    if can(role, Section.SCHEDULE_EDIT):
        extra.append(BTN_SCHEDULE)
    if can(role, Section.MANAGE_EMPLOYEES) or can(role, Section.MANAGE_CONTENT):
        extra.append(BTN_ADMIN)
    if can(role, Section.STATS):
        extra.append(BTN_STATS)
    for i in range(0, len(extra), 2):
        rows.append(extra[i:i + 2])

    rows.append([BTN_HELP])
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t) for t in row] for row in rows],
        resize_keyboard=True,
        is_persistent=True,
    )


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_CANCEL)]], resize_keyboard=True)


def share_phone_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Отправить мой номер", request_contact=True)],
            [KeyboardButton(text=BTN_CANCEL)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def inline(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    """inline([[('Текст', 'callback_data')], ...]). Если data начинается с http — это ссылка."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=text, url=data) if data.startswith(("http://", "https://"))
            else InlineKeyboardButton(text=text, callback_data=data)
            for text, data in row
        ]
        for row in rows
    ])
