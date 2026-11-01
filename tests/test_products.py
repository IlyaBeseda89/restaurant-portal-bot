from app import schema as S
from app.handlers.products import card_text, category_key, photo_direct_url
from app.keyboards import BTN_PRODUCTS
from app.models import Product
from tests.conftest import register


def inline_texts(markup):
    return [b.text for row in markup.inline_keyboard for b in row] if markup else []


def inline_data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row] if markup else []


def edits(h):
    return [c for c in h.session.calls if type(c).__name__ == "EditMessageText"]


def photos(h):
    return [c for c in h.session.calls if type(c).__name__ == "SendPhoto"]


def test_photo_url_from_drive():
    assert photo_direct_url("https://drive.google.com/file/d/1AbCdEfGhIjKlM/view?usp=sharing") == (
        "https://drive.google.com/uc?export=view&id=1AbCdEfGhIjKlM"
    )
    assert photo_direct_url("https://example.com/a.jpg") == "https://example.com/a.jpg"
    assert photo_direct_url("") is None and photo_direct_url("не ссылка") is None


def test_card_text_escapes_html_and_skips_empty():
    p = Product("1", "trat", "Салаты", "Салат <b>X</b>", "", "соль & перец", "", "", "", "")
    text = card_text(p)
    assert "&lt;b&gt;" in text and "&amp;" in text
    assert "Аллергены" in text and "не указаны" in text  # без данных не выдаём за «аллергенов нет»
    assert "Что рассказать" not in text  # пустые поля не показываем


async def test_categories_and_dishes_by_concept(h, repo):
    await register(h, 100, "employee_DEMOEMP1", "Петрова Анна Сергеевна")  # концепция trat
    await h.send(100, BTN_PRODUCTS)
    cats = inline_texts(h.last_markup(100))
    assert cats == ["Салаты", "Горячее", "Десерты", "Напитки", "⬅️ В базу знаний"]  # «Бургеры» чужой концепции нет

    await h.click(100, f"pr:c:{category_key('Десерты')}")
    names = inline_texts(edits(h)[-1].reply_markup)
    assert "Тирамису" in names and not any("Скрытая" in n for n in names)


async def test_card_content_and_activity_log(h, repo):
    await register(h, 101, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await repo.flush_activity()
    await h.click(101, "pr:d:3")
    text = h.last_text(101)
    for part in ("Паста карбонара", "Спагетти", "глютен", "al dente", "Красное лёгкое вино", "римский"):
        assert part in text
    assert await repo.flush_activity() == 1


async def test_other_concept_and_hidden_dishes_are_not_available(h):
    await register(h, 102, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    for dish_id in ("7", "6", "999"):  # чужая концепция, скрытая, несуществующая
        await h.click(102, f"pr:d:{dish_id}")
        answers = [c for c in h.session.calls if type(c).__name__ == "AnswerCallbackQuery"]
        assert "недоступна" in (answers[-1].text or "")


async def test_next_dish_wraps_around(h):
    await register(h, 103, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await h.click(103, "pr:d:3")
    assert "pr:n:3" in inline_data(h.last_markup(103))
    await h.click(103, "pr:n:3")
    assert "Лазанья" in h.last_text(103)
    await h.click(103, "pr:n:4")
    assert "Паста карбонара" in h.last_text(103)  # после последнего блюда снова первое


async def test_single_dish_category_has_no_next_button(h):
    await register(h, 104, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await h.click(104, "pr:d:5")  # в «Десертах» одно видимое блюдо
    assert not any(d.startswith("pr:n:") for d in inline_data(h.last_markup(104)))


async def test_photo_is_sent_when_url_given(h, repo):
    await repo.backend.update(S.PRODUCTS, "id", "5", {"фото_url": "https://example.com/t.jpg"})
    await register(h, 105, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await h.click(105, "pr:d:5")
    assert len(photos(h)) == 1
    assert photos(h)[0].photo == "https://example.com/t.jpg"
    assert "Тирамису" in photos(h)[0].caption


async def test_done_button_only_for_newbie_and_is_idempotent(h, repo):
    await register(h, 106, "employee_DEMOEMP1", "Петрова Анна Сергеевна")  # давно работает
    await h.click(106, "pr:d:3")
    assert not any(d.startswith("pr:ok:") for d in inline_data(h.last_markup(106)))

    await register(h, 107, "employee_DEMONEW1", "Смирнов Олег Игоревич")  # новичок
    await h.click(107, "pr:d:3")
    assert "pr:ok:3" in inline_data(h.last_markup(107))
    await h.click(107, "pr:ok:3")
    await h.click(107, "pr:ok:3")
    rows = await repo.backend.read_all(S.PROGRESS)
    assert len(rows) == 1 and rows[0]["объект_id"] == "3" and rows[0]["сотрудник_id"] == "2"
    await h.click(107, "pr:d:3")  # после отметки кнопки «Отметить» уже нет
    assert "pr:ok:3" not in inline_data(h.last_markup(107))


async def test_card_edit_in_table_is_visible_immediately(h, repo):
    await register(h, 108, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await repo.backend.update(S.PRODUCTS, "id", "2", {"состав": "Томаты, буррата, базилик"})
    await h.click(108, "pr:d:2")
    assert "буррата" in h.last_text(108)
