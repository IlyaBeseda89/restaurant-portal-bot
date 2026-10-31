from app.keyboards import BTN_SCHEDULE
from tests.conftest import register


async def _flow(h, repo, user, fmt_key, topic_cb, concept_cb, venue=None):
    await h.send(user, BTN_SCHEDULE)
    await h.click(user, "ev:add")
    await h.click(user, topic_cb)
    if topic_cb == "ev:t:new":
        await h.send(user, "Сервис вина")
    await h.click(user, f"ev:f:{fmt_key}")
    await h.send(user, "15.12.2099 14:00")
    if fmt_key != "online":
        await h.send(user, venue or "Зал на Невском")
    await h.send(user, "Иванов")
    await h.click(user, concept_cb)
    await h.send(user, "12")
    await h.click(user, "ev:o:1")


async def test_hr_adds_hybrid_training_with_new_topic(h, repo):
    await register(h, 700, "hr_DEMOHR01", "Тестов Тест Тестович")
    before = {e.id for e in await repo.list_events()}
    await _flow(h, repo, 700, "hybrid", "ev:t:new", "ev:c:all")
    new = [e for e in await repo.list_events() if e.id not in before]
    assert len(new) == 1
    e = new[0]
    assert e.format == "гибрид" and e.venue == "Зал на Невском" and e.host == "Иванов"
    assert e.capacity == 12 and e.open and not e.concept_id
    assert (await repo.get_topic(e.topic_id)).name == "Сервис вина"


async def test_online_skips_venue_and_concept_is_saved(h, repo):
    await register(h, 700, "hr_DEMOHR01", "Тестов Тест Тестович")
    before = {e.id for e in await repo.list_events()}
    concept = (await repo.list_concepts())[0]
    from app.scope import concept_key
    topic = (await repo.list_topics())[0]
    await _flow(h, repo, 700, "online", f"ev:t:{topic.id}", f"ev:c:{concept_key(concept.id)}")
    e = next(e for e in await repo.list_events() if e.id not in before)
    assert e.format == "онлайн" and e.venue == "онлайн" and e.concept_id == concept.id


async def test_employee_cannot_add(h, repo):
    await register(h, 100, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await h.click(100, "ev:add")
    assert not any("Новый тренинг" in str(getattr(m, "text", "")) for m in h.session.sent(100))
