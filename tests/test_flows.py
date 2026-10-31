"""Сценарии целиком: апдейты от «пользователя» идут через настоящий диспетчер."""

from app import schema as S
from app.keyboards import BTN_FEEDBACK, BTN_KNOWLEDGE, BTN_REQUEST, BTN_START
from tests.conftest import FEEDBACK_CHAT, HR_CHAT, register


def kb_texts(markup):
    if markup is None:
        return set()
    rows = getattr(markup, "keyboard", None) or getattr(markup, "inline_keyboard", [])
    return {b.text for row in rows for b in row}


async def test_no_link_no_access(h):
    await h.send(10, "/start")
    assert "только для сотрудников" in h.last_text(10)
    await h.send(10, BTN_KNOWLEDGE)
    assert "только для сотрудников" in h.last_text(10)


async def test_register_director(h, repo):
    await register(h, 20, "director_DEMODIR1", "Кузнецов Илья Петрович")
    emp = await repo.get_employee_by_telegram(20)
    assert emp is not None and emp.full_name == "Кузнецов Илья Петрович"
    assert emp.phone == "+79001234567"
    assert BTN_REQUEST in kb_texts(h.last_markup(20))
    # повторный /start — сразу меню
    await h.send(20, "/start")
    assert "Здравствуйте, Илья" in h.last_text(20)


async def test_register_newbie_gets_start_section(h):
    await register(h, 21, "employee_DEMONEW1", "Смирнов Олег Игоревич")
    assert "Добро пожаловать в команду" in h.last_text(21)
    assert BTN_START in kb_texts(h.last_markup(21))


async def test_unknown_person_goes_to_hr(h, repo):
    await h.send(30, "/start employee_NOPE")
    await h.send(30, "Иванов Иван Иванович")
    await h.send(30, "+79990000000")
    assert "передал заявку HR" in h.last_text(30)
    hr = h.last_text(HR_CHAT)
    assert "Иванов Иван Иванович" in hr and "не найден" in hr
    assert await repo.get_employee_by_telegram(30) is None


async def test_link_cannot_be_reused(h):
    await register(h, 40, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await h.send(41, "/start employee_DEMOEMP1")
    await h.send(41, "Петрова Анна Сергеевна")
    await h.send(41, "+79001112233")
    assert "уже зарегистрирован другой" in h.last_text(HR_CHAT)


async def test_fired_employee_loses_access(h, repo):
    await register(h, 50, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await repo.backend.update(S.EMPLOYEES, "id", "1", {"активен": "нет"})
    await h.send(50, BTN_KNOWLEDGE)
    assert "только для сотрудников" in h.last_text(50)


async def test_knowledge_base_navigation(h, repo):
    await register(h, 60, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await h.send(60, BTN_KNOWLEDGE)
    assert "Стандарты сервиса" in " ".join(kb_texts(h.last_markup(60)))
    await h.click(60, "kb:cat:menu")
    edit = [c for c in h.session.calls if type(c).__name__ == "EditMessageText"][-1]
    titles = " ".join(kb_texts(edit.reply_markup))
    assert "Итальянская кухня" in titles and "бистро" not in titles.lower()
    await h.click(60, "kb:mat:5")
    assert "Итальянская кухня" in h.last_text(60)
    await h.click(60, "kb:mat:6")  # материал чужой концепции
    answers = [c for c in h.session.calls if type(c).__name__ == "AnswerCallbackQuery"]
    assert "недоступен" in (answers[-1].text or "")
    assert await repo.flush_activity() == 2  # регистрация + просмотр


async def test_anonymous_feedback_keeps_no_trace(h, repo):
    await register(h, 70, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await repo.flush_activity()
    await h.send(70, BTN_FEEDBACK)
    await h.click(70, "fb:cat:idea")
    await h.send(70, "Поставить кофемашину для персонала")
    await h.click(70, "fb:mode:anon")
    assert "№1" in h.last_text(70)
    assert "Траттория" not in h.last_text(70)  # автору ресторан не показываем

    rows = await repo.backend.read_all(S.FEEDBACK)
    assert rows[0]["анонимно"] == "да" and rows[0]["контакт"] == ""
    assert rows[0]["ресторан_id"] == "r1"  # подставлен из профиля
    card = h.last_text(FEEDBACK_CHAT)
    assert "#идея" in card and "#Траттория_на_Невском" in card and "анонимно" in card
    assert "Петрова" not in card and "70" not in card.replace("№1", "")
    assert await repo.flush_activity() == 0  # анонимное обращение не попало в журнал


async def test_feedback_with_contact_and_status(h, repo):
    await register(h, 80, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await h.send(80, BTN_FEEDBACK)
    await h.click(80, "fb:cat:crit")
    await h.send(80, "Долго ждём поставку")
    await h.click(80, "fb:mode:contact")
    await h.click(80, "fb:contact:username")
    card = h.last_text(FEEDBACK_CHAT)
    assert "@user80" in card and "#Траттория_на_Невском" in card

    await h.click(999, "fbst:1:w", chat_id=FEEDBACK_CHAT, msg_text=card)
    rows = await repo.backend.read_all(S.FEEDBACK)
    assert rows[0]["статус"] == "в работе"


async def test_menu_button_interrupts_dialog(h, repo):
    await register(h, 90, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await h.send(90, BTN_FEEDBACK)
    await h.click(90, "fb:cat:wish")
    await h.send(90, BTN_KNOWLEDGE)
    assert "База знаний" in h.last_text(90)
    assert await repo.backend.read_all(S.FEEDBACK) == []


async def test_feedback_without_profile_restaurant_requires_choice(h, repo):
    await register(h, 95, "hr_DEMOHR01", "Тестов Тест Тестович")  # у HR нет ресторана
    await h.send(95, BTN_FEEDBACK)
    await h.click(95, "fb:cat:wish")
    await h.send(95, "Текст")
    await h.click(95, "fb:mode:anon")
    assert "К какому ресторану" in h.last_text(95)
    assert "Не относится" not in " ".join(kb_texts(h.last_markup(95)))
    await h.click(95, "fb:rest:-")  # пропустить нельзя
    assert await repo.backend.read_all(S.FEEDBACK) == []
    await h.click(95, "fb:rest:r3")
    rows = await repo.backend.read_all(S.FEEDBACK)
    assert rows[0]["ресторан_id"] == "r3"
