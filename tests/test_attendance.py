from tests.conftest import register


async def reg(h):
    await register(h, 100, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await register(h, 101, "employee_DEMONEW1", "Смирнов Олег Игоревич")
    await register(h, 600, "trainer_DEMOTRN1", "Лебедева Ольга Николаевна")
    await register(h, 700, "hr_DEMOHR01", "Тестов Тест Тестович")


async def finished_event(h, repo):
    await reg(h)
    await h.click(600, "sch:op:1")
    await h.click(100, "tr:en:1")
    await h.click(101, "tr:en:1")
    await h.click(600, "sch:done:1")


def data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row] if markup else []


async def test_attendance_only_after_done(h, repo):
    await reg(h)
    await h.click(600, "sch:att:1")
    assert await repo.list_enrollments("1") == []


async def test_mark_attendance_and_ratings(h, repo):
    await finished_event(h, repo)
    first = await repo.get_employee_by_telegram(100)
    second = await repo.get_employee_by_telegram(101)
    await h.click(600, "sch:att:1")
    await h.click(600, f"sch:att:1:{first.id}")
    await h.click(600, f"sch:att:1:{second.id}")
    await h.click(600, f"sch:att:1:{second.id}")  # повторное нажатие меняет на «не был»
    assert (await repo.get_enrollment("1", first.id)).status == "был"
    assert (await repo.get_enrollment("1", second.id)).status == "не был"
    await h.click(600, "sch:rate:1")
    assert any("Оцените" in (c.text or "") for c in h.session.sent(100))
    assert not any("Оцените" in (c.text or "") for c in h.session.sent(101))
    await h.click(101, "tr:rt:1:5")  # не был: оценить нельзя
    assert (await repo.get_enrollment("1", second.id)).rating == 0
    await h.click(100, "tr:rt:1:4")
    assert (await repo.get_enrollment("1", first.id)).rating == 4


async def test_non_manager_cannot_mark(h, repo):
    await finished_event(h, repo)
    first = await repo.get_employee_by_telegram(100)
    await h.click(101, f"sch:att:1:{first.id}")
    assert (await repo.get_enrollment("1", first.id)).status == "записан"


async def test_stats_show_trainings(h, repo):
    await finished_event(h, repo)
    from app.keyboards import BTN_STATS
    first = await repo.get_employee_by_telegram(100)
    await h.click(600, "sch:att:1")
    await h.click(600, f"sch:att:1:{first.id}")
    await h.click(100, "tr:rt:1:5")
    await h.send(700, BTN_STATS)
    assert "Проведено тренингов: 1, посещений: 1, средняя оценка 5.0" in h.last_text(700)
