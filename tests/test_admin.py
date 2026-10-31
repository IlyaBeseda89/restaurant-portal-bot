from app.keyboards import BTN_ADMIN
from tests.conftest import register


def data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row] if markup else []


async def reg(h):
    await register(h, 100, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await register(h, 400, "moderator_DEMOMOD1", "Волкова Мария Андреевна")
    await register(h, 600, "trainer_DEMOTRN1", "Лебедева Ольга Николаевна")
    await register(h, 700, "hr_DEMOHR01", "Тестов Тест Тестович")


async def test_employee_has_no_admin(h):
    await reg(h)
    await h.send(100, BTN_ADMIN)
    assert "Админка" not in h.last_text(100)
    await h.click(100, "ad:ea")
    assert all("ФИО" not in (c.text or "") for c in h.session.calls if type(c).__name__ == "SendMessage")


async def test_hr_adds_employee_and_gets_link(h, repo):
    await reg(h)
    await h.send(700, BTN_ADMIN)
    assert "Админка" in h.last_text(700)
    await h.click(700, "ad:ea")
    await h.send(700, "Новиков Павел Игоревич")
    await h.click(700, "ad:ar:employee")
    await h.click(700, "ad:as:r1")
    await h.send(700, "официант")
    await h.click(700, "ad:ag:auto")
    text = [c.text for c in h.session.sent(700)][-1]
    assert "t.me/" in text and "start=employee_" in text
    new = (await repo.find_employees("Новиков"))[0]
    assert new.role.value == "сотрудник" and new.active and new.invite_code in text
    # новый сотрудник регистрируется по ссылке
    await register(h, 800, f"employee_{new.invite_code}", "Новиков Павел Игоревич")
    assert (await repo.get_employee(new.id)).telegram_id == 800


async def test_manager_cannot_assign_hr(h, repo):
    await reg(h)
    await h.send(600, BTN_ADMIN)
    await h.click(600, "ad:ea")
    await h.send(600, "Новиков Павел Игоревич")
    assert "ad:ar:hr" not in data(h.last_markup(600))
    await h.click(600, "ad:ar:hr")
    assert await repo.find_employees("Новиков") == []


async def test_disable_and_role_change(h, repo):
    await reg(h)
    emp = (await repo.find_employees("Петрова"))[0]
    await h.click(700, f"ad:ex:{emp.id}")
    assert not (await repo.get_employee(emp.id)).active
    await h.click(700, f"ad:ex:{emp.id}")
    await h.click(700, f"ad:erv:{emp.id}:director")
    assert (await repo.get_employee(emp.id)).role.value == "директор"


async def test_cannot_touch_self_or_hr_by_manager(h, repo):
    await reg(h)
    hr = (await repo.find_employees("Тестов"))[0]
    me = (await repo.find_employees("Лебедева"))[0]
    await h.click(600, f"ad:ex:{hr.id}")
    assert (await repo.get_employee(hr.id)).active
    await h.click(700, f"ad:ex:{hr.id}")  # HR себя не отключит
    assert (await repo.get_employee(hr.id)).active
    await h.click(600, f"ad:erv:{me.id}:hr")
    assert (await repo.get_employee(me.id)).role.value == "менеджер по обучению"


async def test_add_and_hide_material(h, repo):
    await reg(h)
    cat = (await repo.list_categories())[0]
    before = len(await repo.list_materials(concept_id=None))
    await h.click(700, "ad:ma")
    await h.click(700, f"ad:mc:{cat.id}")
    await h.send(700, "Тестовый материал")
    await h.send(700, "https://example.com/a")
    await h.click(700, "ad:mn:all")
    await h.click(700, "ad:mg:all")
    await h.click(700, "ad:mb:1")
    items = await repo.list_materials(concept_id=None)
    assert len(items) == before + 1
    new = next(m for m in items if m.title == "Тестовый материал")
    assert new.concept_id == "все" and new.for_newbies and new.kind == "ссылка"
    await h.click(700, f"ad:mx:{new.id}")
    assert all(m.id != new.id for m in await repo.list_materials(concept_id=None))


async def test_drive_file_detected(h, repo):
    await reg(h)
    cat = (await repo.list_categories())[0]
    await h.click(700, "ad:ma")
    await h.click(700, f"ad:mc:{cat.id}")
    await h.send(700, "Файл")
    await h.send(700, "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUv/view")
    await h.click(700, "ad:mn:all")
    await h.click(700, "ad:mg:all")
    await h.click(700, "ad:mb:0")
    new = next(m for m in await repo.list_materials(concept_id=None) if m.title == "Файл")
    assert new.kind == "файл"


async def test_add_and_hide_product(h, repo):
    await reg(h)
    await h.click(700, "ad:pa")
    for answer in ["Горячее", "Тестовое блюдо", "-", "-", "-", "-", "-", "-"]:
        await h.send(700, answer)
    await h.click(700, "ad:pn:all")
    p = next(p for p in await repo.list_products(concept_id=None) if p.name == "Тестовое блюдо")
    assert p.concept_id == "все"
    await h.click(700, f"ad:px:{p.id}")
    assert all(x.id != p.id for x in await repo.list_products(concept_id=None))


async def test_moderator_limited_to_own_concept(h, repo):
    await reg(h)
    scope = await repo.concept_of((await repo.find_employees("Волкова"))[0])
    assert scope
    cat = (await repo.list_categories())[0]
    await h.click(400, "ad:ma")
    await h.click(400, f"ad:mc:{cat.id}")
    await h.send(400, "Материал модератора")
    await h.send(400, "https://example.com/m")
    buttons = data(h.last_markup(400))
    assert "ad:mn:all" not in buttons and len(buttons) == 1
    await h.click(400, buttons[0])
    await h.click(400, "ad:mg:all")
    await h.click(400, "ad:mb:0")
    new = next(m for m in await repo.list_materials(concept_id=None) if m.title == "Материал модератора")
    assert new.concept_id == scope
    # общий материал модератор скрыть не может
    common = next(m for m in await repo.list_materials(concept_id=None) if m.concept_id.lower() == "все")
    await h.click(400, f"ad:mx:{common.id}")
    assert any(m.id == common.id for m in await repo.list_materials(concept_id=None))
