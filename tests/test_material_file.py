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
