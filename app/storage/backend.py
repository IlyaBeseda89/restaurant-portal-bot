"""Нижний уровень хранения: «таблица → строки».

Любое хранилище (SQLite, Google Sheets, в будущем облачная БД) реализует
четыре операции из TableBackend. Вся остальная логика лежит в Repository
и от конкретного хранилища не зависит. Так выполняется требование ТЗ
о едином слое хранения.
"""

from __future__ import annotations

import asyncio
import time
from typing import Protocol

Row = dict[str, str]


class TableBackend(Protocol):
    async def read_all(self, table: str) -> list[Row]: ...

    async def append(self, table: str, row: Row) -> None: ...

    async def append_many(self, table: str, rows: list[Row]) -> None: ...

    async def update(self, table: str, key_column: str, key: str, changes: Row) -> bool: ...

    async def ensure_tables(self) -> None: ...


class CachedBackend:
    """Кэш чтения поверх любого хранилища.

    Google Sheets ограничивает число запросов в минуту, поэтому таблицы
    читаются не чаще раза в ttl секунд. Правка в таблице видна боту
    не позже чем через ttl секунд. Своя запись сбрасывает кэш сразу.
    """

    def __init__(self, inner: TableBackend, ttl: float = 60.0) -> None:
        self.inner = inner
        self.ttl = ttl
        self._cache: dict[str, tuple[float, list[Row]]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, table: str) -> asyncio.Lock:
        return self._locks.setdefault(table, asyncio.Lock())

    async def read_all(self, table: str) -> list[Row]:
        async with self._lock(table):
            cached = self._cache.get(table)
            if cached and time.monotonic() - cached[0] < self.ttl:
                return cached[1]
            rows = await self.inner.read_all(table)
            self._cache[table] = (time.monotonic(), rows)
            return rows

    async def append(self, table: str, row: Row) -> None:
        await self.inner.append(table, row)
        self._cache.pop(table, None)

    async def append_many(self, table: str, rows: list[Row]) -> None:
        if rows:
            await self.inner.append_many(table, rows)
            self._cache.pop(table, None)

    async def update(self, table: str, key_column: str, key: str, changes: Row) -> bool:
        ok = await self.inner.update(table, key_column, key, changes)
        self._cache.pop(table, None)
        return ok

    async def ensure_tables(self) -> None:
        await self.inner.ensure_tables()

    def invalidate(self) -> None:
        self._cache.clear()
