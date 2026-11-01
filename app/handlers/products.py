"""🍽 Карточки продуктов (ТЗ, сценарий 5.5).

Категория меню → список блюд → карточка (фото, состав, аллергены, метод,
сочетания, сторителлинг). Карточка собирается из таблицы в момент нажатия,
поэтому правка строки в таблице видна сразу (с учётом кэша до минуты).
Сотрудник видит карточки только своей концепции и общие («все»).
"""

from __future__ import annotations

import hashlib
import logging
import re

from aiogram import F, Router, html
from aiogram.types import CallbackQuery, Message

from app.handlers.common import Registered
from app.keyboards import BTN_PRODUCTS, inline
from app.models import Employee, Product
from app.scope import choose, effective_concept, label, picker
from app.storage.repository import Repository

log = logging.getLogger(__name__)

router = Router(name="products")
router.message.filter(Registered())
router.callback_query.filter(Registered())

KIND = "карточка"
CAPTION_LIMIT = 1000  # у подписи к фото в Telegram лимит 1024 символа
TEXT_LIMIT = 4000  # у обычного сообщения 4096


def category_key(name: str) -> str:
    """Короткий устойчивый ключ категории для кнопки (в callback_data лимит 64 байта)."""
    return hashlib.sha1(name.encode()).hexdigest()[:8]


_DRIVE_ID = re.compile(r"(?:/file/d/|[?&]id=)([\w-]{10,})")


