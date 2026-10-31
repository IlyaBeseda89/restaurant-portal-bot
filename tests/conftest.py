from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
import pytest_asyncio
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import Chat, Message, MessageId, Update, User

from app.cli import cmd_demo
from app.config import Config
from app.storage.backend import CachedBackend
from app.storage.repository import Repository
from app.storage.sqlite_backend import SqliteBackend

FEEDBACK_CHAT = -1001
HR_CHAT = -1002


class FakeSession(BaseSession):
    """Вместо Telegram API запоминает, что бот пытался отправить."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod] = []
        self._next_id = 1000

    async def make_request(self, bot, method, timeout=None) -> Any:
        self.calls.append(method)
        name = type(method).__name__
        self._next_id += 1
        if name in {"SendMessage", "EditMessageText", "SendPhoto", "SendDocument"}:
            chat_id = getattr(method, "chat_id", None) or 1
            return Message(
                message_id=self._next_id, date=dt.datetime.now(),
                chat=Chat(id=chat_id, type="private"), text=getattr(method, "text", None) or getattr(method, "caption", None) or "",
            )
        if name == "CopyMessage":
            return MessageId(message_id=self._next_id)
        return True

    async def close(self) -> None:
        pass

    async def stream_content(self, *a, **kw):
        if False:
            yield b""

    def sent(self, chat_id: int | None = None) -> list[TelegramMethod]:
        return [
            c for c in self.calls
            if type(c).__name__ == "SendMessage" and (chat_id is None or c.chat_id == chat_id)
        ]


@pytest.fixture(autouse=True)
def _reset_concept_choice():
    from app import scope

    scope.reset()
    yield
    scope.reset()


@pytest.fixture
def config() -> Config:
    return Config(
        bot_token="42:TEST", storage="sqlite", sqlite_path=":memory:",
        google_credentials_file="", spreadsheet_id="",
        feedback_chat_id=FEEDBACK_CHAT, hr_chat_id=HR_CHAT,
        newbie_days=28, cache_ttl=0, timezone="Europe/Moscow",
    )


@pytest_asyncio.fixture
async def repo() -> Repository:
    r = Repository(CachedBackend(SqliteBackend(":memory:"), ttl=0))
    await cmd_demo(r)
    return r


class Harness:
    def __init__(self, repo: Repository, config: Config) -> None:
        from app.__main__ import build_dispatcher
        from app.handlers import (
            feedback, knowledge, menu, products, registration, training_requests, trainings,
        )

        # Роутеры — модульные объекты, в aiogram их можно подключить лишь раз.
        # Для отдельного диспетчера на каждый тест отцепляем их от прошлого.
        for r in (registration.router, feedback.chat_router, knowledge.router, products.router,
                  trainings.router, training_requests.router, feedback.router, menu.router):
            r._parent_router = None

        self.repo = repo
        self.session = FakeSession()
        self.bot = Bot("42:TEST", session=self.session)
        self.dp = build_dispatcher(repo, config)
        self._uid = 0

    def _next(self) -> int:
        self._uid += 1
        return self._uid

    async def send(self, user_id: int, text: str | None = None, chat_id: int | None = None, **extra) -> None:
        user = User(id=user_id, is_bot=False, first_name="T", username=f"user{user_id}")
        msg = Message(
            message_id=self._next(), date=dt.datetime.now(),
            chat=Chat(id=chat_id or user_id, type="private" if not chat_id else "supergroup"),
            from_user=user, text=text, **extra,
        )
        await self.dp.feed_update(self.bot, Update(update_id=self._next(), message=msg))

    async def click(self, user_id: int, data: str, chat_id: int | None = None, msg_text: str = "x") -> None:
        from aiogram.types import CallbackQuery

        user = User(id=user_id, is_bot=False, first_name="T", username=f"user{user_id}")
        msg = Message(
            message_id=self._next(), date=dt.datetime.now(),
            chat=Chat(id=chat_id or user_id, type="private" if not chat_id else "supergroup"),
            text=msg_text,
        )
        cq = CallbackQuery(id=str(self._next()), from_user=user, chat_instance="ci", message=msg, data=data)
        await self.dp.feed_update(self.bot, Update(update_id=self._next(), callback_query=cq))

    def last_text(self, chat_id: int) -> str:
        sent = self.session.sent(chat_id)
        return sent[-1].text if sent else ""

    def last_markup(self, chat_id: int):
        sent = self.session.sent(chat_id)
        return sent[-1].reply_markup if sent else None


@pytest_asyncio.fixture
async def h(repo, config) -> Harness:
    return Harness(repo, config)


async def register(h: Harness, user_id: int, payload: str, fio: str, phone: str = "+79001234567") -> None:
    await h.send(user_id, f"/start {payload}")
    await h.send(user_id, fio)
    await h.send(user_id, phone)
    await h.click(user_id, "reg:yes")
