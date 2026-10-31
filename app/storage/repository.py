"""Repository — единственная точка, через которую диалоги бота получают данные.

Обработчики сообщений не знают, лежат данные в SQLite, Google Sheets или
в облачной БД. Они вызывают методы этого класса.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from app import schema as S
from app.models import (
    Category, Concept, Employee, Feedback, Material, Restaurant,
    normalize_name, parse_bool, parse_date, parse_int,
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
    )


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
        return [Concept(id=r["id"], name=r.get("название", "")) for r in rows if r.get("id")]

    async def concept_of(self, employee: Employee) -> str | None:
        """Концепция сотрудника по его ресторану. None — видит все концепции."""
        if not employee.restaurant_id:
            return None
        restaurant = await self.get_restaurant(employee.restaurant_id)
        return restaurant.concept_id if restaurant and restaurant.concept_id else None

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
