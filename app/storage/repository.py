"""Repository — единственная точка, через которую диалоги бота получают данные.

Обработчики сообщений не знают, лежат данные в SQLite, Google Sheets или
в облачной БД. Они вызывают методы этого класса.
"""

from __future__ import annotations

import asyncio
import secrets
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app import schema as S
from app.models import (
    Category,
    Concept,
    Employee,
    Event,
    Feedback,
    Material,
    Product,
    Restaurant,
    Topic,
    TrainingRequest,
    normalize_name,
    parse_bool,
    parse_date,
    parse_datetime,
    parse_int,
)
from app.roles import Role
from app.storage.backend import Row, TableBackend


def _employee(row: Row) -> Employee | None:
    role = Role.parse(row.get("роль"))
    if role is None:
        role = Role.EMPLOYEE
    newbie_raw = row.get("новичок", "").strip()
    tg = row.get("telegram_id", "").strip()
    return Employee(
        id=row.get("id", "").strip() or row.get("пригласительный_код", "").strip(),
        telegram_id=parse_int(tg) if tg else None,
        full_name=row.get("фио", "").strip(),
        phone=row.get("телефон", "").strip(),
        restaurant_id=row.get("ресторан_id", "").strip(),
        position=row.get("должность", "").strip(),
        role=role,
        start_date=parse_date(row.get("дата_старта")),
        active=parse_bool(row.get("активен"), default=True),
        invite_code=row.get("пригласительный_код", "").strip(),
        newbie_override=parse_bool(newbie_raw) if newbie_raw else None,
        all_concepts=(
            parse_bool(row.get("все_концепции")) if row.get("все_концепции", "").strip() else None
        ),
    )


CROSS_CONCEPT_ROLES = {Role.TU, Role.TRAINING_MANAGER, Role.HR}


