from aiogram import Router

from app.handlers import feedback, knowledge, menu, registration


def build_router() -> Router:
    root = Router(name="root")
    # Порядок важен: общие «ловушки» (menu) подключаются последними
    root.include_routers(
        registration.router,
        feedback.chat_router,
        knowledge.router,
        feedback.router,
        menu.router,
    )
    return root
