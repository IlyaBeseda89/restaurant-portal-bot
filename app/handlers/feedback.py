"""💬 Обратная связь (ТЗ, сценарий 5.2).

Анонимность: при анонимной отправке telegram_id и ФИО не сохраняются нигде,
ни в таблице, ни в журнале активности, ни в карточке для служебного чата.

Ресторан подставляется из профиля всегда, в том числе для анонимных
обращений, чтобы у каждого отзыва была точка. Видят его только получатели
служебного чата (ТУ и собственник) и таблица. Если у сотрудника нет
ресторана (офис, HR), он выбирает его кнопками, пропустить шаг нельзя.
"""

from __future__ import annotations

import logging
import re

from aiogram import Bot, F, Router, html
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.config import Config
from app.handlers.common import Registered
from app.keyboards import BTN_FEEDBACK, cancel_kb, inline, main_menu
from app.models import Employee, Feedback
from app.storage.repository import Repository

log = logging.getLogger(__name__)

router = Router(name="feedback")
router.message.filter(Registered())
router.callback_query.filter(Registered())

# Отдельный роутер для кнопок статуса в служебном чате (там пишут ТУ и собственник)
chat_router = Router(name="feedback_chat")

CATEGORIES = {"wish": "пожелание", "idea": "идея", "crit": "критика"}
STATUSES = {"n": "новое", "w": "в работе", "c": "закрыто"}


class Fb(StatesGroup):
    category = State()
    text = State()
    mode = State()
    contact = State()
    restaurant = State()


def hashtag(value: str) -> str:
    tag = re.sub(r"\W+", "_", value, flags=re.UNICODE).strip("_")
    return f"#{tag}" if tag else ""


@router.message(F.text == BTN_FEEDBACK)
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Fb.category)
    await message.answer(
        "💬 <b>Обратная связь</b>\nЧто вы хотите отправить?",
        reply_markup=inline([
            [("🙏 Пожелание", "fb:cat:wish"), ("💡 Идея", "fb:cat:idea")],
            [("🗣 Критика", "fb:cat:crit")],
        ]),
    )


@router.callback_query(Fb.category, F.data.startswith("fb:cat:"))
async def choose_category(call: CallbackQuery, state: FSMContext) -> None:
    category = CATEGORIES.get(call.data.removeprefix("fb:cat:"))
    if category is None:
        await call.answer()
        return
    await state.update_data(category=category)
    await state.set_state(Fb.text)
    await call.message.edit_text(f"💬 Категория: <b>{category}</b>")
    await call.message.answer(
        "Напишите сообщение одним текстом. Можно приложить фото или файл с подписью.",
        reply_markup=cancel_kb(),
    )
    await call.answer()


@router.message(Fb.text, F.text | F.photo | F.document)
async def got_text(message: Message, state: FSMContext) -> None:
    text = (message.text or message.caption or "").strip()
    has_media = bool(message.photo or message.document)
    if not text and not has_media:
        await message.answer("Пустое сообщение. Напишите, пожалуйста, текст.")
        return
    if len(text) > 3500:
        await message.answer("Слишком длинно для одного обращения: сократите, пожалуйста, до 3500 символов.")
        return
    await state.update_data(
        text=text,
        media_chat_id=message.chat.id if has_media else None,
        media_message_id=message.message_id if has_media else None,
    )
    await state.set_state(Fb.mode)
    await message.answer(
        "Как отправить?\n\n"
        "🕶 <b>Анонимно</b>: мы не сохраним, кто вы, и ответить вам через бота будет невозможно.\n"
        "📇 <b>С контактом</b>: с вами смогут связаться.",
        reply_markup=inline([[("🕶 Анонимно", "fb:mode:anon"), ("📇 Оставить контакт", "fb:mode:contact")]]),
    )


@router.callback_query(Fb.mode, F.data.startswith("fb:mode:"))
async def choose_mode(
    call: CallbackQuery, state: FSMContext, repo: Repository, employee: Employee,
    bot: Bot, config: Config, is_newbie: bool,
) -> None:
    await call.message.edit_reply_markup(reply_markup=None)
    if call.data == "fb:mode:anon":
        await state.update_data(anonymous=True, contact="")
        await call.answer()
        await resolve_restaurant(call.message, state, repo, employee, bot, config, is_newbie)
        return
    else:
        await state.update_data(anonymous=False)
        await state.set_state(Fb.contact)
        options = []
        if call.from_user.username:
            options.append((f"@{call.from_user.username}", "fb:contact:username"))
        if employee.phone:
            options.append((employee.phone, "fb:contact:phone"))
        await call.message.answer(
            "Как с вами связаться? Напишите телефон или @username"
            + (", или выберите кнопкой:" if options else "."),
            reply_markup=inline([options]) if options else None,
        )
    await call.answer()


@router.callback_query(Fb.contact, F.data.startswith("fb:contact:"))
async def contact_button(
    call: CallbackQuery, state: FSMContext, repo: Repository, employee: Employee,
    bot: Bot, config: Config, is_newbie: bool,
) -> None:
    if call.data == "fb:contact:username" and call.from_user.username:
        contact = f"@{call.from_user.username}"
    else:
        contact = employee.phone
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer()
    await after_contact(call.message, state, repo, employee, bot, config, is_newbie, contact)


@router.message(Fb.contact, F.text)
async def contact_text(
    message: Message, state: FSMContext, repo: Repository, employee: Employee,
    bot: Bot, config: Config, is_newbie: bool,
) -> None:
    contact = message.text.strip()[:100]
    await after_contact(message, state, repo, employee, bot, config, is_newbie, contact)