class Repository:
    def __init__(self, backend: TableBackend, timezone: str = "Europe/Moscow") -> None:
        self.backend = backend
        self.tz = ZoneInfo(timezone)
        self._id_lock = asyncio.Lock()
        self._activity_buffer: list[Row] = []

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def _now_str(self) -> str:
        return self.now().strftime("%d.%m.%Y %H:%M")

    async def _next_id(self, table: str) -> str:
        rows = await self.backend.read_all(table)
        return str(max((parse_int(r.get("id"), 0) for r in rows), default=0) + 1)

    # ---------- сотрудники ----------

    async def list_employees(self) -> list[Employee]:
        rows = await self.backend.read_all(S.EMPLOYEES)
        return [e for e in (_employee(r) for r in rows) if e and e.full_name]

    async def get_employee_by_telegram(self, telegram_id: int) -> Employee | None:
        for e in await self.list_employees():
            if e.telegram_id == telegram_id:
                return e
        return None

    async def get_employee_by_code(self, code: str) -> Employee | None:
        code = code.strip().lower()
        if not code:
            return None
        for e in await self.list_employees():
            if e.invite_code.lower() == code:
                return e
        return None

    async def find_unbound_by_name(self, full_name: str) -> list[Employee]:
        target = normalize_name(full_name)
        return [
            e for e in await self.list_employees()
            if normalize_name(e.full_name) == target and e.telegram_id is None and e.active
        ]

    async def bind_telegram(self, employee: Employee, telegram_id: int, phone: str) -> bool:
        changes = {"telegram_id": str(telegram_id)}
        if phone and not employee.phone:
            changes["телефон"] = phone
        key_col = "id" if employee.id != employee.invite_code else "пригласительный_код"
        return await self.backend.update(S.EMPLOYEES, key_col, employee.id, changes)

    # ---------- справочники ----------

    async def list_restaurants(self, active_only: bool = True) -> list[Restaurant]:
        rows = await self.backend.read_all(S.RESTAURANTS)
        items = [
            Restaurant(
                id=r["id"], name=r.get("название", ""), concept_id=r.get("концепция_id", ""),
                city=r.get("город", ""), address=r.get("адрес", ""),
                active=parse_bool(r.get("активен")),
            )
            for r in rows if r.get("id")
        ]
        return [x for x in items if x.active or not active_only]

    async def get_restaurant(self, restaurant_id: str) -> Restaurant | None:
        for r in await self.list_restaurants(active_only=False):
            if r.id == restaurant_id:
                return r
        return None

    async def list_concepts(self) -> list[Concept]:
        rows = await self.backend.read_all(S.CONCEPTS)
        return [
            Concept(id=r["id"], name=r.get("название", ""), moderator_id=r.get("модератор_id", "").strip())
            for r in rows if r.get("id")
        ]

    async def concept_of(self, employee: Employee) -> str | None:
        """К какой концепции относится сотрудник.

        None  — работает со всеми концепциями: ТУ, менеджер по обучению, HR, а также любой,
                кому в таблице «Сотрудники» стоит «да» в колонке «все_концепции»
                («нет» там отключает это даже для таких ролей);
        "…"   — id его концепции (по ресторану, а у модератора по листу «Концепции»);
        ""    — определить не удалось (нет ресторана, у ресторана нет концепции):
                такой сотрудник видит только общие материалы, чужое не показывается.
        """
        if employee.all_concepts is True:
            return None
        if employee.role is Role.MODERATOR:
            for c in await self.list_concepts():
                if c.moderator_id and c.moderator_id == employee.id:
                    return c.id
        elif employee.all_concepts is None and employee.role in CROSS_CONCEPT_ROLES:
            return None
        if employee.restaurant_id:
            restaurant = await self.get_restaurant(employee.restaurant_id)
            if restaurant and restaurant.concept_id.strip():
                return restaurant.concept_id.strip()
        return ""

    # ---------- база знаний ----------

    async def list_categories(self) -> list[Category]:
        rows = await self.backend.read_all(S.CATEGORIES)
        cats = [
            Category(id=r["id"], name=r.get("название", ""), order=parse_int(r.get("порядок"), 100))
            for r in rows if r.get("id") and parse_bool(r.get("активен"))
        ]
        return sorted(cats, key=lambda c: (c.order, c.name))

    async def list_materials(
        self, concept_id: str | None, category_id: str | None = None
    ) -> list[Material]:
        rows = await self.backend.read_all(S.MATERIALS)
        items = []
        for r in rows:
            if not r.get("id") or not parse_bool(r.get("активен")):
                continue
            m = Material(
                id=r["id"], category_id=r.get("категория_id", ""), title=r.get("название", ""),
                kind=r.get("тип", "ссылка"), url=r.get("url", ""),
                concept_id=r.get("концепция_id", ""),
                for_newbies=parse_bool(r.get("для_новичков"), default=False),
                order=parse_int(r.get("порядок"), 100),
            )
            if not m.visible_for_concept(concept_id):
                continue
            if category_id is not None and m.category_id != category_id:
                continue
            items.append(m)
        return sorted(items, key=lambda m: (m.order, m.title))

    async def get_material(self, material_id: str) -> Material | None:
        for m in await self.list_materials(concept_id=None):
            if m.id == material_id:
                return m
        return None

    # ---------- карточки продуктов ----------

    async def list_products(
        self, concept_id: str | None, category: str | None = None
    ) -> list[Product]:
        """Активные карточки концепции сотрудника (и общие) в порядке строк таблицы."""
        items = []
        for r in await self.backend.read_all(S.PRODUCTS):
            if not r.get("id") or not r.get("название", "").strip():
                continue
            if not parse_bool(r.get("активен")):
                continue
            p = Product(
                id=r["id"], concept_id=r.get("концепция_id", ""),
                category=r.get("категория_меню", "").strip() or "Без категории",
                name=r["название"].strip(), photo_url=r.get("фото_url", "").strip(),
                ingredients=r.get("состав", "").strip(), allergens=r.get("аллергены", "").strip(),
                method=r.get("метод_приготовления", "").strip(),
                pairings=r.get("сочетания", "").strip(),
                storytelling=r.get("сторителлинг", "").strip(),
            )
            if not p.visible_for_concept(concept_id):
                continue
            if category is not None and p.category != category:
                continue
            items.append(p)
        return items

    async def list_product_categories(self, concept_id: str | None) -> list[str]:
        seen: dict[str, None] = {}
        for p in await self.list_products(concept_id):
            seen.setdefault(p.category)
        return list(seen)

    async def get_product(self, product_id: str, concept_id: str | None) -> Product | None:
        for p in await self.list_products(concept_id):
            if p.id == product_id:
                return p
        return None

    # ---------- админка: правки из бота ----------

    @staticmethod
    def new_invite_code() -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        return "".join(secrets.choice(alphabet) for _ in range(8))

    async def add_employee(self, full_name: str, restaurant_id: str, position: str, role: Role) -> Employee:
        """Новый сотрудник с пригласительным кодом. Telegram привяжется при входе по ссылке."""
        async with self._id_lock:
            employee_id = await self._next_id(S.EMPLOYEES)
            code = self.new_invite_code()
            await self.backend.append(S.EMPLOYEES, {
                "id": employee_id, "telegram_id": "", "фио": full_name.strip(), "телефон": "",
                "ресторан_id": restaurant_id, "должность": position.strip(), "роль": role.value,
                "дата_старта": self.now().strftime("%d.%m.%Y"), "дата_добавления": self.now().strftime("%d.%m.%Y"),
                "активен": "да", "пригласительный_код": code,
            })
        created = await self.get_employee(employee_id)
        assert created is not None
        return created

    async def update_employee(self, employee_id: str, **changes: str) -> bool:
        return await self.backend.update(S.EMPLOYEES, "id", employee_id, changes)

    async def find_employees(self, query: str, limit: int = 8) -> list[Employee]:
        q = normalize_name(query)
        if not q:
            return []
        found = [e for e in await self.list_employees() if q in normalize_name(e.full_name)]
        return sorted(found, key=lambda e: normalize_name(e.full_name))[:limit]

    async def add_material(
        self, category_id: str, title: str, kind: str, url: str, concept_id: str, for_newbies: bool,
    ) -> str:
        async with self._id_lock:
            material_id = await self._next_id(S.MATERIALS)
            rows = await self.backend.read_all(S.MATERIALS)
            order = 1 + max(
                (parse_int(r.get("порядок"), 0) for r in rows if r.get("категория_id") == category_id), default=0,
            )
            await self.backend.append(S.MATERIALS, {
                "id": material_id, "категория_id": category_id, "название": title.strip(), "тип": kind,
                "url": url.strip(), "концепция_id": concept_id, "для_новичков": "да" if for_newbies else "нет",
                "порядок": str(order), "активен": "да",
            })
        return material_id

    async def update_material(self, material_id: str, **changes: str) -> bool:
        return await self.backend.update(S.MATERIALS, "id", material_id, changes)

    async def add_product(
        self, concept_id: str, category: str, name: str, photo_url: str, ingredients: str,
        allergens: str, method: str, pairings: str, storytelling: str,
    ) -> str:
        async with self._id_lock:
            product_id = await self._next_id(S.PRODUCTS)
            await self.backend.append(S.PRODUCTS, {
                "id": product_id, "концепция_id": concept_id, "категория_меню": category.strip(),
                "название": name.strip(), "фото_url": photo_url.strip(), "состав": ingredients,
                "аллергены": allergens, "метод_приготовления": method, "сочетания": pairings,
                "сторителлинг": storytelling, "дата_обновления": self.now().strftime("%d.%m.%Y"),
                "активен": "да",
            })
        return product_id

    async def update_product(self, product_id: str, **changes: str) -> bool:
        return await self.backend.update(S.PRODUCTS, "id", product_id, changes)

    # ---------- прогресс и статистика ----------

    async def done_ids(self, employee_id: str, kind: str) -> set[str]:
        """Что сотрудник уже отметил изученным (лист «Прогресс»)."""
        return {
            r.get("объект_id", "") for r in await self.backend.read_all(S.PROGRESS)
            if r.get("сотрудник_id") == employee_id and r.get("тип") == kind
        }

    async def all_progress(self, kind: str) -> dict[str, set[str]]:
        """сотрудник_id → id изученных объектов."""
        result: dict[str, set[str]] = {}
        for r in await self.backend.read_all(S.PROGRESS):
            if r.get("тип") == kind:
                result.setdefault(r.get("сотрудник_id", ""), set()).add(r.get("объект_id", ""))
        return result

    async def activity_since(self, days: int) -> list[dict]:
        """Записи журнала за последние дни (сначала сбрасывает буфер в таблицу)."""
        await self.flush_activity()
        limit = self.now().replace(tzinfo=None) - timedelta(days=days)
        rows = []
        for r in await self.backend.read_all(S.ACTIVITY):
            when = parse_datetime(r.get("дата"))
            if when and when >= limit:
                rows.append({**r, "when": when})
        return rows

    async def feedback_since(self, days: int) -> list[dict]:
        limit = self.now().replace(tzinfo=None) - timedelta(days=days)
        rows = []
        for r in await self.backend.read_all(S.FEEDBACK):
            when = parse_datetime(r.get("дата"))
            if when and when >= limit:
                rows.append(r)
        return rows

    # ---------- тренинги: темы, расписание, заявки ----------

    async def list_topics(self, active_only: bool = True) -> list[Topic]:
        topics = [
            Topic(
                id=r["id"], name=r.get("название", "").strip(), format=r.get("формат", "").strip().lower(),
                description=r.get("описание", "").strip(), duration=r.get("длительность", "").strip(),
            )
            for r in await self.backend.read_all(S.TOPICS)
            if r.get("id") and r.get("название", "").strip()
            and (not active_only or parse_bool(r.get("активен")))
        ]
        return topics

    async def get_topic(self, topic_id: str) -> Topic | None:
        for t in await self.list_topics(active_only=False):
            if t.id == topic_id:
                return t
        return None

    @staticmethod
    def _event(r: Row) -> Event:
        return Event(
            id=r["id"], topic_id=r.get("тема_id", "").strip(), start=parse_datetime(r.get("дата_время")),
            format=r.get("формат", "").strip().lower(), venue=r.get("площадка", "").strip(),
            host=r.get("ведущий", "").strip(), capacity=parse_int(r.get("вместимость"), 0),
            enrolled=parse_int(r.get("записано"), 0), status=r.get("статус", "").strip().lower() or "план",
            reminded=parse_bool(r.get("напоминание"), default=False),
        )

    async def list_events(self) -> list[Event]:
        events = [self._event(r) for r in await self.backend.read_all(S.SCHEDULE) if r.get("id")]
        return sorted(events, key=lambda e: (e.start is None, e.start))

    async def get_event(self, event_id: str) -> Event | None:
        for e in await self.list_events():
            if e.id == event_id:
                return e
        return None

    def now_local(self) -> datetime:
        """Текущее время без часового пояса: даты в таблице тоже локальные."""
        return self.now().replace(tzinfo=None)

    async def upcoming_events(self) -> list[Event]:
        now = self.now_local()
        return [e for e in await self.list_events() if e.active and e.start and e.start >= now]

    async def add_event(
        self, topic_id: str, start: datetime, fmt: str, venue: str, host: str,
        enrolled: int = 0, status: str = "подтверждён",
    ) -> str:
        async with self._id_lock:
            event_id = await self._next_id(S.SCHEDULE)
            await self.backend.append(S.SCHEDULE, {
                "id": event_id, "тема_id": topic_id, "дата_время": start.strftime("%d.%m.%Y %H:%M"),
                "формат": fmt, "площадка": venue, "ведущий": host, "вместимость": "",
                "записано": str(enrolled), "статус": status, "напоминание": "",
            })
        return event_id

    async def update_event(self, event_id: str, **changes: str) -> bool:
        return await self.backend.update(S.SCHEDULE, "id", event_id, changes)

    @staticmethod
    def _request(r: Row) -> TrainingRequest:
        return TrainingRequest(
            id=r["id"], created=r.get("дата_создания", ""), restaurant_id=r.get("ресторан_id", "").strip(),
            applicant_id=r.get("заявитель_id", "").strip(), topic_id=r.get("тема_id", "").strip(),
            format=r.get("формат", "").strip().lower(), venue=r.get("площадка", "").strip(),
            desired_dates=r.get("желаемые_даты", ""), participants=r.get("участники", ""),
            count=parse_int(r.get("количество"), 0), status=r.get("статус", "").strip().lower() or "новая",
            comment=r.get("комментарий_менеджера", ""), decided=r.get("дата_решения", ""),
            event_id=r.get("событие_id", "").strip(),
        )

    async def list_requests(self) -> list[TrainingRequest]:
        return [self._request(r) for r in await self.backend.read_all(S.REQUESTS) if r.get("id")]

    async def get_request(self, request_id: str) -> TrainingRequest | None:
        for r in await self.list_requests():
            if r.id == request_id:
                return r
        return None

    async def add_request(
        self, restaurant_id: str, applicant_id: str, topic_id: str, fmt: str, venue: str,
        desired_dates: str, participants: str, count: int,
    ) -> str:
        async with self._id_lock:
            request_id = await self._next_id(S.REQUESTS)
            await self.backend.append(S.REQUESTS, {
                "id": request_id, "дата_создания": self._now_str(), "ресторан_id": restaurant_id,
                "заявитель_id": applicant_id, "тема_id": topic_id, "формат": fmt, "площадка": venue,
                "желаемые_даты": desired_dates, "участники": participants, "количество": str(count),
                "статус": "новая",
            })
        return request_id

    async def update_request(self, request_id: str, **changes: str) -> bool:
        return await self.backend.update(S.REQUESTS, "id", request_id, changes)

    async def get_employee(self, employee_id: str) -> Employee | None:
        for e in await self.list_employees():
            if e.id == employee_id:
                return e
        return None

    async def training_managers(self) -> list[Employee]:
        """Менеджеры по обучению, которые уже зарегистрировались в боте."""
        return [
            e for e in await self.list_employees()
            if e.role is Role.TRAINING_MANAGER and e.active and e.telegram_id
        ]

    async def match_participants(self, names: list[str]) -> tuple[list[Employee], list[str]]:
        """Находит среди зарегистрированных сотрудников тех, кто назван в заявке.

        Совпадением считается ФИО целиком или «Фамилия Имя» без отчества, но только если
        такой человек один. Возвращает (найденные, не найденные имена).
        """
        staff = [e for e in await self.list_employees() if e.active and e.telegram_id]
        found: dict[str, Employee] = {}
        missing: list[str] = []
        for name in names:
            tokens = normalize_name(name).split()
            hits = [
                e for e in staff
                if len(tokens) >= 2 and normalize_name(e.full_name).split()[:len(tokens)] == tokens
            ]
            if len(hits) == 1:
                found[hits[0].id] = hits[0]
            else:
                missing.append(name)
        return list(found.values()), missing

    # ---------- прогресс «изучено» ----------

    async def is_done(self, employee_id: str, kind: str, object_id: str) -> bool:
        return any(
            r.get("сотрудник_id") == employee_id and r.get("тип") == kind
            and r.get("объект_id") == object_id
            for r in await self.backend.read_all(S.PROGRESS)
        )

    async def mark_done(self, employee_id: str, kind: str, object_id: str) -> bool:
        """Отмечает изученным. False, если уже было отмечено раньше."""
        async with self._id_lock:
            if await self.is_done(employee_id, kind, object_id):
                return False
            await self.backend.append(S.PROGRESS, {
                "id": await self._next_id(S.PROGRESS), "сотрудник_id": employee_id,
                "тип": kind, "объект_id": object_id, "дата": self._now_str(),
            })
        return True

    # ---------- обратная связь ----------

    async def add_feedback(self, fb: Feedback) -> str:
        async with self._id_lock:
            fb.id = await self._next_id(S.FEEDBACK)
            await self.backend.append(S.FEEDBACK, {
                "id": fb.id,
                "дата": self._now_str(),
                "категория": fb.category,
                "ресторан_id": fb.restaurant_id,
                "анонимно": "да" if fb.anonymous else "нет",
                "контакт": "" if fb.anonymous else fb.contact,
                "текст": fb.text,
                "вложение": "да" if fb.has_attachment else "нет",
                "статус": "новое",
            })
        return fb.id

    async def set_feedback_status(self, feedback_id: str, status: str) -> bool:
        return await self.backend.update(S.FEEDBACK, "id", feedback_id, {"статус": status})

    # ---------- тексты ----------

    async def get_text(self, key: str, default: str = "") -> str:
        for r in await self.backend.read_all(S.TEXTS):
            if r.get("ключ", "").strip() == key and r.get("значение", "").strip():
                return r["значение"]
        return default

    # ---------- журнал активности ----------

    def log(self, employee_id: str, action: str, obj: str = "") -> None:
        """Пишет в буфер. В таблицу журнал уходит пачкой (см. flush_activity),
        чтобы не упираться в лимиты Google Sheets на запись."""
        self._activity_buffer.append({
            "id": uuid.uuid4().hex[:10],
            "дата": self._now_str(),
            "пользователь_id": employee_id,
            "действие": action,
            "объект": obj,
        })

    async def flush_activity(self) -> int:
        rows, self._activity_buffer = self._activity_buffer, []
        if rows:
            try:
                await self.backend.append_many(S.ACTIVITY, rows)
            except Exception:
                self._activity_buffer = rows + self._activity_buffer
                raise
        return len(rows)
