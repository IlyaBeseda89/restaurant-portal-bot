from app.drive import direct_download_url, drive_file_id
from tests.conftest import register


def test_drive_urls():
    url = "https://drive.google.com/file/d/1MZomV7QkAabaLE29QE9d4YCCUBElWPS2/view"
    assert drive_file_id(url) == "1MZomV7QkAabaLE29QE9d4YCCUBElWPS2"
    assert direct_download_url(url).endswith("export=download&id=1MZomV7QkAabaLE29QE9d4YCCUBElWPS2")
    assert direct_download_url("https://example.com/a.pdf") is None


async def test_drive_file_material_is_sent_as_document(h, repo):
    await repo.backend.append("Материалы", {
        "id": "50", "категория_id": "safety", "название": "Хранение", "тип": "файл",
        "url": "https://drive.google.com/file/d/1MZomV7QkAabaLE29QE9d4YCCUBElWPS2/view",
        "концепция_id": "все", "для_новичков": "да", "порядок": "5", "активен": "да",
    })
    await register(h, 100, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await h.click(100, "kb:mat:50")
    docs = [c for c in h.session.calls if type(c).__name__ == "SendDocument"]
    assert len(docs) == 1 and "export=download" in docs[0].document


async def test_other_material_stays_link(h, repo):
    await register(h, 100, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await h.click(100, "kb:mat:1")
    assert not [c for c in h.session.calls if type(c).__name__ == "SendDocument"]
