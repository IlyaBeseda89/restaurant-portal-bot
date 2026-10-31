from app.keyboards import BTN_START, BTN_STATS
from tests.conftest import register


def data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row] if markup else []


async def reg(h):
    await register(h, 100, "employee_DEMONEW1", "Смирнов Олег Игоревич")  # новичок
    await register(h, 200, "employee_DEMOEMP1", "Петрова Анна Сергеевна")  # не новичок
    await register(h, 600, "trainer_DEMOTRN1", "Лебедева Ольга Николаевна")
    await register(h, 700, "hr_DEMOHR01", "Тестов Тест Тестович")


async def test_newbie_sees_checklist_with_own_concept(h, repo):
    await reg(h)
    await h.send(100, BTN_START)
    text = h.last_text(100)
    assert "Мой старт" in text and "0 из" in text
    buttons = data(h.last_markup(100))
    me = await repo.get_employee_by_telegram(100)
    concept = await repo.concept_of(me)
    expected = {m.id for m in await repo.list_materials(concept) if m.for_newbies}
    assert {b.removeprefix("st:m:") for b in buttons if b.startswith("st:m:")} == expected


async def test_mark_done_updates_progress_and_notifies_manager(h, repo):
    await reg(h)
    me = await repo.get_employee_by_telegram(100)
    concept = await repo.concept_of(me)
    items = [m for m in await repo.list_materials(concept) if m.for_newbies]
    for m in items:
        await h.click(100, f"st:ok:{m.id}")
    assert await repo.done_ids(me.id, "материал") == {m.id for m in items}
    await h.click(100, f"st:ok:{items[0].id}")  # повтор ничего не ломает
    assert len(await repo.done_ids(me.id, "материал")) == len(items)
    assert "прошёл" in h.last_text(600)  # менеджер по обучению получил уведомление
    await h.send(100, BTN_START)
    assert f"{len(items)} из {len(items)}" in h.last_text(100)


async def test_not_newbie_has_no_start(h):
    await reg(h)
    await h.send(200, BTN_START)
    assert "Мой старт" not in h.last_text(200)


async def test_cannot_mark_other_concept_material(h, repo):
    await reg(h)
    me = await repo.get_employee_by_telegram(100)
    concept = await repo.concept_of(me)
    foreign = next(
        m for m in await repo.list_materials(None)
        if m.for_newbies and m.concept_id.lower() not in {"все", concept.lower()}
    )
    await h.click(100, f"st:ok:{foreign.id}")
    assert foreign.id not in await repo.done_ids(me.id, "материал")


async def test_stats_for_hr_and_hidden_for_employee(h, repo):
    await reg(h)
    await h.send(200, BTN_STATS)
    assert "Статистика" not in h.last_text(200)
    await h.send(100, BTN_START)  # создаёт активность
    await h.send(700, BTN_STATS)
    text = h.last_text(700)
    assert "Статистика" in text and "Сотрудники" in text and "Новичков сейчас" in text
    await h.click(700, "stt:new")
    edits = [c for c in h.session.calls if type(c).__name__ == "EditMessageText"]
    assert "Смирнов" in edits[-1].text


async def test_stats_moderator_scoped_to_concept(h, repo):
    await reg(h)
    await register(h, 400, "moderator_DEMOMOD1", "Волкова Мария Андреевна")
    await h.send(400, BTN_STATS)
    assert "концепция" in h.last_text(400)