def photo_direct_url(url: str) -> str | None:
    """Ссылка на Google Диск → прямая ссылка на картинку. Иное http(s) оставляем как есть."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return None
    if "drive.google.com" in url:
        m = _DRIVE_ID.search(url)
        if m:
            return f"https://drive.google.com/uc?export=view&id={m.group(1)}"
    return url


def card_text(p: Product) -> str:
    def field(title: str, value: str) -> str:
        return f"\n<b>{title}</b>\n{html.quote(value)}\n" if value else ""

    allergens = (
        f"\n<b>Аллергены</b>\n⚠️ {html.quote(p.allergens)}\n"
        if p.allergens
        else "\n<b>Аллергены</b>\nв карточке не указаны, уточните у шефа\n"
    )
    text = (
        f"<b>{html.quote(p.name)}</b>\n<i>{html.quote(p.category)}</i>\n"
        + field("Состав", p.ingredients)
        + allergens
        + field("Как готовим и подаём", p.method)
        + field("Что предложить к блюду", p.pairings)
        + field("Что рассказать гостю", p.storytelling)
    )
    return text[:TEXT_LIMIT]


async def _categories_view(repo: Repository, employee: Employee):
    concept = await effective_concept(repo, employee)
    cats = await repo.list_product_categories(concept)
    head = html.quote(await label(repo, employee))
    if not cats:
        return f"🍽 {head}Карточек продуктов пока нет.", None
    rows = [[(c, f"pr:c:{category_key(c)}")] for c in cats]
    if await picker(repo, employee, "pr"):
        rows.append([("🔀 Другая концепция", "pr:pick")])
    rows.append([("⬅️ В базу знаний", "kb:cats")])
    return f"🍽 <b>Карточки продуктов</b>\n{head}Выберите категорию меню:", inline(rows)


@router.message(F.text == BTN_PRODUCTS)
async def products(message: Message, repo: Repository, employee: Employee) -> None:
    pick = await picker(repo, employee, "pr")
    if pick:  # ТУ, менеджер по обучению и HR сначала выбирают концепцию
        await message.answer("🍽 <b>Карточки продуктов</b>\n" + pick[0], reply_markup=pick[1])
        return
    text, markup = await _categories_view(repo, employee)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "pr:pick")
async def pick_again(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    pick = await picker(repo, employee, "pr")
    if pick:
        await call.message.edit_text("🍽 <b>Карточки продуктов</b>\n" + pick[0], reply_markup=pick[1])
    await call.answer()


@router.callback_query(F.data.startswith("sc:pr:"))
async def concept_chosen(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    if await choose(repo, employee, call.data.removeprefix("sc:pr:")) is None:
        await call.answer("Список концепций изменился. Откройте раздел заново.", show_alert=True)
        return
    text, markup = await _categories_view(repo, employee)
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data == "pr:cats")
async def back_to_categories(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    text, markup = await _categories_view(repo, employee)
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()


async def _category_by_key(repo: Repository, concept: str | None, key: str) -> str | None:
    for c in await repo.list_product_categories(concept):
        if category_key(c) == key:
            return c
    return None


@router.callback_query(F.data.startswith("pr:c:"))
async def category(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    concept = await effective_concept(repo, employee)
    name = await _category_by_key(repo, concept, call.data.removeprefix("pr:c:"))
    if name is None:
        await call.answer("Категория изменилась. Откройте раздел заново.", show_alert=True)
        return
    dishes = await repo.list_products(concept, name)
    rows = [[(p.name, f"pr:d:{p.id}")] for p in dishes]
    rows.append([("⬅️ Ко всем категориям", "pr:cats")])
    await call.message.edit_text(f"🍽 <b>{html.quote(name)}</b>", reply_markup=inline(rows))
    await call.answer()


async def _send_card(
    call: CallbackQuery, repo: Repository, employee: Employee, is_newbie: bool, p: Product,
) -> None:
    rows = []
    siblings = await repo.list_products(await effective_concept(repo, employee), p.category)
    if len(siblings) > 1:
        rows.append([("➡️ Следующее блюдо", f"pr:n:{p.id}")])
    if is_newbie and not await repo.is_done(employee.id, KIND, p.id):
        rows.append([("✅ Отметить изученным", f"pr:ok:{p.id}")])
    rows.append([("⬅️ К списку блюд", f"pr:c:{category_key(p.category)}")])
    markup = inline(rows)
    text = card_text(p)

    photo = photo_direct_url(p.photo_url)
    if photo:
        try:
            if len(text) <= CAPTION_LIMIT:
                await call.message.answer_photo(photo, caption=text, reply_markup=markup)
                return
            await call.message.answer_photo(photo)
        except Exception:
            # Telegram не смог скачать картинку (закрытый доступ, не картинка): покажем без неё
            log.warning("Не удалось отправить фото карточки %s: %s", p.id, p.photo_url)
    await call.message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("pr:d:"))
async def dish(call: CallbackQuery, repo: Repository, employee: Employee, is_newbie: bool) -> None:
    concept = await effective_concept(repo, employee)
    p = await repo.get_product(call.data.removeprefix("pr:d:"), concept)
    if p is None:
        await call.answer("Карточка недоступна или скрыта.", show_alert=True)
        return
    repo.log(employee.id, "просмотр карточки", p.id)
    await _send_card(call, repo, employee, is_newbie, p)
    await call.answer()


@router.callback_query(F.data.startswith("pr:n:"))
async def next_dish(call: CallbackQuery, repo: Repository, employee: Employee, is_newbie: bool) -> None:
    concept = await effective_concept(repo, employee)
    current = await repo.get_product(call.data.removeprefix("pr:n:"), concept)
    if current is None:
        await call.answer("Карточка недоступна или скрыта.", show_alert=True)
        return
    siblings = await repo.list_products(concept, current.category)
    ids = [x.id for x in siblings]
    nxt = siblings[(ids.index(current.id) + 1) % len(siblings)]
    await call.message.edit_reply_markup(reply_markup=None)  # убираем кнопки у прошлой карточки
    repo.log(employee.id, "просмотр карточки", nxt.id)
    await _send_card(call, repo, employee, is_newbie, nxt)
    await call.answer()


@router.callback_query(F.data.startswith("pr:ok:"))
async def mark_done(call: CallbackQuery, repo: Repository, employee: Employee, is_newbie: bool) -> None:
    concept = await effective_concept(repo, employee)
    p = await repo.get_product(call.data.removeprefix("pr:ok:"), concept)
    if p is None:
        await call.answer("Карточка недоступна или скрыта.", show_alert=True)
        return
    new = await repo.mark_done(employee.id, KIND, p.id)
    await call.answer("Отмечено ✅" if new else "Уже отмечено ранее")
    # убираем кнопку «Отметить» из клавиатуры сообщения
    markup = call.message.reply_markup
    if markup is not None:
        rows = [
            [b for b in row if not (b.callback_data or "").startswith("pr:ok:")]
            for row in markup.inline_keyboard
        ]
        rows = [r for r in rows if r]
        try:
            await call.message.edit_reply_markup(reply_markup=type(markup)(inline_keyboard=rows))
        except Exception:
            log.debug("Не удалось обновить клавиатуру карточки", exc_info=True)
