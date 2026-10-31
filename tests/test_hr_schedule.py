from app.keyboards import BTN_SCHEDULE
from tests.conftest import register


async def test_hr_manages_schedule_and_opens_enrollment(h, repo):
    await register(h, 100, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await register(h, 700, "hr_DEMOHR01", "Тестов Тест Тестович")
    await h.send(700, BTN_SCHEDULE)
    buttons = [b.callback_data for row in h.last_markup(700).inline_keyboard for b in row]
    assert "sch:op:2" in buttons or "sch:op:1" in buttons  # карточки тренингов с кнопками управления
    await h.click(700, "sch:op:1")
    assert (await repo.get_event("1")).open
    await h.click(100, "tr:en:1")
    assert (await repo.get_enrollment("1", "1")).status == "записан"
