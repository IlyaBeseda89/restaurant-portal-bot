"""Регистрация по персональной ссылке (ТЗ, сценарий 5.1).

Ссылка: t.me/<бот>?start=<роль>_<код>. Роль в ссылке — подсказка,
источник правды — строка сотрудника в таблице «Сотрудники».
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram import Bot, F, Router, html
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from app.config import Config
from app.keyboards import BTN_CANCEL, inline, main_menu, share_phone_kb
from app.models import Employee, normalize_name
from app.roles import Role
from app.storage.repository import Repository
from app.texts import DEFAULTS

log = logging.getLogger(__name__)
router = Router(name="registration")


class Reg(StatesGroup):
    name = State()
    phone = State()
    confirm = State()


@dataclass
class Invite:
    role: Role | None
    code: str


def parse_invite(payload: str | None) -> Invite | None:
    """'director_AB12CD' → Invite(DIRECTOR, 'AB12CD'). Без роли: 'AB12CD' → Invite(None, ...)."""
    if not payload:
        return None
    payload = payload.strip()
    if "_" in payload:
        role_part, code = payload.split("_", 1)
        role = Role.parse(role_part)
        if role is not None:
            return Invite(role=role, code=code)
    return Invite(role=None, code=payload)


@dataclass
class MatchResult:
    employee: Employee | None
    problem: str = ""  # почему не нашли — уходит HR


async def match_employee(repo: Repository, invite: Invite, full_name: str, telegram_id: int) -> MatchResult:
    """Сверка с таблицей «Сотрудники»: сначала по коду из ссылки, потом по ФИО."""
    by_code = await repo.get_employee_by_code(invite.code)
    if by_code is not None:
        if not by_code.active:
            return MatchResult(None, "сотрудник с этим кодом отмечен как неактивный")
        if by_code.telegram_id and by_code.telegram_id != telegram_id:
            return MatchResult(None, "по этой ссылке уже зарегистрирован другой Telegram-аккаунт")
        if normalize_name(by_code.full_name) != normalize_name(full_name):
            return MatchResult(None, f"ФИО не совпадает с таблицей (там: {by_code.full_name})")
        return MatchResult(by_code)

    candidates = await repo.find_unbound_by_name(full_name)
    if invite.role is not None:
        candidates = [c for c in candidates if c.role == invite.role]
    if len(candidates) == 1:
        return MatchResult(candidates[0])
    if len(candidates) > 1:
        return MatchResult(None, "в таблице несколько сотрудников с таким ФИО")
    return MatchResult(None, "сотрудник не найден в таблице")


async def show_main_menu(message: Message, repo: Repository, employee: Employee, is_newbie: bool) -> None:
    key = "приветствие_новичка" if is_newbie else "приветствие"
    text = (await repo.get_text(key, DEFAULTS[key])).replace("{name}", html.quote(employee.first_name))
    await message.answer(text, reply_markup=main_menu(employee.role, is_newbie))


@router.message(CommandStart())
async def cmd_start(
    message: Message, command: CommandObject, state: FSMContext,
    repo: Repository, employee: Employee | None, is_newbie: bool,
) -> None:
    await state.clear()
    if employee is not None:
        await show_main_menu(message, repo, employee, is_newbie)
        return

    invite = parse_invite(command.args)
    if invite is None:
        await message.answer(await repo.get_text("нет_доступа", DEFAULTS["нет_доступа"]))
        return

    await state.update_data(invite_role=invite.role.value if invite.role else "", invite_code=invite.code)
    await state.set_state(Reg.name)
    await message.answer(
        "Здравствуйте! Давайте познакомимся.\n\n"
        "Напишите, пожалуйста, ваши <b>фамилию, имя и отчество</b> полностью, "
        "как в трудовом договоре.",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(F.text == BTN_CANCEL)
async def cancel_any(message: Message, state: FSMContext, employee: Employee | None, is_newbie: bool) -> None:
    await state.clear()
    if employee is not None:
        await message.answer("Отменено.", reply_markup=main_menu(employee.role, is_newbie))
    else:
        await message.answer(
            "Регистрация отменена. Чтобы начать заново, снова откройте пригласительную ссылку.",
            reply_markup=ReplyKeyboardRemove(),
        )


@router.message(Reg.name, F.text)
async def reg_name(message: Message, state: FSMContext) -> None:
    name = " ".join(message.text.split())
    if len(name.split()) < 2 or len(name) > 120:
        await message.answer("Пожалуйста, напишите фамилию и имя (и отчество, если есть) одним сообщением.")
        return
    await state.update_data(full_name=name)
    await state.set_state(Reg.phone)
    await message.answer(
        "Спасибо! Теперь отправьте номер телефона: нажмите кнопку ниже или напишите его.",
        reply_markup=share_phone_kb(),
    )


@router.message(Reg.phone, F.contact | F.text)
async def reg_phone(
    message: Message, state: FSMContext, repo: Repository, config: Config, bot: Bot,
) -> None:
    if message.contact:
        if message.contact.user_id and message.contact.user_id != message.from_user.id:
            await message.answer("Пожалуйста, отправьте свой собственный номер.")
            return
        phone = message.contact.phone_number
    else:
        phone = message.text.strip()
        digits = "".join(ch for ch in phone if ch.isdigit())
        if not 10 <= len(digits) <= 15:
            await message.answer("Не похоже на номер телефона. Попробуйте ещё раз, например +7 999 123-45-67.")
            return
    if not phone.startswith("+"):
        phone = "+" + "".join(ch for ch in phone if ch.isdigit())
    await state.update_data(phone=phone)

    data = await state.get_data()
    invite = Invite(role=Role.parse(data.get("invite_role")), code=data.get("invite_code", ""))
    result = await match_employee(repo, invite, data["full_name"], message.from_user.id)

    if result.employee is None:
        await state.clear()
        await notify_hr_unknown(bot, config, message, data["full_name"], phone, invite, result.problem)
        await message.answer(
            "Не нашёл вас в списке сотрудников. Я передал заявку HR: после проверки "
            "вам пришлют новую ссылку или подтвердят доступ.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    emp = result.employee
    await state.update_data(employee_id=emp.id)
    await state.set_state(Reg.confirm)
    restaurant = await repo.get_restaurant(emp.restaurant_id) if emp.restaurant_id else None
    where = html.quote(restaurant.name) if restaurant else "не указан"
    await message.answer("Нашёл вас в списке ✅", reply_markup=ReplyKeyboardRemove())
    await message.answer(
        f"<b>{html.quote(emp.full_name)}</b>\n"
        f"Ресторан: {where}\n"
        f"Должность: {html.quote(emp.position or '—')}\n\n"
        "Всё верно?",
        reply_markup=inline([[("✅ Да, всё верно", "reg:yes"), ("❌ Нет, ошибка", "reg:no")]]),
    )


@router.callback_query(Reg.confirm, F.data.in_({"reg:yes", "reg:no"}))
async def reg_confirm(
    call: CallbackQuery, state: FSMContext, repo: Repository, config: Config, bot: Bot,
) -> None:
    data = await state.get_data()
    await state.clear()
    await call.message.edit_reply_markup(reply_markup=None)

    if call.data == "reg:no":
        invite = Invite(role=Role.parse(data.get("invite_role")), code=data.get("invite_code", ""))
        await notify_hr_unknown(
            bot, config, call.message, data["full_name"], data["phone"], invite,
            "сотрудник говорит, что ресторан или должность указаны неверно",
            user=call.from_user,
        )
        await call.message.answer("Понял, передал HR, чтобы исправили данные. Вам напишут.")
        await call.answer()
        return

    employee = next((e for e in await repo.list_employees() if e.id == data["employee_id"]), None)
    if employee is None:
        await call.message.answer("Что-то пошло не так. Откройте пригласительную ссылку ещё раз.")
        await call.answer()
        return
    await repo.bind_telegram(employee, call.from_user.id, data["phone"])
    repo.log(employee.id, "регистрация")
    employee.telegram_id = call.from_user.id
    is_newbie = employee.is_newbie(repo.now().date(), config.newbie_days)
    await show_main_menu(call.message, repo, employee, is_newbie)
    await call.answer("Готово!")


async def notify_hr_unknown(
    bot: Bot, config: Config, message: Message, full_name: str, phone: str,
    invite: Invite, problem: str, user=None,
) -> None:
    user = user or message.from_user
    username = f"@{user.username}" if user.username else "без username"
    text = (
        "🆕 <b>Заявка на доступ к порталу</b>\n\n"
        f"ФИО: {html.quote(full_name)}\n"
        f"Телефон: {html.quote(phone)}\n"
        f"Telegram: {html.quote(username)} (id {user.id})\n"
        f"Роль в ссылке: {html.quote(invite.role.title if invite.role else '—')}\n"
        f"Код ссылки: {html.quote(invite.code or '—')}\n"
        f"Причина: {html.quote(problem)}"
    )
    if config.hr_chat_id is None:
        log.warning("HR_CHAT_ID не задан, заявка не отправлена: %s", text)
        return
    try:
        await bot.send_message(config.hr_chat_id, text)
    except Exception:
        log.exception("Не удалось отправить заявку в HR-чат")
