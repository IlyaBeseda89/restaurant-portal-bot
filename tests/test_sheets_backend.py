"""Логика SheetsBackend на подделке листа Google (без сети)."""


from app import schema as S
from app.storage.sheets_backend import SheetsBackend


class FakeWorksheet:
    def __init__(self, title, values):
        self.title = title
        self.values = values
        self.col_count = 26

    def get_all_values(self):
        return [list(r) for r in self.values]

    def row_values(self, n):
        return list(self.values[n - 1]) if len(self.values) >= n else []

    def append_rows(self, rows, value_input_option=None, insert_data_option=None):
        assert value_input_option == "RAW"
        self.values.extend(rows)

    def update_cells(self, cells, value_input_option=None):
        for c in cells:
            row = self.values[c.row - 1]
            while len(row) < c.col:
                row.append("")
            row[c.col - 1] = c.value


class FakeBook:
    def __init__(self, sheets):
        self.sheets = sheets

    def worksheet(self, title):
        return self.sheets[title]

    def worksheets(self):
        return list(self.sheets.values())


def make_backend(sheets):
    b = SheetsBackend.__new__(SheetsBackend)
    import asyncio

    b._book = FakeBook(sheets)
    b._ws = {}
    b._lock = asyncio.Lock()
    return b


async def test_reads_by_header_name_with_reordered_and_extra_columns():
    ws = FakeWorksheet(S.RESTAURANTS, [
        ["название", "Заметки HR", "id", "активен"],
        ["Ресторан А", "что-то", "r1", "да"],
        ["", "", "", ""],
        ["Ресторан Б", "", "r2"],
    ])
    b = make_backend({S.RESTAURANTS: ws})
    rows = await b.read_all(S.RESTAURANTS)
    assert [r["id"] for r in rows] == ["r1", "r2"]
    assert rows[1]["активен"] == "" and rows[0]["город"] == ""


async def test_append_and_update_follow_header_order():
    ws = FakeWorksheet(S.FEEDBACK, [["текст", "id", "статус"]])
    b = make_backend({S.FEEDBACK: ws})
    await b.append(S.FEEDBACK, {"id": "1", "текст": "+7 999", "статус": "новое", "лишнее": "x"})
    assert ws.values[1] == ["+7 999", "1", "новое"]
    assert await b.update(S.FEEDBACK, "id", "1", {"статус": "закрыто"})
    assert ws.values[1][2] == "закрыто"
    assert not await b.update(S.FEEDBACK, "id", "404", {"статус": "закрыто"})
