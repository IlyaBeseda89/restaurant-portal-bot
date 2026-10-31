"""Роли и матрица доступа (ТЗ, раздел 2)."""

from enum import Enum


class Role(str, Enum):
    EMPLOYEE = "сотрудник"
    DIRECTOR = "директор"
    TU = "ту"
    TRAINING_MANAGER = "менеджер по обучению"
    MODERATOR = "модератор"
    HR = "hr"

    @classmethod
    def parse(cls, value: str | None) -> "Role | None":
        """Понимает роль из таблицы или из пригласительной ссылки."""
        if not value:
            return None
        v = value.strip().lower().replace("ё", "е")
        aliases = {
            "сотрудник": cls.EMPLOYEE, "employee": cls.EMPLOYEE, "staff": cls.EMPLOYEE,
            "директор": cls.DIRECTOR, "director": cls.DIRECTOR,
            "ту": cls.TU, "tu": cls.TU, "территориальный управляющий": cls.TU,
            "менеджер по обучению": cls.TRAINING_MANAGER, "trainer": cls.TRAINING_MANAGER,
            "training": cls.TRAINING_MANAGER,
            "модератор": cls.MODERATOR, "модератор концепции": cls.MODERATOR,
            "moderator": cls.MODERATOR,
            "hr": cls.HR, "администратор": cls.HR, "admin": cls.HR,
        }
        return aliases.get(v)

    @property
    def title(self) -> str:
        return {
            Role.EMPLOYEE: "Сотрудник",
            Role.DIRECTOR: "Директор ресторана",
            Role.TU: "Территориальный управляющий",
            Role.TRAINING_MANAGER: "Менеджер по обучению",
            Role.MODERATOR: "Модератор концепции",
            Role.HR: "HR / администратор",
        }[self]


class Section(str, Enum):
    KNOWLEDGE = "knowledge"
    PRODUCTS = "products"
    ONBOARDING = "onboarding"
    FEEDBACK_SEND = "feedback_send"
    FEEDBACK_READ = "feedback_read"
    SCHEDULE_VIEW = "schedule_view"
    TRAINING_REQUEST = "training_request"
    REQUESTS_PROCESS = "requests_process"
    SCHEDULE_EDIT = "schedule_edit"
    MANAGE_EMPLOYEES = "manage_employees"
    MANAGE_CONTENT = "manage_content"
    STATS = "stats"


_ALL = set(Role)
_E, _D, _T, _M, _MOD, _HR = (
    Role.EMPLOYEE, Role.DIRECTOR, Role.TU, Role.TRAINING_MANAGER, Role.MODERATOR, Role.HR,
)

# Матрица 2.2. «Новичок» — не роль, а флаг: онбординг открыт новичкам дополнительно.
ACCESS: dict[Section, set[Role]] = {
    Section.KNOWLEDGE: _ALL,
    Section.PRODUCTS: _ALL,
    Section.ONBOARDING: {_M, _MOD, _HR},
    Section.FEEDBACK_SEND: _ALL,
    Section.FEEDBACK_READ: {_D, _T, _M, _HR},
    Section.SCHEDULE_VIEW: _ALL,
    Section.TRAINING_REQUEST: {_D, _T, _M, _HR},
    Section.REQUESTS_PROCESS: {_M, _HR},
    Section.SCHEDULE_EDIT: {_M, _HR},
    Section.MANAGE_EMPLOYEES: {_M, _MOD, _HR},
    Section.MANAGE_CONTENT: {_M, _MOD, _HR},
    Section.STATS: {_T, _M, _MOD, _HR},
}


def can(role: Role, section: Section, *, is_newbie: bool = False) -> bool:
    if section is Section.ONBOARDING and is_newbie:
        return True
    return role in ACCESS[section]
