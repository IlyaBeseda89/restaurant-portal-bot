from aiogram import Router

from app.handlers import (
    admin,
    feedback,
    knowledge,
    menu,
    products,
    registration,
    start,
    stats,
    training_requests,
    trainings,
)


def build_router() -> Router:
    root = Router(name="root")
    # Порядок важен: общие «ловушки» (menu) подключаются последними
    root.include_routers(
        registration.router,
        feedback.chat_router,
        knowledge.router,
        products.router,
        trainings.router,
        training_requests.router,
        admin.router,
        start.router,
        stats.router,
        feedback.router,
        menu.router,
    )
    return root
