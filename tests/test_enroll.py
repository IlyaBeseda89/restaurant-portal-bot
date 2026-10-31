from app.keyboards import BTN_TRAININGS
from tests.conftest import register


def data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row] if markup else []


async def reg(h):
    await register(h, 100, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await register(h, 101, "employee_DEMONEW1", "Смирнов Олег Игоревич")
    await register(h, 600, "trainer_DEMOTRN1", "Лебедева Ольга Николаевна")


async def open_event(h, cap=None):
    await h.click(600, "sch:op:1")
    if cap is not None:
        await h.click(600, "sch:ef:1:cap")
        await h.send(600, str(cap))


async def test_closed_event_has_no_enroll_button(h, repo):
    await reg(h)
    await h.send(100, BTN_TRAININGS)
    assert "tr:en:1" not in data(h.last_markup(100))


async def test_enroll_queue_and_promotion(h, repo):
    await reg(h)
    await open_event(h, cap=1)
    assert (await repo.get_event("1")).open and (await repo.get_event("1")).capacity == 1
    await h.send(100, BTN_TRAININGS)
    assert "tr:en:1" in data(h.last_markup(100))
    await h.click(100, "tr:en:1")
    await h.click(101, "tr:en:1")
    assert (await repo.get_enrollment("1", "1")).status == "записан"
    second = await repo.get_employee_by_telegram(101)
    assert (await repo.get_enrollment("1", second.id)).status == "очередь"
    assert (await repo.get_event("1")).enrolled == 1
    before = len(h.session.sent(101))
    await h.click(100, "tr:un:1")  # первый отменил, место получает второй
    assert (await repo.get_enrollment("1", second.id)).status == "записан"
    assert any("Освободилось место" in (c.text or "") for c in h.session.sent(101)[before:])


async def test_repeat_enroll_is_harmless(h, repo):
    await reg(h)
    await open_event(h)
    await h.click(100, "tr:en:1")
    await h.click(100, "tr:en:1")
    assert len([e for e in await repo.list_enrollments("1")]) == 1


async def test_cannot_enroll_when_closed_or_not_manager(h, repo):
    await reg(h)
    await h.click(100, "tr:en:1")  # запись не открыта
    assert await repo.list_enrollments("1") == []
    await h.click(100, "sch:op:1")  # сотрудник не может открыть запись
    assert not (await repo.get_event("1")).open


async def test_event_concept_hides_from_other_concept(h, repo):
    await reg(h)
    me = await repo.get_employee_by_telegram(100)
    mine = await repo.concept_of(me)
    other = next(c for c in await repo.list_concepts() if c.id != mine)
    from app.scope import concept_key
    await h.click(600, f"sch:ecv:1:{concept_key(other.id)}")
    assert (await repo.get_event("1")).concept_id == other.id
    await h.send(100, BTN_TRAININGS)
    assert "tr:ics:1" not in data(h.last_markup(100))
    await h.click(600, "sch:ecv:1:all")
    await h.send(100, BTN_TRAININGS)
    assert "tr:ics:1" in data(h.last_markup(100))


async def test_changing_date_notifies_enrolled(h, repo):
    await reg(h)
    await open_event(h)
    await h.click(100, "tr:en:1")
    await h.click(600, "sch:ef:1:date")
    await h.send(600, "bad")
    assert (await repo.get_event("1")).start.year  # не сломалось
    from datetime import datetime, timedelta
    new = (datetime.now() + timedelta(days=40)).strftime("%d.%m.%Y 16:30")
    await h.send(600, new)
    assert (await repo.get_event("1")).start.strftime("%d.%m.%Y %H:%M") == new
    assert any("Тренинг изменён" in (c.text or "") for c in h.session.sent(100))
    await h.click(600, "sch:ef:1:venue")
    await h.send(600, "Новая площадка")
    assert (await repo.get_event("1")).venue == "Новая площадка"
