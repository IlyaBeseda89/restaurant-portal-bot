"""⚙️ Админка в боте (ТЗ, этап 2.3).

Для ролей с правом MANAGE_CONTENT (менеджер по обучению, модератор, HR):
сотрудники (добавить, найти, сменить роль и ресторан, отключить), материалы и карточки продуктов
(добавить, скрыть). Всё остальное по-прежнему правится прямо в таблице.

Границы:
- HR назначает любые роли; менеджер по обучению любые, кроме HR; модератор только сотрудника и
  директора в ресторанах своей концепции и материалы своей концепции.
- Свою роль и свою активность менять нельзя.
- Скрытие обратимо: строка остаётся в таблице с «активен = нет».
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router, html
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.cli import LINK_ROLE, invite_link
from app.drive import drive_file_id
from app.groups import (
    BY_KEY,
    GROUPS,
    SHORT_KEY,
    TITLES,
    default_group,
    group_of,
    parse_group,
)
from app.handlers.common import HasAccess, Registered
from app.keyboards import BTN_ADMIN, cancel_kb, inline, main_menu
from app.models import Employee
from app.roles import Role, Section
from app.scope import concept_key
from app.storage.repository import Repository

log = logging.getLogger(__name__)

router = Router(name="admin")
router.message.filter(Registered(), HasAccess(Section.MANAGE_CONTENT))
router.callback_query.filter(Registered(), HasAccess(Section.MANAGE_CONTENT))

LIST_LIMIT = 15
ROLE_BY_KEY = {key: role for role, key in LINK_ROLE.items()}


class AddEmp(StatesGroup):
    name = State()
    role = State()
    restaurant = State()
    position = State()
    group = State()


class Find(StatesGroup):
    query = State()


class AddMat(StatesGroup):
    category = State()
    title = State()
    url = State()
    concept = State()
    group = State()
    newbies = State()


class AddProd(StatesGroup):
    field = State()
    concept = State()


# ---------------------------------------------------------------- права


def assignable_roles(admin: Employee) -> list[Role]:
    if admin.role is Role.HR:
        return list(Role)
    if admin.role is Role.TRAINING_MANAGER:
        return [r for r in Role if r is not Role.HR]
    return [Role.EMPLOYEE, Role.DIRECTOR]


async def _scope(repo: Repository, admin: Employee) -> str | None:
    """None: все концепции; иначе id своей концепции ("" если определить не удалось)."""
    return await repo.concept_of(admin)


async def _restaurants_for(repo: Repository, admin: Employee):
    scope = await _scope(repo, admin)
    items = await repo.list_restaurants(active_only=True)
    if scope is None:
        return items
    return [r for r in items if r.concept_id and r.concept_id == scope]


async def _can_touch(repo: Repository, admin: Employee, target: Employee) -> bool:
    if target.id == admin.id or target.role not in assignable_roles(admin):
        return False
    scope = await _scope(repo, admin)
    if scope is None:
        return True
    restaurant = await repo.get_restaurant(target.restaurant_id)
    return bool(restaurant and restaurant.concept_id and restaurant.concept_id == scope)


def _concept_ok(scope: str | None, concept_id: str) -> bool:
    """Может ли админ со scope править запись этой концепции."""
    return scope is None or (bool(scope) and concept_id.strip().lower() == scope.strip().lower())


# ---------------------------------------------------------------- меню


def _menu_markup():
    return inline([
        [("➕ Добавить сотрудника", "ad:ea"), ("🔎 Найти сотрудника", "ad:ef")],
        [("➕ Материал", "ad:ma"), ("🗑 Скрыть материал", "ad:ml")],
        [("➕ Карточка блюда", "ad:pa"), ("🗑 Скрыть карточку", "ad:pl")],
    ])


MENU_TEXT = (
    "⚙️ <b>Админка</b>\nЗдесь можно управлять сотрудниками, материалами и карточками. "
    "Остальное (тренинги, тексты, рестораны) правится в таблице."
)


@router.message(F.text == BTN_ADMIN)
async def open_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(MENU_TEXT, reply_markup=_menu_markup())


@router.callback_query(F.data == "ad:menu")
async def back_to_menu(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text(MENU_TEXT, reply_markup=_menu_markup())
    await call.answer()


# ---------------------------------------------------------------- сотрудники: карточка


async def _concept_text(repo: Repository, e: Employee) -> str:
    """Концепция сотрудника определяется автоматически: по ресторану (у модератора по листу «Концепции»)."""
    concept = await repo.concept_of(e)
    if concept is None:
        return "все (доступ ко всем концепциям)"
    names = {c.id: c.name or c.id for c in await repo.list_concepts()}
    return html.quote(names.get(concept, concept)) if concept else "не определена (только общие материалы)"


async def _employee_card(repo: Repository, bot: Bot, admin: Employee, e: Employee):
    restaurant = await repo.get_restaurant(e.restaurant_id)
    lines = [
        f"👤 <b>{html.quote(e.full_name)}</b>",
        f"Роль: {html.quote(e.role.title)}",
        f"Ресторан: {html.quote(restaurant.name) if restaurant else '—'}",
        f"Концепция: {await _concept_text(repo, e)}",
        f"Должность: {html.quote(e.position or '—')}",
        f"Группа: {TITLES[group_of(e)]}" + ("" if parse_group(e.group) else " (по должности)"),
        "Статус: " + ("активен" if e.active else "отключён"),
    ]
    if e.telegram_id:
        lines.append("Вход в бот: выполнен ✅")
    elif e.invite_code:
        username = (await bot.me()).username
        lines.append("Вход в бот: ещё не заходил(а). Отправьте ссылку:")
        lines.append(invite_link(username, e.role, e.invite_code))
    rows = []
    if await _can_touch(repo, admin, e):
        rows.append([("🔁 Роль", f"ad:er:{e.id}"), ("🏠 Ресторан", f"ad:es:{e.id}")])
        rows.append([("👥 Группа", f"ad:eg:{e.id}")])
        rows.append([("🔒 Отключить" if e.active else "🔓 Включить", f"ad:ex:{e.id}")])
    else:
        lines.append("\nЭтого сотрудника вы изменить не можете.")
    rows.append([("⬅️ В админку", "ad:menu")])
    return "\n".join(lines), inline(rows)


async def _show_employee(call: CallbackQuery, repo: Repository, bot: Bot, admin: Employee, emp_id: str) -> None:
    e = await repo.get_employee(emp_id)
    if e is None:
        await call.answer("Сотрудник не найден.", show_alert=True)
        return
    text, markup = await _employee_card(repo, bot, admin, e)
    await call.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    await call.answer()


@router.callback_query(F.data.startswith("ad:e:"))
async def employee_card(call: CallbackQuery, repo: Repository, bot: Bot, employee: Employee) -> None:
    await _show_employee(call, repo, bot, employee, call.data.removeprefix("ad:e:"))


# ---------------------------------------------------------------- сотрудники: поиск


@router.callback_query(F.data == "ad:ef")
async def find_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Find.query)
    await call.message.answer("Введите часть фамилии или имени.", reply_markup=cancel_kb())
    await call.answer()


@router.message(Find.query, F.text)
async def find_do(message: Message, state: FSMContext, repo: Repository, employee: Employee, is_newbie: bool) -> None:
    await state.clear()
    found = await repo.find_employees(message.text)
    if not found:
        await message.answer("Никого не нашёл. Попробуйте другую часть имени.",
                             reply_markup=main_menu(employee.role, is_newbie))
        return
    rows = [[(f"{e.full_name}" + ("" if e.active else " (отключён)"), f"ad:e:{e.id}")] for e in found]
    await message.answer("Выберите сотрудника:", reply_markup=main_menu(employee.role, is_newbie))
    await message.answer("Найдено:", reply_markup=inline(rows))


# ---------------------------------------------------------------- сотрудники: изменения


@router.callback_query(F.data.startswith("ad:er:"))
async def role_menu(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    target = await repo.get_employee(call.data.removeprefix("ad:er:"))
    if target is None or not await _can_touch(repo, employee, target):
        await call.answer("Это изменить нельзя.", show_alert=True)
        return
    rows = [[(r.title, f"ad:erv:{target.id}:{LINK_ROLE[r]}")] for r in assignable_roles(employee)]
    rows.append([("⬅️ Назад", f"ad:e:{target.id}")])
    await call.message.edit_text(f"Новая роль для {html.quote(target.full_name)}:", reply_markup=inline(rows))
    await call.answer()


@router.callback_query(F.data.startswith("ad:erv:"))
async def role_set(call: CallbackQuery, repo: Repository, bot: Bot, employee: Employee) -> None:
    emp_id, _, key = call.data.removeprefix("ad:erv:").partition(":")
    target, role = await repo.get_employee(emp_id), ROLE_BY_KEY.get(key)
    if target is None or role is None or role not in assignable_roles(employee) \
            or not await _can_touch(repo, employee, target):
        await call.answer("Это изменить нельзя.", show_alert=True)
        return
    await repo.update_employee(target.id, роль=role.value)
    repo.log(employee.id, f"админка: роль {role.value}", target.id)
    await _show_employee(call, repo, bot, employee, target.id)


@router.callback_query(F.data.startswith("ad:es:"))
async def restaurant_menu(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    target = await repo.get_employee(call.data.removeprefix("ad:es:"))
    if target is None or not await _can_touch(repo, employee, target):
        await call.answer("Это изменить нельзя.", show_alert=True)
        return
    rows = [[(r.name, f"ad:esv:{target.id}:{r.id}")] for r in await _restaurants_for(repo, employee)]
    rows.append([("⬅️ Назад", f"ad:e:{target.id}")])
    await call.message.edit_text(f"Ресторан для {html.quote(target.full_name)}:", reply_markup=inline(rows))
    await call.answer()


@router.callback_query(F.data.startswith("ad:esv:"))
async def restaurant_set(call: CallbackQuery, repo: Repository, bot: Bot, employee: Employee) -> None:
    emp_id, _, rid = call.data.removeprefix("ad:esv:").partition(":")
    target = await repo.get_employee(emp_id)
    allowed = {r.id for r in await _restaurants_for(repo, employee)}
    if target is None or rid not in allowed or not await _can_touch(repo, employee, target):
        await call.answer("Это изменить нельзя.", show_alert=True)
        return
    await repo.update_employee(target.id, ресторан_id=rid)
    repo.log(employee.id, f"админка: ресторан {rid}", target.id)
    await _show_employee(call, repo, bot, employee, target.id)


@router.callback_query(F.data.startswith("ad:eg:"))
async def group_menu(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    target = await repo.get_employee(call.data.removeprefix("ad:eg:"))
    if target is None or not await _can_touch(repo, employee, target):
        await call.answer("Это изменить нельзя.", show_alert=True)
        return
    rows = [[(TITLES[g], f"ad:egv:{target.id}:{SHORT_KEY[g]}")] for g in reversed(GROUPS)]
    rows.append([("По должности (авто)", f"ad:egv:{target.id}:auto")])
    rows.append([("⬅️ Назад", f"ad:e:{target.id}")])
    await call.message.edit_text(f"Группа для {html.quote(target.full_name)}:", reply_markup=inline(rows))
    await call.answer()


@router.callback_query(F.data.startswith("ad:egv:"))
async def group_set(call: CallbackQuery, repo: Repository, bot: Bot, employee: Employee) -> None:
    emp_id, _, key = call.data.removeprefix("ad:egv:").partition(":")
    target = await repo.get_employee(emp_id)
    if target is None or (key != "auto" and key not in BY_KEY) or not await _can_touch(repo, employee, target):
        await call.answer("Это изменить нельзя.", show_alert=True)
        return
    value = "" if key == "auto" else BY_KEY[key]
    await repo.update_employee(target.id, группа=value)
    repo.log(employee.id, f"админка: группа {value or 'авто'}", target.id)
    await _show_employee(call, repo, bot, employee, target.id)


@router.callback_query(F.data.startswith("ad:ex:"))
async def toggle_active(call: CallbackQuery, repo: Repository, bot: Bot, employee: Employee) -> None:
    target = await repo.get_employee(call.data.removeprefix("ad:ex:"))
    if target is None or not await _can_touch(repo, employee, target):
        await call.answer("Это изменить нельзя.", show_alert=True)
        return
    new = not target.active
    await repo.update_employee(target.id, активен="да" if new else "нет")
    repo.log(employee.id, "админка: включён" if new else "админка: отключён", target.id)
    await _show_employee(call, repo, bot, employee, target.id)


# ---------------------------------------------------------------- сотрудники: добавление


@router.callback_query(F.data == "ad:ea")
async def add_emp_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AddEmp.name)
    await call.message.answer("Введите ФИО нового сотрудника полностью (фамилия, имя, отчество).",
                              reply_markup=cancel_kb())
    await call.answer()


@router.message(AddEmp.name, F.text)
async def add_emp_name(message: Message, state: FSMContext, employee: Employee) -> None:
    name = " ".join(message.text.split())
    if len(name.split()) < 2 or len(name) > 120:
        await message.answer("Напишите фамилию и имя, лучше полностью с отчеством.")
        return
    await state.update_data(name=name)
    await state.set_state(AddEmp.role)
    rows = [[(r.title, f"ad:ar:{LINK_ROLE[r]}")] for r in assignable_roles(employee)]
    await message.answer("Какая роль?", reply_markup=inline(rows))


@router.callback_query(AddEmp.role, F.data.startswith("ad:ar:"))
async def add_emp_role(call: CallbackQuery, state: FSMContext, repo: Repository, employee: Employee) -> None:
    role = ROLE_BY_KEY.get(call.data.removeprefix("ad:ar:"))
    if role is None or role not in assignable_roles(employee):
        await call.answer("Эту роль назначить нельзя.", show_alert=True)
        return
    restaurants = await _restaurants_for(repo, employee)
    if not restaurants:
        await call.answer("Нет подходящих ресторанов. Добавьте их в таблице «Рестораны».", show_alert=True)
        return
    await state.update_data(role=role.value)
    await state.set_state(AddEmp.restaurant)
    rows = [[(r.name, f"ad:as:{r.id}")] for r in restaurants]
    await call.message.edit_text("В каком ресторане работает?", reply_markup=inline(rows))
    await call.answer()


@router.callback_query(AddEmp.restaurant, F.data.startswith("ad:as:"))
async def add_emp_restaurant(call: CallbackQuery, state: FSMContext, repo: Repository, employee: Employee) -> None:
    rid = call.data.removeprefix("ad:as:")
    if rid not in {r.id for r in await _restaurants_for(repo, employee)}:
        await call.answer("Этот ресторан недоступен.", show_alert=True)
        return
    await state.update_data(restaurant=rid)
    await state.set_state(AddEmp.position)
    await call.message.edit_text("Ресторан выбран.")
    await call.message.answer("Должность? Если не нужна, напишите «-».", reply_markup=cancel_kb())
    await call.answer()


@router.message(AddEmp.position, F.text)
async def add_emp_position(message: Message, state: FSMContext, employee: Employee) -> None:
    position = "" if message.text.strip() in {"-", "—"} else message.text.strip()[:80]
    data = await state.get_data()
    role = Role.parse(data["role"])
    await state.update_data(position=position)
    await state.set_state(AddEmp.group)
    auto = TITLES[default_group(role, position)] if role else "—"
    rows = [[(TITLES[g], f"ad:ag:{SHORT_KEY[g]}")] for g in reversed(GROUPS)]
    rows.append([(f"Определить по должности ({auto})", "ad:ag:auto")])
    await message.answer("К какой группе относится сотрудник?", reply_markup=inline(rows))


@router.callback_query(AddEmp.group, F.data.startswith("ad:ag:"))
async def add_emp_finish(
    call: CallbackQuery, state: FSMContext, repo: Repository, bot: Bot, employee: Employee, is_newbie: bool,
) -> None:
    key = call.data.removeprefix("ad:ag:")
    if key != "auto" and key not in BY_KEY:
        await call.answer("Выберите из списка.", show_alert=True)
        return
    data = await state.get_data()
    await state.clear()
    role = Role.parse(data["role"])
    if role is None or role not in assignable_roles(employee):
        await call.message.answer("Не получилось, начните заново.", reply_markup=main_menu(employee.role, is_newbie))
        await call.answer()
        return
    group = "" if key == "auto" else BY_KEY[key]
    new = await repo.add_employee(data["name"], data["restaurant"], data.get("position", ""), role, group)
    repo.log(employee.id, "админка: добавлен сотрудник", new.id)
    username = (await bot.me()).username
    await call.message.edit_text("Группа выбрана.")
    await call.message.answer("Готово ✅", reply_markup=main_menu(employee.role, is_newbie))
    await call.message.answer(
        f"Сотрудник <b>{html.quote(new.full_name)}</b> добавлен ({html.quote(role.title)}, "
        f"группа: {TITLES[group_of(new)]}).\n"
        f"Концепция определена автоматически: {await _concept_text(repo, new)}.\n\n"
        "Отправьте ему эту ссылку. При входе он введёт ФИО, и бот привяжет его к записи:\n"
        f"{invite_link(username, role, new.invite_code)}",
        disable_web_page_preview=True,
    )
    await call.answer()


# ---------------------------------------------------------------- материалы


async def _concept_choices(repo: Repository, admin: Employee):
    """Кнопки выбора концепции записи: «все» и концепции. Модератору только своя."""
    scope = await _scope(repo, admin)
    concepts = await repo.list_concepts()
    rows: list[list[tuple[str, str]]] = []
    mapping: dict[str, str] = {}
    if scope is None:
        mapping["all"] = "все"
        rows.append([("Для всех концепций", "all")])
    for c in concepts:
        if scope is None or c.id == scope:
            mapping[concept_key(c.id)] = c.id
            rows.append([(c.name or c.id, concept_key(c.id))])
    return mapping, rows


@router.callback_query(F.data == "ad:ma")
async def mat_start(call: CallbackQuery, state: FSMContext, repo: Repository) -> None:
    await state.clear()
    categories = await repo.list_categories()
    if not categories:
        await call.answer("Сначала добавьте разделы в таблице «Категории».", show_alert=True)
        return
    await state.set_state(AddMat.category)
    rows = [[(c.name, f"ad:mc:{c.id}")] for c in categories]
    await call.message.answer("Новый материал. В какой раздел?", reply_markup=inline(rows))
    await call.answer()


@router.callback_query(AddMat.category, F.data.startswith("ad:mc:"))
async def mat_category(call: CallbackQuery, state: FSMContext, repo: Repository) -> None:
    cid = call.data.removeprefix("ad:mc:")
    if cid not in {c.id for c in await repo.list_categories()}:
        await call.answer("Раздел не найден.", show_alert=True)
        return
    await state.update_data(category=cid)
    await state.set_state(AddMat.title)
    await call.message.edit_text("Раздел выбран.")
    await call.message.answer("Название материала?", reply_markup=cancel_kb())
    await call.answer()


@router.message(AddMat.title, F.text)
async def mat_title(message: Message, state: FSMContext) -> None:
    title = " ".join(message.text.split())[:120]
    await state.update_data(title=title)
    await state.set_state(AddMat.url)
    await message.answer("Пришлите ссылку (Google Диск, сайт). Файлы с Диска бот отправит прямо в чат.")


@router.message(AddMat.url, F.text)
async def mat_url(message: Message, state: FSMContext, repo: Repository, employee: Employee) -> None:
    url = message.text.strip()
    if not url.startswith(("http://", "https://")) or " " in url:
        await message.answer("Нужна ссылка, начинающаяся с https://")
        return
    await state.update_data(url=url, kind="файл" if drive_file_id(url) else "ссылка")
    mapping, rows = await _concept_choices(repo, employee)
    if not rows:
        await state.clear()
        await message.answer("Для вашей роли нет концепции. Обратитесь к HR.")
        return
    if len(mapping) == 1:  # у модератора концепция одна: не спрашиваем
        await state.update_data(concept=next(iter(mapping.values())))
        await _ask_material_group(message, state)
        return
    await state.update_data(concepts=mapping)
    await state.set_state(AddMat.concept)
    await message.answer("Для какой концепции?", reply_markup=inline([[(t, f"ad:mn:{k}")] for [(t, k)] in rows]))


async def _ask_material_group(message: Message, state: FSMContext) -> None:
    await state.set_state(AddMat.group)
    await message.answer(
        "Для кого материал?",
        reply_markup=inline([
            [("Для всех", "ad:mg:all")],
            [("Менеджмент и руководители", "ad:mg:mgmt")],
            [("Только руководители", "ad:mg:lead")],
        ]),
    )


@router.callback_query(AddMat.concept, F.data.startswith("ad:mn:"))
async def mat_concept(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    concept = data.get("concepts", {}).get(call.data.removeprefix("ad:mn:"))
    if concept is None:
        await call.answer("Выберите из списка.", show_alert=True)
        return
    await state.update_data(concept=concept)
    await call.message.edit_text("Концепция выбрана.")
    await _ask_material_group(call.message, state)
    await call.answer()


@router.callback_query(AddMat.group, F.data.startswith("ad:mg:"))
async def mat_group(call: CallbackQuery, state: FSMContext) -> None:
    key = call.data.removeprefix("ad:mg:")
    if key != "all" and key not in BY_KEY:
        await call.answer("Выберите из списка.", show_alert=True)
        return
    await state.update_data(group="" if key == "all" else BY_KEY[key])
    await state.set_state(AddMat.newbies)
    await call.message.edit_text("Группа выбрана.")
    await call.message.answer(
        "Показывать в «Мой старт» для новичков?",
        reply_markup=inline([[("Да", "ad:mb:1"), ("Нет", "ad:mb:0")]]),
    )
    await call.answer()


@router.callback_query(AddMat.newbies, F.data.startswith("ad:mb:"))
async def mat_finish(
    call: CallbackQuery, state: FSMContext, repo: Repository, employee: Employee, is_newbie: bool,
) -> None:
    data = await state.get_data()
    await state.clear()
    material_id = await repo.add_material(
        data["category"], data["title"], data["kind"], data["url"], data["concept"],
        for_newbies=call.data.endswith("1"), group=data.get("group", ""),
    )
    repo.log(employee.id, "админка: добавлен материал", material_id)
    await call.message.edit_text("Выбрано.")
    await call.message.answer(
        f"✅ Материал «{html.quote(data['title'])}» добавлен. Он уже виден в «Базе знаний».",
        reply_markup=main_menu(employee.role, is_newbie),
    )
    await call.answer()


@router.callback_query(F.data == "ad:ml")
async def mat_list(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    scope = await _scope(repo, employee)
    items = [m for m in await repo.list_materials(concept_id=None) if _concept_ok(scope, m.concept_id)]
    if not items:
        await call.answer("Материалов нет.", show_alert=True)
        return
    rows = [[(f"🗑 {m.title[:40]}", f"ad:mh:{m.id}")] for m in items[-LIST_LIMIT:]]
    rows.append([("⬅️ В админку", "ad:menu")])
    await call.message.edit_text(
        f"Какой материал скрыть? Показаны последние {min(len(items), LIST_LIMIT)}.", reply_markup=inline(rows),
    )
    await call.answer()


@router.callback_query(F.data.startswith("ad:mh:"))
async def mat_hide_ask(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    material = await repo.get_material(call.data.removeprefix("ad:mh:"))
    if material is None or not _concept_ok(await _scope(repo, employee), material.concept_id):
        await call.answer("Материал не найден.", show_alert=True)
        return
    await call.message.edit_text(
        f"Скрыть «{html.quote(material.title)}»? Строка останется в таблице, вернуть можно там.",
        reply_markup=inline([[("Да, скрыть", f"ad:mx:{material.id}"), ("Нет", "ad:ml")]]),
    )
    await call.answer()


@router.callback_query(F.data.startswith("ad:mx:"))
async def mat_hide(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    material = await repo.get_material(call.data.removeprefix("ad:mx:"))
    if material is None or not _concept_ok(await _scope(repo, employee), material.concept_id):
        await call.answer("Материал не найден.", show_alert=True)
        return
    await repo.update_material(material.id, активен="нет")
    repo.log(employee.id, "админка: скрыт материал", material.id)
    await call.message.edit_text(f"✅ Скрыто: {html.quote(material.title)}",
                                 reply_markup=inline([[("⬅️ В админку", "ad:menu")]]))
    await call.answer()


# ---------------------------------------------------------------- карточки продуктов

PRODUCT_FIELDS = [
    ("category", "Категория меню (например, «Горячее»)?", False),
    ("name", "Название блюда?", False),
    ("ingredients", "Состав?", True),
    ("allergens", "Аллергены?", True),
    ("method", "Метод приготовления?", True),
    ("pairings", "Сочетания (с чем подавать)?", True),
    ("storytelling", "История блюда для гостя?", True),
    ("photo", "Ссылка на фото?", True),
]


async def _ask_product_field(message: Message, idx: int) -> None:
    _, prompt, optional = PRODUCT_FIELDS[idx]
    await message.answer(prompt + (" Если нечего писать, отправьте «-»." if optional else ""),
                         reply_markup=cancel_kb())


@router.callback_query(F.data == "ad:pa")
async def prod_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AddProd.field)
    await state.update_data(idx=0, values={})
    await call.message.answer("Новая карточка блюда.")
    await _ask_product_field(call.message, 0)
    await call.answer()


@router.message(AddProd.field, F.text)
async def prod_field(message: Message, state: FSMContext, repo: Repository, employee: Employee) -> None:
    data = await state.get_data()
    idx, values = data["idx"], dict(data["values"])
    key, _, optional = PRODUCT_FIELDS[idx]
    text = message.text.strip()
    if optional and text in {"-", "—"}:
        text = ""
    if not text and not optional:
        await message.answer("Это поле обязательное.")
        return
    if key == "photo" and text and not text.startswith(("http://", "https://")):
        await message.answer("Нужна ссылка на фото или «-».")
        return
    values[key] = text[:1500]
    if idx + 1 < len(PRODUCT_FIELDS):
        await state.update_data(idx=idx + 1, values=values)
        await _ask_product_field(message, idx + 1)
        return
    mapping, rows = await _concept_choices(repo, employee)
    if not rows:
        await state.clear()
        await message.answer("Для вашей роли нет концепции. Обратитесь к HR.")
        return
    if len(mapping) == 1:  # у модератора концепция одна: не спрашиваем
        await state.clear()
        await _save_product(message, repo, employee, next(iter(mapping.values())), values)
        return
    await state.update_data(values=values, concepts=mapping)
    await state.set_state(AddProd.concept)
    await message.answer("Для какой концепции?", reply_markup=inline([[(t, f"ad:pn:{k}")] for [(t, k)] in rows]))


@router.callback_query(AddProd.concept, F.data.startswith("ad:pn:"))
async def prod_finish(
    call: CallbackQuery, state: FSMContext, repo: Repository, employee: Employee, is_newbie: bool,
) -> None:
    data = await state.get_data()
    concept = data.get("concepts", {}).get(call.data.removeprefix("ad:pn:"))
    if concept is None:
        await call.answer("Выберите из списка.", show_alert=True)
        return
    await state.clear()
    await call.message.edit_text("Выбрано.")
    await _save_product(call.message, repo, employee, concept, data["values"], is_newbie)
    await call.answer()


async def _save_product(
    message: Message, repo: Repository, employee: Employee, concept: str, v: dict, is_newbie: bool | None = None,
) -> None:
    product_id = await repo.add_product(
        concept, v["category"], v["name"], v.get("photo", ""), v.get("ingredients", ""),
        v.get("allergens", ""), v.get("method", ""), v.get("pairings", ""), v.get("storytelling", ""),
    )
    repo.log(employee.id, "админка: добавлена карточка", product_id)
    await message.answer(
        f"✅ Карточка «{html.quote(v['name'])}» добавлена.",
        reply_markup=main_menu(employee.role, bool(is_newbie)),
    )


@router.callback_query(F.data == "ad:pl")
async def prod_list(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    scope = await _scope(repo, employee)
    items = [p for p in await repo.list_products(concept_id=None) if _concept_ok(scope, p.concept_id)]
    if not items:
        await call.answer("Карточек нет.", show_alert=True)
        return
    rows = [[(f"🗑 {p.name[:40]}", f"ad:ph:{p.id}")] for p in items[-LIST_LIMIT:]]
    rows.append([("⬅️ В админку", "ad:menu")])
    await call.message.edit_text(
        f"Какую карточку скрыть? Показаны последние {min(len(items), LIST_LIMIT)}.", reply_markup=inline(rows),
    )
    await call.answer()


async def _product_for_admin(repo: Repository, employee: Employee, product_id: str):
    scope = await _scope(repo, employee)
    for p in await repo.list_products(concept_id=None):
        if p.id == product_id and _concept_ok(scope, p.concept_id):
            return p
    return None


@router.callback_query(F.data.startswith("ad:ph:"))
async def prod_hide_ask(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    product = await _product_for_admin(repo, employee, call.data.removeprefix("ad:ph:"))
    if product is None:
        await call.answer("Карточка не найдена.", show_alert=True)
        return
    await call.message.edit_text(
        f"Скрыть «{html.quote(product.name)}»? Строка останется в таблице, вернуть можно там.",
        reply_markup=inline([[("Да, скрыть", f"ad:px:{product.id}"), ("Нет", "ad:pl")]]),
    )
    await call.answer()


@router.callback_query(F.data.startswith("ad:px:"))
async def prod_hide(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    product = await _product_for_admin(repo, employee, call.data.removeprefix("ad:px:"))
    if product is None:
        await call.answer("Карточка не найдена.", show_alert=True)
        return
    await repo.update_product(product.id, активен="нет")
    repo.log(employee.id, "админка: скрыта карточка", product.id)
    await call.message.edit_text(f"✅ Скрыто: {html.quote(product.name)}",
                                 reply_markup=inline([[("⬅️ В админку", "ad:menu")]]))
    await call.answer()
