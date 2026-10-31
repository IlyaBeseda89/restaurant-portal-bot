import pytest

from app.drive import direct_download_url, drive_file_id
from app.handlers import knowledge
from tests.conftest import register

URL = "https://drive.google.com/file/d/1MZomV7QkAabaLE29QE9d4YCCUBElWPS2/view"


def test_drive_urls():
    assert drive_file_id(URL) == "1MZomV7QkAabaLE29QE9d4YCCUBElWPS2"
    assert "id=1MZomV7QkAabaLE29QE9d4YCCUBElWPS2" in direct_download_url(URL)
    assert direct_download_url("https://example.com/a.pdf") is None


@pytest.fixture(autouse=True)
def _clear_cache():
    knowledge._sent_files.clear()
    yield
    knowledge._sent_files.clear()


async def add_file_material(repo):
    await repo.backend.append("Материалы", {
        "id": "50", "категория_id": "safety", "название": "Хранение", "тип": "файл", "url": URL,
        "концепция_id": "все", "для_новичков": "да", "порядок": "5", "активен": "да",
    })


def documents(h):
    return [c for c in h.session.calls if type(c).__name__ == "SendDocument"]


async def test_drive_file_is_downloaded_and_sent(h, repo, monkeypatch):
    calls = []

    async def fake_download(url):
        calls.append(url)
        return b"%PDF-1.4 test", "Хранение.pdf"

    monkeypatch.setattr(knowledge, "download_drive_file", fake_download)
    await add_file_material(repo)
    await register(h, 100, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await h.click(100, "kb:mat:50")
    docs = documents(h)
    assert len(docs) == 1 and docs[0].document.filename == "Хранение.pdf"
    assert calls == [URL]


async def test_failed_download_falls_back_to_link(h, repo, monkeypatch):
    async def broken(url):
        raise RuntimeError("нет доступа")

    monkeypatch.setattr(knowledge, "download_drive_file", broken)
    await add_file_material(repo)
    await register(h, 100, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await h.click(100, "kb:mat:50")
    assert not documents(h)
    assert "Хранение" in h.last_text(100)


async def test_other_material_stays_link(h, repo):
    await register(h, 100, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await h.click(100, "kb:mat:1")
    assert not documents(h)


def test_confirm_form_parsing():
    from app.drive import looks_like_html, parse_confirm_form

    page = (
        '<html><form id="download-form" action="https://drive.usercontent.google.com/download" method="get">'
        '<input type="hidden" name="id" value="ABC"><input type="hidden" name="confirm" value="t">'
        '<input type="hidden" name="uuid" value="u&amp;1"></form></html>'
    )
    action, fields = parse_confirm_form(page)
    assert action.endswith("/download") and fields == {"id": "ABC", "confirm": "t", "uuid": "u&1"}
    assert looks_like_html(page.encode()) and looks_like_html(b'{"error": 1}')
    assert not looks_like_html(b"%PDF-1.7 ...") and not looks_like_html(b"PK\x03\x04")
    assert parse_confirm_form("<html>нет формы</html>") is None


async def test_read_limited_joins_all_chunks_and_enforces_limit():
    import pytest

    from app.drive import DriveError, read_limited

    async def chunks(*parts):
        for p in parts:
            yield p

    assert await read_limited(chunks(b"%PDF", b"-1.3 ", b"end"), 100) == b"%PDF-1.3 end"
    with pytest.raises(DriveError):
        await read_limited(chunks(b"x" * 60, b"y" * 60), 100)