async def after_contact(
    message: Message, state: FSMContext, repo: Repository, employee: Employee,
    bot: Bot, config: Config, is_newbie: bool, contact: str,
) -> None:
    contact = f"{employee.full_name}, {contact}"
    await state.update_data(contact=contact)
    await resolve_restaurant(message, state, repo, employee, bot, config, is_newbie)


async def resolve_restaurant(
    message: Message, state: FSMContext, repo: Repository, employee: Employee,
    bot: Bot, config: Config, is_newbie: bool,
) -> None:
    """Ресторан из профиля; если его нет — обязательный выбор кнопками."""
    if employee.restaurant_id:
        await state.update_data(restaurant_id=employee.restaurant_id)
        await finish(message, state, repo, employee, bot, config, is_newbie)
        return
    await state.set_state(Fb.restaurant)
    restaurants = await repo.list_restaurants()
    rows = [[(r.name, f"fb:rest:{r.id}")] for r in restaurants]
    await message.answer("К какому ресторану относится обращение?", reply_markup=inline(rows))


@router.callback_query(Fb.restaurant, F.data.startswith("fb:rest:"))
async def choose_restaurant(
    call: CallbackQuery, state: FSMContext, repo: Repository, employee: Employee,
    bot: Bot, config: Config, is_newbie: bool,
) -> None:
    rid = call.data.removeprefix("fb:rest:")
    if await repo.get_restaurant(rid) is None:
        await call.answer("Выберите ресторан из списка.", show_alert=True)
        return
    await state.update_data(restaurant_id=rid)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer()
    await finish(call.message, state, repo, employee, bot, config, is_newbie)


async def finish(
    message: Message, state: FSMContext, repo: Repository, employee: Employee,
    bot: Bot, config: Config, is_newbie: bool,
) -> None:
    data = await state.get_data()
    await state.clear()
    fb = Feedback(
        category=data["category"],
        restaurant_id=data.get("restaurant_id", ""),
        anonymous=data["anonymous"],
        contact=data.get("contact", ""),
        text=data.get("text", ""),
        has_attachment=bool(data.get("media_message_id")),
    )
    fb_id = await repo.add_feedback(fb)
    if not fb.anonymous:
        repo.log(employee.id, "обратная связь", fb_id)

    await send_card(bot, config, repo, fb, data.get("media_chat_id"), data.get("media_message_id"))
    await message.answer(
        f"✅ Спасибо! Обращение <b>№{fb_id}</b> принято.",
        reply_markup=main_menu(employee.role, is_newbie),
    )


def card_text(fb: Feedback, restaurant_name: str, status: str, place: str = "") -> str:
    tags = " ".join(t for t in (hashtag(fb.category), hashtag(restaurant_name)) if t)
    author = "🕶 анонимно" if fb.anonymous else f"📇 {html.quote(fb.contact)}"
    body = html.quote(fb.text) if fb.text else "<i>(без текста, см. вложение)</i>"
    where = f"📍 {html.quote(restaurant_name)}" + (f", {html.quote(place)}" if place else "")
    return (
        f"💬 <b>Обращение №{fb.id}</b>\n{tags}\n"
        + (f"{where}\n" if restaurant_name else "")
        + f"\n{body}\n\n"
        f"Автор: {author}\nСтатус: <b>{status}</b>"
    )


def status_kb(fb_id: str):
    return inline([[(f"• {name}", f"fbst:{fb_id}:{code}") for code, name in STATUSES.items()]])


async def send_card(
    bot: Bot, config: Config, repo: Repository, fb: Feedback,
    media_chat_id: int | None, media_message_id: int | None,
) -> None:
    if config.feedback_chat_id is None:
        log.warning("FEEDBACK_CHAT_ID не задан, обращение №%s сохранено только в таблице", fb.id)
        return
    restaurant = await repo.get_restaurant(fb.restaurant_id) if fb.restaurant_id else None
    try:
        card = await bot.send_message(
            config.feedback_chat_id,
            card_text(
                fb, restaurant.name if restaurant else "", "новое",
                ", ".join(x for x in (restaurant.city, restaurant.address) if x) if restaurant else "",
            ),
            reply_markup=status_kb(fb.id),
        )
        if media_chat_id and media_message_id:
            # copy_message не показывает, от кого вложение
            await bot.copy_message(
                config.feedback_chat_id, media_chat_id, media_message_id,
                reply_to_message_id=card.message_id,
            )
    except Exception:
        log.exception("Не удалось отправить обращение №%s в служебный чат", fb.id)


@chat_router.callback_query(F.data.startswith("fbst:"))
async def set_status(call: CallbackQuery, repo: Repository, config: Config) -> None:
    if config.feedback_chat_id is None or call.message.chat.id != config.feedback_chat_id:
        await call.answer("Статус меняется только в служебном чате.", show_alert=True)
        return
    _, fb_id, code = call.data.split(":", 2)
    status = STATUSES.get(code)
    if status is None:
        await call.answer()
        return
    await repo.set_feedback_status(fb_id, status)
    old = call.message.html_text or ""
    new = re.sub(r"Статус: <b>.*?</b>", f"Статус: <b>{status}</b>", old)
    if new != old:
        await call.message.edit_text(new, reply_markup=status_kb(fb_id))
    await call.answer(f"Статус: {status}")
