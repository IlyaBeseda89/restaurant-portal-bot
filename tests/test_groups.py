from app.groups import LEADERS, MANAGEMENT, STAFF, allows, default_group, group_of
from app.roles import Role
from tests.conftest import register


def test_default_group_by_role_and_position():
    assert default_group(Role.TU, "") == LEADERS
    assert default_group(Role.DIRECTOR, "директор ресторана") == LEADERS
    assert default_group(Role.EMPLOYEE, "Су-шеф") == LEADERS
    assert default_group(Role.EMPLOYEE, "Шеф-бармен") == LEADERS
    assert default_group(Role.EMPLOYEE, "менеджер зала") == MANAGEMENT
    assert default_group(Role.EMPLOYEE, "Старший бармен") == MANAGEMENT
    assert default_group(Role.EMPLOYEE, "официант") == STAFF
    assert default_group(Role.EMPLOYEE, "линейный повар") == STAFF


def test_seniors_see_lower_groups():
    assert allows("", STAFF) and allows(None, STAFF)
    assert allows("сотрудники", STAFF)
    assert not allows("менеджмент", STAFF)
    assert allows("менеджмент", MANAGEMENT) and allows("менеджмент", LEADERS)
    assert not allows("руководители", MANAGEMENT)
    assert allows("руководители", LEADERS)
    assert not allows("опечатка", MANAGEMENT)  # непонятное значение не открывает материал всем


async def test_materials_filtered_by_group(h, repo):
    await register(h, 100, "employee_DEMOEMP1", "Петрова Анна Сергеевна")  # официант
    me = await repo.get_employee_by_telegram(100)
    assert group_of(me) == STAFF
    concept = await repo.concept_of(me)
    cat = (await repo.list_materials(concept))[0].category_id
    mid = await repo.add_material(cat, "Для менеджеров", "ссылка", "https://example.com", "все", False, "менеджмент")
    assert all(m.id != mid for m in await repo.list_materials(concept, group=STAFF))
    assert any(m.id == mid for m in await repo.list_materials(concept, group=MANAGEMENT))
    await h.click(100, f"kb:mat:{mid}")
    # не открылся: в журнале нет просмотра
    assert all(r["объект"] != mid for r in await repo.activity_since(1) if r["действие"] == "просмотр материала")
    await repo.update_employee(me.id, группа="менеджмент")
    await h.click(100, f"kb:mat:{mid}")
    assert any(r["объект"] == mid for r in await repo.activity_since(1) if r["действие"] == "просмотр материала")


async def test_admin_sets_group(h, repo):
    await register(h, 100, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await register(h, 700, "hr_DEMOHR01", "Тестов Тест Тестович")
    me = await repo.get_employee_by_telegram(100)
    await h.click(700, f"ad:egv:{me.id}:lead")
    assert (await repo.get_employee(me.id)).group == "руководители"
    await h.click(700, f"ad:egv:{me.id}:auto")
    assert (await repo.get_employee(me.id)).group == ""
