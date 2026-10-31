from datetime import date

from app.handlers.feedback import hashtag
from app.handlers.registration import Invite, match_employee, parse_invite
from app.keyboards import BTN_ADMIN, BTN_REQUEST, BTN_START, main_menu
from app.models import Employee, parse_date
from app.roles import Role, Section, can


def buttons(markup):
    return {b.text for row in markup.keyboard for b in row}


def test_access_matrix():
    assert can(Role.EMPLOYEE, Section.KNOWLEDGE)
    assert not can(Role.EMPLOYEE, Section.TRAINING_REQUEST)
    assert can(Role.DIRECTOR, Section.TRAINING_REQUEST)
    assert not can(Role.DIRECTOR, Section.ONBOARDING)
    assert can(Role.EMPLOYEE, Section.ONBOARDING, is_newbie=True)
    assert can(Role.TRAINING_MANAGER, Section.REQUESTS_PROCESS)
    assert not can(Role.HR, Section.TRAINING_REQUEST)


def test_menu_by_role():
    assert BTN_REQUEST not in buttons(main_menu(Role.EMPLOYEE, False))
    assert BTN_REQUEST in buttons(main_menu(Role.DIRECTOR, False))
    assert BTN_ADMIN in buttons(main_menu(Role.HR, False))
    assert BTN_START in buttons(main_menu(Role.EMPLOYEE, True))


def test_parse_invite():
    assert parse_invite("director_AB12") == Invite(Role.DIRECTOR, "AB12")
    assert parse_invite("AB12") == Invite(None, "AB12")
    assert parse_invite("tu_X_Y") == Invite(Role.TU, "X_Y")
    assert parse_invite(None) is None


def test_role_parse_from_table():
    assert Role.parse("ТУ") is Role.TU
    assert Role.parse("Менеджер по обучению") is Role.TRAINING_MANAGER
    assert Role.parse("HR") is Role.HR
    assert Role.parse("кто-то") is None


def test_newbie_flag():
    e = Employee("1", None, "А Б", "", "", "", Role.EMPLOYEE, date(2026, 10, 20), True, "", None)
    assert e.is_newbie(date(2026, 10, 31), 28)
    assert not e.is_newbie(date(2026, 12, 31), 28)
    e.newbie_override = False
    assert not e.is_newbie(date(2026, 10, 31), 28)


def test_parse_date_formats():
    assert parse_date("31.10.2026") == date(2026, 10, 31)
    assert parse_date("2026-10-31") == date(2026, 10, 31)
    assert parse_date("ерунда") is None


def test_hashtag():
    assert hashtag("Траттория на Невском") == "#Траттория_на_Невском"
    assert hashtag("") == ""


async def test_match_by_code_and_name(repo):
    r = await match_employee(repo, Invite(Role.EMPLOYEE, "DEMOEMP1"), "петрова  анна сергеевна", 111)
    assert r.employee and r.employee.id == "1"
    r = await match_employee(repo, Invite(Role.EMPLOYEE, "DEMOEMP1"), "Иванов Иван", 111)
    assert r.employee is None and "ФИО не совпадает" in r.problem


async def test_match_by_name_without_code(repo):
    r = await match_employee(repo, Invite(Role.DIRECTOR, "WRONG"), "Кузнецов Илья Петрович", 5)
    assert r.employee and r.employee.role is Role.DIRECTOR
    r = await match_employee(repo, Invite(Role.HR, "WRONG"), "Кузнецов Илья Петрович", 5)
    assert r.employee is None


async def test_materials_filtered_by_concept(repo):
    trat = {m.id for m in await repo.list_materials("trat")}
    bistro = {m.id for m in await repo.list_materials("bistro")}
    assert "5" in trat and "6" not in trat
    assert "6" in bistro and "5" not in bistro
    assert "9" not in trat  # скрытый
