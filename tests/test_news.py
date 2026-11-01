from app.keyboards import BTN_NEWS
from app.scope import concept_key
from tests.conftest import register


async def _regs(h):
    await register(h, 100, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await register(h, 200, "director_DEMODIR1", "Кузнецов Илья Петрович")
    await register(h, 205, "hr_DEMOHR01", "Тестов Тест Тестович")


async def _write(h, user, audience_cb=None, push="push"):
    await h.send(user, BTN_NEWS)
    await h.click(user, "nw:new")
    await h.send(user, "Новое меню")
    await h.send(user, "С понедельника меняем меню")
    await h.click(user, "nw:nophoto")
    if audience_cb:
        await h.click(user, audience_cb)
    await h.click(user, f"nw:go:{push}")


async def test_employee_cannot_write(h, repo):
    await _regs(h)
    await h.send(100, BTN_NEWS)
    assert "nw:new" not in str(h.last_markup(100))
    await h.click(100, "nw:new")
    assert not await repo.list_news()


async def test_director_posts_to_own_concept_and_pushes(h, repo):
    await _regs(h)
    await _write(h, 200)
    posts = await repo.list_news()
    assert len(posts) == 1
    assert posts[0].concept_id == await repo.concept_of(await repo.get_employee("3"))
    texts = [str(getattr(m, "text", "")) + str(getattr(m, "caption", "")) for m in h.session.sent(100)]
    assert any("Новое меню" in t for t in texts)
    assert posts[0].sent >= 1


async def test_hr_posts_for_all_and_feed_only_in_feed(h, repo):
    await _regs(h)
    await _write(h, 205, "nw:a:all", push="feed")
    post = (await repo.list_news())[0]
    assert post.concept_id == "" and post.sent == 0
    assert not any("Новое меню" in str(getattr(m, "text", "")) for m in h.session.sent(100))
    await h.send(100, BTN_NEWS)
    assert f"nw:o:{post.id}" in str(h.last_markup(100))


async def test_other_concept_news_hidden_from_employee(h, repo):
    await _regs(h)
    employee = await repo.get_employee("1")
    mine = await repo.concept_of(employee)
    others = [c for c in await repo.list_concepts() if c.id != mine]
    if not others:
        return
    await _write(h, 205, f"nw:a:{concept_key(others[0].id)}", push="feed")
    post = (await repo.list_news())[0]
    await h.send(100, BTN_NEWS)
    assert f"nw:o:{post.id}" not in str(h.last_markup(100))
    await h.click(100, f"nw:o:{post.id}")
    assert "недоступна" in h.last_text(100)


async def test_author_can_hide(h, repo):
    await _regs(h)
    await _write(h, 205, "nw:a:all", push="feed")
    post = (await repo.list_news())[0]
    await h.click(100, f"nw:h:{post.id}")
    assert (await repo.list_news())
    await h.click(205, f"nw:h:{post.id}")
    assert not await repo.list_news()


async def test_edit_in_preview_before_publishing(h, repo):
    await _regs(h)
    await h.send(205, BTN_NEWS)
    await h.click(205, "nw:new")
    await h.send(205, "Старый заголовок")
    await h.send(205, "Текст")
    await h.click(205, "nw:nophoto")
    await h.click(205, "nw:a:all")
    await h.click(205, "nw:e:t")
    await h.send(205, "Новый заголовок")
    assert "nw:go:feed" in str(h.last_markup(205))  # снова предпросмотр
    await h.click(205, "nw:go:feed")
    assert (await repo.list_news())[0].title == "Новый заголовок"


async def test_edit_after_publishing_marks_edited_and_can_resend(h, repo):
    await _regs(h)
    await _write(h, 205, "nw:a:all", push="feed")
    post = (await repo.list_news())[0]
    await h.click(205, f"nw:x:{post.id}")
    await h.click(205, "nw:f:x")
    await h.send(205, "Исправленный текст")
    post = (await repo.list_news())[0]
    assert post.text == "Исправленный текст" and post.edited
    assert not any("Исправленный" in str(getattr(m, "text", "")) for m in h.session.sent(100))
    await h.click(205, f"nw:ru:{post.id}")
    assert any("Исправленный" in str(getattr(m, "text", "")) for m in h.session.sent(100))


async def test_stranger_cannot_edit_news(h, repo):
    await _regs(h)
    await _write(h, 205, "nw:a:all", push="feed")
    post = (await repo.list_news())[0]
    await h.click(100, f"nw:x:{post.id}")
    await h.click(100, "nw:f:x")
    await h.send(100, "Хакнули")
    assert (await repo.list_news())[0].text == "С понедельника меняем меню"
