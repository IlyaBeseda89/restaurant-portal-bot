from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app import schema as S
from app.ics import build_ics
from app.keyboards import BTN_REQUEST, BTN_REQUESTS_INBOX, BTN_SCHEDULE, BTN_TRAININGS
from app.models import parse_datetime
from app.reminders import send_due_reminders
from tests.conftest import register


def data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row] if markup else []


def docs(h):
    return [c for c in h.session.calls if type(c).__name__ == "SendDocument"]


async def reg_all(h):
    await register(h, 100, "employee_DEMOEMP1", "Петрова Анна Сергеевна")
    await register(h, 200, "director_DEMODIR1", "Кузнецов Илья Петрович")
    await register(h, 300, "training_DEMOTRN1", "Лебедева Ольга Николаевна")


async def test_employee_sees_schedule_and_gets_ics(h, repo):
    await reg_all(h)
    await h.send(100, BTN_TRAININGS)
    assert "Ближайшие тренинги" in h.last_text(100)
    assert "tr:ics:all" in data(h.last_markup(100))
    await h.click(100, "tr:ics:all")
    assert len(docs(h)) == 1


async def test_employee_has_no_manager_buttons(h, repo):
    await reg_all(h)
    await h.send(100, BTN_SCHEDULE)
    assert "Не понял" in h.last_text(100)  # кнопки нет, ответ не раскрывает раздел


async def test_request_to_event_flow(h, repo):
    await reg_all(h)
    await h.send(200, BTN_REQUEST)
    await h.click(200, "rq:t:1")
    await h.click(200, "rq:f:очно")
    await h.send(200, "Ресторан на Тверской")
    await h.send(200, "с 10 по 15 декабря")
    await h.send(200, "Петрова Анна Сергеевна — официант\nСмирнов Олег Игоревич — официант")
    await h.click(200, "rq:send")

    requests = await repo.list_requests()
    assert len(requests) == 1 and requests[0].status == "новая" and requests[0].count == 2
    assert "Новая заявка" in h.last_text(300)  # менеджеру ушла карточка

    await h.send(300, BTN_REQUESTS_INBOX)
    await h.click(300, f"rd:ok:{requests[0].id}")
    when = (datetime.now() + timedelta(days=30)).strftime("%d.%m.%Y 15:00")
    await h.send(300, when)
    await h.send(300, "Лебедева Ольга")

    r = (await repo.list_requests())[0]
    assert r.status == "принята" and r.event_id
    event = await repo.get_event(r.event_id)
    assert event.enrolled == 2 and event.host == "Лебедева Ольга"
    assert "принята" in h.last_text(200)  # заявителю
    assert "принята" in h.last_text(100)  # зарегистрированному участнику


async def test_decline_needs_comment_and_notifies(h, repo):
    await reg_all(h)
    rid = await repo.add_request("r1", "3", "2", "онлайн", "онлайн", "любые", "Петрова Анна Сергеевна", 1)
    await h.click(300, f"rd:no:{rid}")
    await h.send(300, "Нет свободных ведущих")
    r = await repo.get_request(rid)
    assert r.status == "отклонена" and r.comment == "Нет свободных ведущих"
    assert "отклонена" in h.last_text(200)
    await h.click(300, f"rd:ok:{rid}")  # повторная обработка запрещена
    assert (await repo.get_request(rid)).status == "отклонена"


async def test_past_date_rejected(h, repo):
    await reg_all(h)
    rid = await repo.add_request("r1", "3", "1", "очно", "x", "любые", "Иванов Иван", 1)
    await h.click(300, f"rd:ok:{rid}")
    await h.send(300, "01.01.2020 10:00")
    assert "прошла" in h.last_text(300)
    assert (await repo.get_request(rid)).status == "новая"


async def test_cancel_event_notifies_participants(h, repo):
    await reg_all(h)
    rid = await repo.add_request("r1", "3", "1", "очно", "x", "любые", "Петрова Анна Сергеевна", 1)
    start = datetime.now() + timedelta(days=5)
    eid = await repo.add_event("1", start, "очно", "x", "")
    await repo.update_request(rid, статус="принята", событие_id=eid)
    await h.click(300, f"sch:cancel!:{eid}")
    assert (await repo.get_event(eid)).status == "отменён"
    assert "отменён" in h.last_text(100)


async def test_reminder_sent_once(h, repo):
    await reg_all(h)
    rid = await repo.add_request("r1", "3", "1", "очно", "x", "любые", "Петрова Анна Сергеевна", 1)
    eid = await repo.add_event("1", repo.now_local() + timedelta(hours=10), "очно", "x", "")
    await repo.update_request(rid, статус="принята", событие_id=eid)
    assert await send_due_reminders(h.bot, repo) == 1
    assert "Напоминание" in h.last_text(100)
    assert await send_due_reminders(h.bot, repo) == 0


def test_ics_has_event_and_escapes():
    from app.models import Event, Topic

    ev = Event("1", "1", parse_datetime("15.12.2026 14:00"), "очно", "Зал; №1, Москва", "", 0, 0, "подтверждён", False)
    raw = build_ics([(ev, Topic("1", "Сервис, база", "оба", "", ""))], ZoneInfo("Europe/Moscow")).decode()
    assert "BEGIN:VEVENT" in raw and "DTSTART:20261215T110000Z" in raw
    assert "Сервис\\, база" in raw and "Зал\\; №1\\, Москва" in raw
    assert S.SCHEDULE == "Расписание"
