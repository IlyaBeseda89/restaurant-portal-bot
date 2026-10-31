"""Хранилище в локальном файле SQLite: для разработки, тестов и демо без Google."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from app.schema import TABLES
from app.storage.backend import Row


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class SqliteBackend:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = asyncio.Lock()

    def _ensure_sync(self) -> None:
        for table, columns in TABLES.items():
            cols = ", ".join(f"{_q(c)} TEXT NOT NULL DEFAULT ''" for c in columns)
            self._conn.execute(f"CREATE TABLE IF NOT EXISTS {_q(table)} ({cols})")
            existing = {r[1] for r in self._conn.execute(f"PRAGMA table_info({_q(table)})")}
            for c in columns:
                if c not in existing:
                    self._conn.execute(
                        f"ALTER TABLE {_q(table)} ADD COLUMN {_q(c)} TEXT NOT NULL DEFAULT ''"
                    )
        self._conn.commit()

    async def ensure_tables(self) -> None:
        async with self._lock:
            self._ensure_sync()

    async def read_all(self, table: str) -> list[Row]:
        async with self._lock:
            cur = self._conn.execute(f"SELECT * FROM {_q(table)} ORDER BY rowid")
            return [{k: (r[k] or "") for k in r.keys()} for r in cur.fetchall()]

    async def append(self, table: str, row: Row) -> None:
        await self.append_many(table, [row])

    async def append_many(self, table: str, rows: list[Row]) -> None:
        cols = TABLES[table]
        sql = (
            f"INSERT INTO {_q(table)} ({', '.join(_q(c) for c in cols)}) "
            f"VALUES ({', '.join('?' for _ in cols)})"
        )
        async with self._lock:
            self._conn.executemany(sql, [[str(r.get(c, "")) for c in cols] for r in rows])
            self._conn.commit()

    async def update(self, table: str, key_column: str, key: str, changes: Row) -> bool:
        cols = [c for c in changes if c in TABLES[table]]
        if not cols:
            return False
        sql = (
            f"UPDATE {_q(table)} SET {', '.join(f'{_q(c)} = ?' for c in cols)} "
            f"WHERE {_q(key_column)} = ?"
        )
        async with self._lock:
            cur = self._conn.execute(sql, [str(changes[c]) for c in cols] + [str(key)])
            self._conn.commit()
            return cur.rowcount > 0

    async def delete_rows(self, table: str, ids: list[str]) -> int:
        """Удаляет строки по id (для очистки старого журнала). Возвращает число удалённых."""
        deleted = 0
        async with self._lock:
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                cur = self._conn.execute(
                    f"DELETE FROM {_q(table)} WHERE {_q('id')} IN ({', '.join('?' for _ in chunk)})", chunk,
                )
                deleted += cur.rowcount
            self._conn.commit()
        return deleted
