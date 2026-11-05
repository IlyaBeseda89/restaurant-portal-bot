"""Разделение по концепциям: чужое не показывается, общее («все») видно всем."""

from app import schema as S
from app.keyboards import BTN_FEEDBACK, BTN_KNOWLEDGE, BTN_PRODUCTS, BTN_REQUEST
from tests.conftest import FEEDBACK_CHAT, register


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
    assert texts(h.last_markup(200)) == ["Бургеры", "Напитки", "⬅️ В базу знаний"]  # ни одного блюда «Траттории»


async def test_employee_without_restaurant_sees_only_common(h, repo):
    code, fio = await other_employee(repo)  # ресторан не указан
    await register(h, 201, f"employee_{code}", fio)
    await h.send(201, BTN_PRODUCTS)
    assert texts(h.last_markup(201)) == ["Напитки", "⬅️ В базу знаний"]  # только общая карточка
    await h.send(201, BTN_KNOWLEDGE)
    await h.click(201, "kb:cat:menu")
    assert texts(last_edit(h).reply_markup) == ["⬅️ Ко всем разделам"]  # материалы по меню у каждой концепции свои


async def test_restaurant_without_concept_gets_only_common(h, repo):
    await repo.backend.append(S.RESTAURANTS, {"id": "r9", "название": "Новая точка", "концепция_id": "",
                                              "город": "", "адрес": "", "активен": "да"})
    code, fio = await other_employee(repo, ресторан_id="r9")
    await register(h, 202, f"employee_{code}", fio)
    await h.send(202, BTN_PRODUCTS)
    assert texts(h.last_markup(202)) == ["Напитки", "⬅️ В базу знаний"]


async def test_cannot_open_other_concept_dish_by_id(h, repo):
    code, fio = await other_employee(repo, ресторан_id="r3")
    await register(h, 203, f"employee_{code}", fio)
    await h.click(203, "pr:d:3")  # блюдо «Траттории»
    answers = [c for c in h.session.calls if type(c).__name__ == "AnswerCallbackQuery"]
    assert "недоступна" in (answers[-1].text or "")


async def test_moderator_is_bound_to_own_concept(h):
    await register(h, 204, "moderator_DEMOMOD1", "Волкова Мария Андреевна")  # модератор «Траттории»
    await h.send(204, BTN_PRODUCTS)
    assert texts(h.last_markup(204)) == ["Салаты", "Горячее", "Десерты", "Напитки", "⬅️ В базу знаний"]
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
    assert texts(edit.reply_markup) == ["Бургеры", "Напитки", "🔀 Другая концепция", "⬅️ В базу знаний"]

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
    assert texts(h.last_markup(208)) == ["Бургеры", "Напитки", "⬅️ В базу знаний"]  # только Бистро, выбора нет


async def test_empty_flag_follows_role(h, repo):
    code, fio = await other_employee(repo, ресторан_id="r1")  # обычный сотрудник, флаг пуст
    await register(h, 209, f"employee_{code}", fio)
    await h.send(209, BTN_PRODUCTS)
    assert "Бургеры" not in texts(h.last_markup(209))


async def test_hidden_concept_is_not_offered(repo):
    concepts = await repo.list_concepts()
    hidden = concepts[0]
    await repo.backend.update(S.CONCEPTS, "id", hidden.id, {"активна": "нет"})
    assert hidden.id not in {c.id for c in await repo.list_concepts()}
    assert hidden.id in {c.id for c in await repo.list_concepts(active_only=False)}
    # рестораны скрытой концепции не предлагаются при добавлении сотрудников, но по id находятся
    assert all(r.concept_id != hidden.id for r in await repo.list_restaurants())
    assert any(r.concept_id == hidden.id for r in await repo.list_restaurants(active_only=False))


async def test_feedback_goes_privately_to_director_concept_tu_and_hr(h, repo):
    """Обращение из Траттории: директор ресторана, ТУ концепции и HR; ТУ только Бистро ничего не получает."""
    base = {"телефон": "", "должность": "", "дата_старта": "01.01.2020", "дата_добавления": "01.01.2020",
            "активен": "да", "новичок": "нет"}
    people = [
        ("60", 6001, "Директоров Дмитрий", "r1", "директор"),
        ("61", 6002, "Тувов Тимур", "", "ту"),        # ТУ обеих концепций
        ("62", 6003, "Бистров Борис", "", "ту"),      # ТУ только Бистро
        ("63", 6004, "Кадров Кирилл", "", "hr"),
        ("64", 6005, "Директоров Другой", "r3", "директор"),  # директор другого ресторана
    ]
    for i, (eid, tg, fio, rest, role) in enumerate(people):
        await repo.backend.append(S.EMPLOYEES, {
            **base, "id": eid, "telegram_id": str(tg), "фио": fio, "ресторан_id": rest,
            "роль": role, "пригласительный_код": f"FB{i}"})
    await repo.backend.update(S.CONCEPTS, "id", "trat", {"ТУ": "Тимур Тувов"})  # порядок слов любой
    await repo.backend.update(S.CONCEPTS, "id", "bistro", {"ТУ": "61, Бистров Борис"})

    await register(h, 300, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await h.send(300, BTN_FEEDBACK)
    await h.click(300, "fb:cat:crit")
    await h.send(300, "Грубый администратор")
    await h.click(300, "fb:mode:anon")

    for tg in (6001, 6002, 6004, FEEDBACK_CHAT):
        assert "Обращение №1" in h.last_text(tg), tg
    for tg in (6003, 6005):
        assert h.session.sent(tg) == [], tg

    card = h.last_text(6001)
    await h.click(6001, "fbst:1:w", chat_id=6001, msg_text=card)
    assert (await repo.backend.read_all(S.FEEDBACK))[0]["статус"] == "в работе"


async def test_restaurant_manager_can_open_training_request(h, repo):
    code, fio = await other_employee(repo, ресторан_id="r1", должность="Менеджер")
    await register(h, 400, f"employee_{code}", fio)
    await h.send(400, BTN_REQUEST)
    assert "Заявка на тренинг" in h.last_text(400)

    code2, fio2 = await other_employee(repo, id="51", ресторан_id="r1", должность="Официант",
                                       пригласительный_код="EXTRA002", телефон="+79005550000")
    await register(h, 401, f"employee_{code2}", fio2, phone="+79005550000")
    await h.send(401, BTN_REQUEST)
    assert "Заявка на тренинг" not in h.last_text(401)
