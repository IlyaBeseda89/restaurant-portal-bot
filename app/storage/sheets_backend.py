"""Хранилище в Google Sheets: одна книга, по листу на таблицу.

Строку заголовков бот берёт из самой таблицы, поэтому колонки можно
переставлять и добавлять свои: бот ищет нужные колонки по названию.
"""

from __future__ import annotations

import asyncio

import gspread

from app.schema import TABLES
from app.storage.backend import Row


class SheetsBackend:
    def __init__(self, credentials_file: str, spreadsheet_id: str) -> None:
        self._client = gspread.service_account(filename=credentials_file)
        self._book = self._client.open_by_key(spreadsheet_id)
        self._ws: dict[str, gspread.Worksheet] = {}
        self._lock = asyncio.Lock()

    def _worksheet(self, table: str) -> gspread.Worksheet:
        if table not in self._ws:
            self._ws[table] = self._book.worksheet(table)
        return self._ws[table]

    # --- синхронные вызовы gspread, выполняются в отдельном потоке ---

    def _read_sync(self, table: str) -> list[Row]:
        values = self._worksheet(table).get_all_values()
        if not values:
            return []
        header = [h.strip() for h in values[0]]
        rows = []
        for raw in values[1:]:
            if not any(cell.strip() for cell in raw):
                continue  # пустые строки пропускаем
            row = {h: (raw[i].strip() if i < len(raw) else "") for i, h in enumerate(header) if h}
            for col in TABLES[table]:
                row.setdefault(col, "")
            rows.append(row)
        return rows

    def _append_sync(self, table: str, rows: list[Row]) -> None:
        ws = self._worksheet(table)
        header = [h.strip() for h in ws.row_values(1)]
        # RAW — чтобы «+7999…» и коды не превращались в числа и формулы
        ws.append_rows(
            [[str(r.get(h, "")) for h in header] for r in rows],
            value_input_option="RAW",
            insert_data_option="INSERT_ROWS",
        )

    def _update_sync(self, table: str, key_column: str, key: str, changes: Row) -> bool:
        ws = self._worksheet(table)
        values = ws.get_all_values()
        if not values:
            return False
        header = [h.strip() for h in values[0]]
        if key_column not in header:
            return False
        key_idx = header.index(key_column)
        for row_no, raw in enumerate(values[1:], start=2):
            if key_idx < len(raw) and raw[key_idx].strip() == str(key):
                cells = []
                for col, val in changes.items():
                    if col in header:
                        cells.append(
                            gspread.Cell(row=row_no, col=header.index(col) + 1, value=str(val))
                        )
                if cells:
                    ws.update_cells(cells, value_input_option="RAW")
                return True
        return False

    def _ensure_sync(self) -> None:
        existing = {ws.title: ws for ws in self._book.worksheets()}
        for table, columns in TABLES.items():
            ws = existing.get(table)
            if ws is None:
                ws = self._book.add_worksheet(title=table, rows=200, cols=max(len(columns), 10))
                ws.update([columns], "A1", value_input_option="RAW")
                ws.freeze(rows=1)
                continue
            header = [h.strip() for h in ws.row_values(1)]
            missing = [c for c in columns if c not in header]
            if missing:
                new_header = header + missing
                if ws.col_count < len(new_header):
                    ws.add_cols(len(new_header) - ws.col_count)
                ws.update([new_header], "A1", value_input_option="RAW")

    # --- асинхронный интерфейс TableBackend ---

    async def read_all(self, table: str) -> list[Row]:
        async with self._lock:
            return await asyncio.to_thread(self._read_sync, table)

    async def append(self, table: str, row: Row) -> None:
        await self.append_many(table, [row])

    async def append_many(self, table: str, rows: list[Row]) -> None:
        if not rows:
            return
        async with self._lock:
            await asyncio.to_thread(self._append_sync, table, rows)

    async def update(self, table: str, key_column: str, key: str, changes: Row) -> bool:
        async with self._lock:
            return await asyncio.to_thread(self._update_sync, table, key_column, key, changes)

    async def ensure_tables(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._ensure_sync)
