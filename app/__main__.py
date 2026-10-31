"""Запуск бота: python -m app"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from app.config import Config, build_repository
from app.handlers import build_router
from app.middlewares import EmployeeMiddleware, MenuResetMiddleware
from app.reminders import remind_forever
from app.storage.repository import Repository

log = logging.getLogger("portal")


async def flush_activity_forever(repo: Repository, every: float = 30.0) -> None:
    while True:
        await asyncio.sleep(every)
        try:
            await repo.flush_activity()
        except Exception:
            log.exception("Не удалось записать журнал активности, повторю позже")


def build_dispatcher(repo: Repository, config: Config) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    employee_mw = EmployeeMiddleware(repo, config)
    dp.message.outer_middleware(employee_mw)
    dp.callback_query.outer_middleware(employee_mw)
    dp.message.outer_middleware(MenuResetMiddleware())
    dp.include_router(build_router())
    return dp


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = Config.from_env()
    if not config.bot_token:
        raise SystemExit("Не задан BOT_TOKEN. Скопируйте .env.example в .env и впишите токен от @BotFather.")

    repo = build_repository(config)
    await repo.backend.ensure_tables()

    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.set_my_commands([
        BotCommand(command="menu", description="Главное меню"),
        BotCommand(command="help", description="Помощь и контакты"),
    ])
    dp = build_dispatcher(repo, config)

    flusher = asyncio.create_task(flush_activity_forever(repo))
    reminder = asyncio.create_task(remind_forever(bot, repo))
    me = await bot.get_me()
    log.info("Бот @%s запущен, хранилище: %s", me.username, config.storage)
    try:
        await dp.start_polling(bot)
    finally:
        flusher.cancel()
        reminder.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await flusher
        await repo.flush_activity()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
