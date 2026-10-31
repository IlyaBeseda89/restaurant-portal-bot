"""Служебные команды.

    python -m app.cli init            создать таблицы/листы с нужными колонками
    python -m app.cli demo            заполнить пустую базу демо-данными
    python -m app.cli links           выдать коды сотрудникам без кода и показать ссылки
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
from datetime import date, timedelta

from app import schema as S
from app.config import Config, build_repository
from app.roles import Role
from app.storage.repository import Repository

LINK_ROLE = {
    Role.EMPLOYEE: "employee",
    Role.DIRECTOR: "director",
    Role.TU: "tu",
    Role.TRAINING_MANAGER: "trainer",
    Role.MODERATOR: "moderator",
    Role.HR: "hr",
}


def invite_link(bot_username: str, role: Role, code: str) -> str:
    return f"https://t.me/{bot_username}?start={LINK_ROLE[role]}_{code}"


def new_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


async def cmd_init(repo: Repository) -> None:
    await repo.backend.ensure_tables()
    print("Таблицы готовы:", ", ".join(S.TABLES))


async def _demo_trainings(repo: Repository) -> None:
    """Демо-темы тренингов и два тренинга в расписании. Грузятся, только если листы пусты."""
    b = repo.backend
    if not await b.read_all(S.TOPICS):
        await b.append_many(S.TOPICS, [
            {"id": "1", "название": "Сервис: знакомство с гостем", "формат": "оба", "описание": "Базовые стандарты сервиса", "длительность": "2 часа", "активен": "да"},
            {"id": "2", "название": "Пищевая безопасность", "формат": "онлайн", "описание": "Обязательный курс для всех", "длительность": "1 час", "активен": "да"},
            {"id": "3", "название": "Работа с кассой", "формат": "очно", "описание": "Практика на кассе", "длительность": "2 часа", "активен": "да"},
        ])
    if not await b.read_all(S.SCHEDULE):
        now = repo.now_local()
        for i, (topic, days, fmt, venue) in enumerate([("1", 7, "очно", "Ресторан на Тверской"), ("2", 14, "онлайн", "онлайн")]):
            start = (now + timedelta(days=days)).replace(hour=14, minute=0, second=0, microsecond=0)
            await repo.add_event(topic, start, fmt, venue, "Лебедева Ольга")


async def _demo_products(repo: Repository) -> None:
    """Демо-карточки блюд. Грузятся, только если лист «Карточки продуктов» пуст."""
    b = repo.backend
    if await b.read_all(S.PRODUCTS):
        return
    today = date.today()
    fmt = "%d.%m.%Y"

    def dish(i, concept, cat, name, photo, ing, allergens, method, pairings, story, active="да"):
        return {"id": i, "концепция_id": concept, "категория_меню": cat, "название": name,
                "фото_url": photo, "состав": ing, "аллергены": allergens,
                "метод_приготовления": method, "сочетания": pairings, "сторителлинг": story,
                "дата_обновления": today.strftime(fmt), "активен": active}

    await b.append_many(S.PRODUCTS, [
        dish("1", "trat", "Салаты", "Цезарь с курицей", "", "Ромэн, куриная грудка, пармезан, соус цезарь, гренки",
             "глютен, яйцо, молоко, рыба (в соусе)", "Курицу гриллим 4 минуты с каждой стороны. Подача на охлаждённой тарелке.",
             "Белое сухое вино, лимонад с базиликом", "Салат придумал шеф Цезарь Кардини в 1924 году."),
        dish("2", "trat", "Салаты", "Капрезе", "", "Томаты, моцарелла, базилик, оливковое масло",
             "молоко", "Подаём при комнатной температуре.", "Просекко", "Цвета салата повторяют флаг Италии."),
        dish("3", "trat", "Горячее", "Паста карбонара", "", "Спагетти, гуанчале, желток, пекорино, чёрный перец",
             "глютен, яйцо, молоко", "Соус на желтке без сливок, паста al dente.", "Красное лёгкое вино",
             "Классический римский рецепт, без сливок."),
        dish("4", "trat", "Горячее", "Лазанья болоньезе", "", "Листы пасты, рагу из говядины, бешамель, пармезан",
             "глютен, яйцо, молоко, сельдерей", "Запекаем 25 минут, даём постоять 3 минуты.", "Кьянти",
             "Готовим по бабушкиному рецепту из Болоньи."),
        dish("5", "trat", "Десерты", "Тирамису", "", "Маскарпоне, савоярди, эспрессо, какао, яичный крем",
             "", "Собираем слоями, настаиваем не менее 6 часов.", "Эспрессо, десертное вино",
             "В переводе «подними меня вверх»."),
        dish("6", "trat", "Десерты", "Скрытая карточка (не должна показываться)", "", "-", "", "-", "-", "-", active="нет"),
        dish("7", "bistro", "Бургеры", "Классический бургер", "", "Булочка бриошь, говяжья котлета, чеддер, пикули",
             "глютен, молоко, яйцо", "Прожарка medium, булочку подсушиваем на гриле.", "Крафтовый лагер",
             "Котлета из мраморной говядины."),
        dish("8", "все", "Напитки", "Домашний лимонад", "", "Лимон, мята, сахарный сироп, газированная вода",
             "", "Готовим порциями, подаём со льдом.", "Любые блюда", "Рецепт общий для всех концепций."),
    ])


async def cmd_demo(repo: Repository) -> None:
    await repo.backend.ensure_tables()
    if await repo.backend.read_all(S.EMPLOYEES):
        await _demo_products(repo)
        print("В таблице «Сотрудники» уже есть данные, их не трогаю. Демо-карточки блюд добавлены, если лист был пуст.")
        return
    b = repo.backend
    today = date.today()
    fmt = "%d.%m.%Y"

    await b.append_many(S.CONCEPTS, [
        {"id": "trat", "название": "Траттория", "модератор_id": "4"},
        {"id": "bistro", "название": "Бистро", "модератор_id": ""},
    ])
    await b.append_many(S.RESTAURANTS, [
        {"id": "r1", "название": "Траттория на Невском", "концепция_id": "trat", "город": "Санкт-Петербург", "адрес": "Невский пр., 1", "активен": "да"},
        {"id": "r2", "название": "Траттория на Садовой", "концепция_id": "trat", "город": "Санкт-Петербург", "адрес": "Садовая ул., 10", "активен": "да"},
        {"id": "r3", "название": "Бистро Центр", "концепция_id": "bistro", "город": "Москва", "адрес": "Тверская ул., 5", "активен": "да"},
    ])
    await b.append_many(S.CATEGORIES, [
        {"id": "start", "название": "🚀 Старт", "порядок": "1", "активен": "да"},
        {"id": "service", "название": "🤝 Стандарты сервиса", "порядок": "2", "активен": "да"},
        {"id": "menu", "название": "🍝 Меню и продукты", "порядок": "3", "активен": "да"},
        {"id": "safety", "название": "🦺 Безопасность", "порядок": "4", "активен": "да"},
        {"id": "career", "название": "📈 Карьера", "порядок": "5", "активен": "да"},
    ])
    await b.append_many(S.MATERIALS, [
        {"id": "1", "категория_id": "start", "название": "Добро пожаловать в компанию", "тип": "статья", "url": "https://telegra.ph/", "концепция_id": "все", "для_новичков": "да", "порядок": "1", "активен": "да"},
        {"id": "2", "категория_id": "start", "название": "Правила внутреннего распорядка", "тип": "файл", "url": "https://drive.google.com/", "концепция_id": "все", "для_новичков": "да", "порядок": "2", "активен": "да"},
        {"id": "3", "категория_id": "service", "название": "Шаги сервиса официанта", "тип": "статья", "url": "https://telegra.ph/", "концепция_id": "все", "для_новичков": "да", "порядок": "1", "активен": "да"},
        {"id": "4", "категория_id": "service", "название": "Как работать с жалобой гостя", "тип": "ссылка", "url": "https://example.com/", "концепция_id": "все", "для_новичков": "нет", "порядок": "2", "активен": "да"},
        {"id": "5", "категория_id": "menu", "название": "Итальянская кухня: основы", "тип": "статья", "url": "https://telegra.ph/", "концепция_id": "trat", "для_новичков": "да", "порядок": "1", "активен": "да"},
        {"id": "6", "категория_id": "menu", "название": "Меню бистро: что рекомендовать", "тип": "файл", "url": "https://drive.google.com/", "концепция_id": "bistro", "для_новичков": "да", "порядок": "1", "активен": "да"},
        {"id": "7", "категория_id": "safety", "название": "Пожарная безопасность", "тип": "файл", "url": "https://drive.google.com/", "концепция_id": "все", "для_новичков": "да", "порядок": "1", "активен": "да"},
        {"id": "8", "категория_id": "career", "название": "Карьерная лестница в компании", "тип": "статья", "url": "https://telegra.ph/", "концепция_id": "все", "для_новичков": "нет", "порядок": "1", "активен": "да"},
        {"id": "9", "категория_id": "career", "название": "Скрытый материал (не должен показываться)", "тип": "ссылка", "url": "https://example.com/", "концепция_id": "все", "для_новичков": "нет", "порядок": "2", "активен": "нет"},
    ])
    emp = [
        ("1", "Петрова Анна Сергеевна", "r1", "официант", "сотрудник", today - timedelta(days=200), "DEMOEMP1"),
        ("2", "Смирнов Олег Игоревич", "r1", "официант", "сотрудник", today - timedelta(days=3), "DEMONEW1"),
        ("3", "Кузнецов Илья Петрович", "r1", "директор ресторана", "директор", today - timedelta(days=500), "DEMODIR1"),
        ("4", "Волкова Мария Андреевна", "", "модератор концепции", "модератор", today - timedelta(days=400), "DEMOMOD1"),
        ("5", "Орлов Денис Викторович", "", "территориальный управляющий", "ТУ", today - timedelta(days=700), "DEMOTU01"),
        ("6", "Лебедева Ольга Николаевна", "", "менеджер по обучению", "менеджер по обучению", today - timedelta(days=300), "DEMOTRN1"),
        ("7", "Тестов Тест Тестович", "", "HR", "HR", today - timedelta(days=900), "DEMOHR01"),
    ]
    await b.append_many(S.EMPLOYEES, [
        {"id": i, "telegram_id": "", "фио": fio, "телефон": "", "ресторан_id": rid,
         "должность": pos, "роль": role, "дата_старта": start.strftime(fmt),
         "дата_добавления": today.strftime(fmt), "активен": "да",
         "пригласительный_код": code, "новичок": ""}
        for i, fio, rid, pos, role, start, code in emp
    ])
    await _demo_products(repo)
    await _demo_trainings(repo)
    await b.append_many(S.TEXTS, [
        {"ключ": "помощь", "значение": "❓ Помощь и контакты\n\nHR: Тестов Тест, +7 900 000-00-00\nМенеджер по обучению: Лебедева Ольга, @example\nТехподдержка портала: @example"},
    ])
    print("Демо-данные загружены. Ссылки: python -m app.cli links --bot <имя_бота>")


async def cmd_links(repo: Repository, bot_username: str, only_missing: bool) -> None:
    rows = await repo.backend.read_all(S.EMPLOYEES)
    used = {r.get("пригласительный_код", "").strip() for r in rows}
    for e in await repo.list_employees():
        if not e.active:
            continue
        if not e.invite_code:
            code = new_code()
            while code in used:
                code = new_code()
            used.add(code)
            await repo.backend.update(S.EMPLOYEES, "id", e.id, {"пригласительный_код": code})
            e.invite_code = code
        if only_missing and e.telegram_id:
            continue
        status = "зарегистрирован" if e.telegram_id else "ждёт регистрации"
        print(f"{e.full_name} ({e.role.title}, {status}):\n  {invite_link(bot_username, e.role, e.invite_code)}")


async def _resolve_bot_username(config: Config, explicit: str | None) -> str:
    if explicit:
        return explicit.lstrip("@")
    if not config.bot_token:
        raise SystemExit("Укажите --bot <имя_бота> или BOT_TOKEN в .env")
    from aiogram import Bot

    bot = Bot(config.bot_token)
    try:
        return (await bot.get_me()).username
    finally:
        await bot.session.close()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Служебные команды портала")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("demo")
    links = sub.add_parser("links")
    links.add_argument("--bot", help="имя бота без @ (иначе возьмётся из BOT_TOKEN)")
    links.add_argument("--new", action="store_true", help="только ещё не зарегистрированные")
    args = parser.parse_args()

    config = Config.from_env()
    repo = build_repository(config)
    if args.cmd == "init":
        await cmd_init(repo)
    elif args.cmd == "demo":
        await cmd_demo(repo)
    elif args.cmd == "links":
        await cmd_links(repo, await _resolve_bot_username(config, args.bot), args.new)


if __name__ == "__main__":
    asyncio.run(main())
