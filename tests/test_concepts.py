"""Разделение по концепциям: чужое не показывается, общее («все») видно всем."""

from app import schema as S
from app.keyboards import BTN_KNOWLEDGE, BTN_PRODUCTS
from tests.conftest import register


def texts(markup):
    return [b.text for row in markup.inline_keyboard for b in row] if markup else []


def last_edit(h):
    return [c for c in h.session.calls if type(c).__name__ == "EditMessageText"][-1]


async def other_employee(repo, **fields):
    """Добавляет сотрудника с заданными полями поверх демо-данных."""
    row = {"id": "50", "telegram_id": "", "фио": "Новиков Новик Новикович", "телефон": "",
           "ресторан_id": "", "должность": "", "роль": "сотрудник", "дата_старта": "01.01.2020",
           "дата_добавления": "01.01.2020", "активен": "да", "пригласительный_код": "EXTRA001",
           "новичок": "нет"}
    row.update(fields)
    await repo.backend.append(S.EMPLOYEES, row)
    return row["пригласительный_код"], row["фио"]


async def test_bistro_employee_sees_only_bistro_and_common_products(h, repo):
    code, fio = await other_employee(repo, ресторан_id="r3")  # Бистро Центр
    await register(h, 200, f"employee_{code}", fio)
    await h.send(200, BTN_PRODUCTS)
    assert texts(h.last_markup(200)) == ["Бургеры", "Напитки"]  # ни одного блюда «Траттории»


async def test_employee_without_restaurant_sees_only_common(h, repo):
    code, fio = await other_employee(repo)  # ресторан не указан
    await register(h, 201, f"employee_{code}", fio)
    await h.send(201, BTN_PRODUCTS)
    assert texts(h.last_markup(201)) == ["Напитки"]  # только общая карточка
    await h.send(201, BTN_KNOWLEDGE)
    await h.click(201, "kb:cat:menu")
    assert texts(last_edit(h).reply_markup) == ["⬅️ Ко всем разделам"]  # материалы по меню у каждой концепции свои


async def test_restaurant_without_concept_gets_only_common(h, repo):
    await repo.backend.append(S.RESTAURANTS, {"id": "r9", "название": "Новая точка", "концепция_id": "",
                                              "город": "", "адрес": "", "активен": "да"})
    code, fio = await other_employee(repo, ресторан_id="r9")
    await register(h, 202, f"employee_{code}", fio)
    await h.send(202, BTN_PRODUCTS)
    assert texts(h.last_markup(202)) == ["Напитки"]


async def test_cannot_open_other_concept_dish_by_id(h, repo):
    code, fio = await other_employee(repo, ресторан_id="r3")
    await register(h, 203, f"employee_{code}", fio)
    await h.click(203, "pr:d:3")  # блюдо «Траттории»
    answers = [c for c in h.session.calls if type(c).__name__ == "AnswerCallbackQuery"]
    assert "недоступна" in (answers[-1].text or "")


async def test_moderator_is_bound_to_own_concept(h):
    await register(h, 204, "moderator_DEMOMOD1", "Волкова Мария Андреевна")  # модератор «Траттории»
    await h.send(204, BTN_PRODUCTS)
    assert texts(h.last_markup(204)) == ["Салаты", "Горячее", "Десерты", "Напитки"]
    assert "Бургеры" not in texts(h.last_markup(204))


async def test_hr_chooses_concept_first(h):
    await register(h, 205, "hr_DEMOHR01", "Тестов Тест Тестович")
    await h.send(205, BTN_PRODUCTS)
    assert "Выберите концепцию" in h.last_text(205)
    assert texts(h.last_markup(205)) == ["Траттория", "Бистро"]

    from app.scope import concept_key

    await h.click(205, f"sc:pr:{concept_key('bistro')}")
    edit = last_edit(h)
    assert "Концепция: Бистро" in edit.text
    assert texts(edit.reply_markup) == ["Бургеры", "Напитки", "🔀 Другая концепция"]

    await h.click(205, "pr:pick")  # смена концепции
    await h.click(205, f"sc:pr:{concept_key('trat')}")
    assert "Бургеры" not in texts(last_edit(h).reply_markup)
    assert "Десерты" in texts(last_edit(h).reply_markup)


async def test_hr_knowledge_base_per_concept(h):
    from app.scope import concept_key

    await register(h, 206, "tu_DEMOTU01", "Орлов Денис Викторович")  # ТУ
    await h.send(206, BTN_KNOWLEDGE)
    await h.click(206, f"sc:kb:{concept_key('bistro')}")
    await h.click(206, "kb:cat:menu")
    titles = " ".join(texts(last_edit(h).reply_markup))
    assert "Меню бистро" in titles and "Итальянская" not in titles


async def test_flag_gives_any_employee_all_concepts(h, repo):
    from app.scope import concept_key

    code, fio = await other_employee(repo, ресторан_id="r1", **{"все_концепции": "да"})  # PR-директор
    await register(h, 207, f"employee_{code}", fio)
    await h.send(207, BTN_PRODUCTS)
    assert texts(h.last_markup(207)) == ["Траттория", "Бистро"]
    await h.click(207, f"sc:pr:{concept_key('bistro')}")
    assert "Бургеры" in texts(last_edit(h).reply_markup)


async def test_flag_no_restricts_even_privileged_role(h, repo):
    code, fio = await other_employee(
        repo, ресторан_id="r3", роль="ТУ", **{"все_концепции": "нет"}
    )
    await register(h, 208, f"tu_{code}", fio)
    await h.send(208, BTN_PRODUCTS)
    assert texts(h.last_markup(208)) == ["Бургеры", "Напитки"]  # только Бистро, выбора нет


async def test_empty_flag_follows_role(h, repo):
    code, fio = await other_employee(repo, ресторан_id="r1")  # обычный сотрудник, флаг пуст
    await register(h, 209, f"employee_{code}", fio)
    await h.send(209, BTN_PRODUCTS)
    assert "Бургеры" not in texts(h.last_markup(209))
