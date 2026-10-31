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
    knowledge._sent_slides.clear()
    yield
    knowledge._sent_files.clear()
    knowledge._sent_slides.clear()


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


def make_pdf(pages: int) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=1440, height=810)
        page.insert_text((100, 400), f"Slide {i + 1}", fontsize=60)
    return doc.tobytes()


def photos_sent(h):
    out = []
    for c in h.session.calls:
        name = type(c).__name__
        if name == "SendMediaGroup":
            out.append(("group", len(c.media)))
        elif name == "SendPhoto":
            out.append(("photo", 1))
    return out


async def open_pdf_material(h, repo, monkeypatch, pages):
    calls = []

    async def fake_download(url):
        calls.append(url)
        return make_pdf(pages), "x.pdf"

    monkeypatch.setattr(knowledge, "download_drive_file", fake_download)
    await add_file_material(repo)
    await register(h, 100, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await h.click(100, "kb:mat:50")
    return calls


async def test_pdf_is_sent_as_slide_albums(h, repo, monkeypatch):
    calls = await open_pdf_material(h, repo, monkeypatch, pages=12)
    assert photos_sent(h) == [("group", 10), ("group", 2)]
    assert not documents(h)
    assert "kb:pdf:50" in str(h.last_markup(100))
    # второй раз слайды берутся из кэша, Диск не трогаем
    await h.click(100, "kb:mat:50")
    assert len(calls) == 1 and len(photos_sent(h)) == 4


async def test_single_leftover_slide_sent_as_photo(h, repo, monkeypatch):
    await open_pdf_material(h, repo, monkeypatch, pages=11)
    assert photos_sent(h) == [("group", 10), ("photo", 1)]


async def test_pdf_button_sends_document(h, repo, monkeypatch):
    await open_pdf_material(h, repo, monkeypatch, pages=2)
    await h.click(100, "kb:pdf:50")
    assert len(documents(h)) == 1


def test_render_pdf_limits():
    import pytest

    from app.slides import render_pdf

    pages = render_pdf(make_pdf(3))
    assert len(pages) == 3 and pages[0][:2] == b"\xff\xd8"
    with pytest.raises(ValueError):
        render_pdf(make_pdf(3), max_pages=2)
    with pytest.raises(Exception):  # noqa: B017
        render_pdf(b"not a pdf")
