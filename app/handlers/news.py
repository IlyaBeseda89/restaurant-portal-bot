"""📰 Новости: посты руководителей, общие или по концепциям.

Читать могут все. Писать: директор, ТУ, менеджер по обучению, модератор, HR и все из группы
«руководители» (шефы и т. п.). Новость видят общие + своей концепции; кто работает со всеми
концепциями (ТУ, менеджер по обучению, HR), видит все и может писать как для всех, так и для одной.
Остальные авторы пишут для своей концепции (если концепции нет, то для всех).
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router, html
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.groups import LEADERS, group_of
from app.handlers.common import Registered
from app.keyboards import BTN_NEWS, cancel_kb, inline, main_menu
from app.models import Employee, NewsPost
from app.roles import Role, Section, can
from app.scope import concept_key
from app.storage.repository import Repository

log = logging.getLogger(__name__)

router = Router(name="news")
router.message.filter(Registered())
router.callback_query.filter(Registered())

PAGE = 8
TITLE_MAX, TEXT_MAX = 100, 3500
MODERATORS = {Role.HR, Role.TRAINING_MANAGER, Role.TU}  # могут скрыть любую новость


class NewsForm(StatesGroup):
    title = State()
    text = State()
    photo = State()
    audience = State()
    confirm = State()


def can_post(employee: Employee) -> bool:
    return can(employee.role, Section.NEWS_POST) or group_of(employee) == LEADERS


async def concept_names(repo: Repository) -> dict[str, str]:
    return {c.id: c.name or c.id for c in await repo.list_concepts()}


def tag(post: NewsPost, names: dict[str, str]) -> str:
    return f"🏷 {names.get(post.concept_id, post.concept_id)}" if post.concept_id else "🌐 Для всех"


def render(post: NewsPost, names: dict[str, str]) -> str:
    return (
        f"📰 <b>{html.quote(post.title)}</b>\n{tag(post, names)} · {post.date}\n\n"
        f"{html.quote(post.text)}\n\n<i>{html.quote(post.author)}</i>"
    )


async def feed(repo: Repository, employee: Employee, page: int):
    posts = await repo.list_news(await repo.concept_of(employee))
    names = await concept_names(repo)
    page = max(0, min(page, max(0, (len(posts) - 1) // PAGE)))
    rows = [
        [(f"{p.date[:5]} · {p.title[:40]}" + (f" · {names.get(p.concept_id, p.concept_id)}" if p.concept_id else ""),
          f"nw:o:{p.id}")]
        for p in posts[page * PAGE:(page + 1) * PAGE]
    ]
    nav = []
    if page > 0:
        nav.append(("◀️ Новее", f"nw:p:{page - 1}"))
    if (page + 1) * PAGE < len(posts):
        nav.append(("Старше ▶️", f"nw:p:{page + 1}"))
    if nav:
        rows.append(nav)
    if can_post(employee):
        rows.append([("✍️ Написать новость", "nw:new")])
    text = "📰 <b>Новости</b>" if posts else "📰 <b>Новости</b>\nПока новостей нет."
    return text, inline(rows)


@router.message(F.text == BTN_NEWS)
async def open_feed(message: Message, state: FSMContext, repo: Repository, employee: Employee) -> None:
    await state.clear()
    text, markup = await feed(repo, employee, 0)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("nw:p:"))
async def page(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    await call.answer()
    text, markup = await feed(repo, employee, int(call.data.rsplit(":", 1)[1]))
    await call.message.edit_text(text, reply_markup=markup)


async def send_post(bot: Bot, chat_id: int, post: NewsPost, names: dict[str, str], markup=None) -> None:
    text = render(post, names)
    if post.photo and len(text) <= 1000:
        await bot.send_photo(chat_id, post.photo, caption=text, reply_markup=markup)
    elif post.photo:
        await bot.send_photo(chat_id, post.photo)
        await bot.send_message(chat_id, text, reply_markup=markup)
    else:
        await bot.send_message(chat_id, text, reply_markup=markup)


@router.callback_query(F.data.startswith("nw:o:"))
async def open_post(call: CallbackQuery, bot: Bot, repo: Repository, employee: Employee) -> None:
    await call.answer()
    post = await repo.get_news(call.data.removeprefix("nw:o:"))
    visible = await repo.concept_of(employee)
    if post is None or (visible is not None and post.concept_id not in ("", visible)):
        await call.message.answer("Эта новость больше недоступна.")
        return
    markup = None
    if post.author_id == employee.id or employee.role in MODERATORS:
        markup = inline([[("🗑 Скрыть новость", f"nw:h:{post.id}")]])
    await send_post(bot, call.message.chat.id, post, await concept_names(repo), markup)


@router.callback_query(F.data.startswith("nw:h:"))
async def hide(call: CallbackQuery, repo: Repository, employee: Employee) -> None:
    await call.answer()
    post = await repo.get_news(call.data.removeprefix("nw:h:"))
    if post is None:
        await call.message.answer("Новость уже скрыта.")
        return
    if post.author_id != employee.id and employee.role not in MODERATORS:
        await call.message.answer("Скрыть новость может её автор, ТУ, менеджер по обучению или HR.")
        return
    await repo.hide_news(post.id)
    repo.log(employee.id, "новости: скрыта", post.id)
    await call.message.answer(f"🗑 Новость «{html.quote(post.title)}» скрыта из ленты.")


# ---------- написание ----------

@router.callback_query(F.data == "nw:new")
async def new(call: CallbackQuery, state: FSMContext, employee: Employee) -> None:
    await call.answer()
    if not can_post(employee):
        await call.message.answer("Публиковать новости могут руководители.")
        return
    await state.clear()
    await state.set_state(NewsForm.title)
    await call.message.answer("✍️ Напишите <b>заголовок</b> новости (коротко).", reply_markup=cancel_kb())


@router.message(NewsForm.title, F.text)
async def got_title(message: Message, state: FSMContext) -> None:
    title = message.text.strip()
    if not title or len(title) > TITLE_MAX:
        await message.answer(f"Заголовок нужен длиной до {TITLE_MAX} символов. Попробуйте ещё раз.")
        return
    await state.update_data(title=title)
    await state.set_state(NewsForm.text)
    await message.answer("Теперь <b>текст</b> новости.")


@router.message(NewsForm.text, F.text)
async def got_text(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not text or len(text) > TEXT_MAX:
        await message.answer(f"Текст нужен длиной до {TEXT_MAX} символов. Сократите и пришлите ещё раз.")
        return
    await state.update_data(text=text)
    await state.set_state(NewsForm.photo)
    await message.answer(
        "Приложите <b>фото</b> или пропустите.",
        reply_markup=inline([[("Без фото", "nw:nophoto")]]),
    )


async def ask_audience(message: Message, state: FSMContext, repo: Repository, employee: Employee) -> None:
    base = await repo.concept_of(employee)
    names = await concept_names(repo)
    if base is None:
        rows = [[("🌐 Для всех концепций", "nw:a:all")]]
        rows += [[(f"🏷 {n}", f"nw:a:{concept_key(cid)}")] for cid, n in names.items()]
        await state.set_state(NewsForm.audience)
        await message.answer("Для кого эта новость?", reply_markup=inline(rows))
        return
    await state.update_data(concept_id=base)
    await show_preview(message, state, repo, employee)


@router.message(NewsForm.photo, F.photo)
async def got_photo(message: Message, state: FSMContext, repo: Repository, employee: Employee) -> None:
    await state.update_data(photo=message.photo[-1].file_id)
    await ask_audience(message, state, repo, employee)


@router.callback_query(NewsForm.photo, F.data == "nw:nophoto")
async def no_photo(call: CallbackQuery, state: FSMContext, repo: Repository, employee: Employee) -> None:
    await call.answer()
    await state.update_data(photo="")
    await ask_audience(call.message, state, repo, employee)


@router.callback_query(NewsForm.audience, F.data.startswith("nw:a:"))
async def choose_audience(call: CallbackQuery, state: FSMContext, repo: Repository, employee: Employee) -> None:
    await call.answer()
    key = call.data.removeprefix("nw:a:")
    concept_id = ""
    if key != "all":
        concept_id = next((c for c in await concept_names(repo) if concept_key(c) == key), None)
        if concept_id is None:
            await call.message.answer("Не нашёл такую концепцию. Выберите из кнопок.")
            return
    await state.update_data(concept_id=concept_id)
    await show_preview(call.message, state, repo, employee)


async def recipients(repo: Repository, concept_id: str, author_id: str) -> list[Employee]:
    result = []
    for e in await repo.list_employees():
        if not e.active or not e.telegram_id or e.id == author_id:
            continue
        base = await repo.concept_of(e)
        if not concept_id or base is None or base == concept_id:
            result.append(e)
    return result


async def show_preview(message: Message, state: FSMContext, repo: Repository, employee: Employee) -> None:
    data = await state.get_data()
    post = NewsPost("", repo._now_str(), employee.id, employee.full_name, data["title"], data["text"],
                    data.get("concept_id", ""), data.get("photo", ""))
    count = len(await recipients(repo, post.concept_id, employee.id))
    await state.set_state(NewsForm.confirm)
    await message.answer("Так новость увидят читатели:")
    await send_post(message.bot, message.chat.id, post, await concept_names(repo))
    await message.answer(
        f"Разослать уведомление {count} сотрудникам или только положить в ленту?",
        reply_markup=inline([
            [(f"📣 Опубликовать и разослать ({count})", "nw:go:push")],
            [("📌 Только в ленту", "nw:go:feed")],
        ]),
    )


@router.callback_query(NewsForm.confirm, F.data.startswith("nw:go:"))
async def publish(
    call: CallbackQuery, state: FSMContext, bot: Bot, repo: Repository, employee: Employee, is_newbie: bool,
) -> None:
    await call.answer()
    await call.message.edit_reply_markup(reply_markup=None)
    data = await state.get_data()
    await state.clear()
    post = NewsPost("", "", employee.id, employee.full_name, data["title"], data["text"],
                    data.get("concept_id", ""), data.get("photo", ""))
    post.id = await repo.add_news(post)
    post.date = repo._now_str()
    repo.log(employee.id, "новости: опубликована", post.id)
    reply = f"✅ Новость «{html.quote(post.title)}» опубликована в ленте."
    if call.data.endswith("push"):
        names = await concept_names(repo)
        people = await recipients(repo, post.concept_id, employee.id)
        sent = 0
        for person in people:
            try:
                await send_post(bot, person.telegram_id, post, names)
                sent += 1
            except Exception:
                log.warning("Новость %s не доставлена сотруднику %s", post.id, person.id, exc_info=True)
            await asyncio.sleep(0.05)  # лимиты Telegram
        await repo.set_news_sent(post.id, sent)
        reply += f"\n📣 Доставлено: {sent} из {len(people)}."
    await call.message.answer(reply, reply_markup=main_menu(employee.role, is_newbie))
