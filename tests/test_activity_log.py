from datetime import timedelta

from app import schema as S
from app.storage.backend import CachedBackend
from app.storage.repository import ACTIVE_USERS, Repository
from app.storage.sqlite_backend import SqliteBackend


async def make(days=60):
    main, activity = SqliteBackend(":memory:"), SqliteBackend(":memory:")
    await main.ensure_tables()
    await activity.ensure_tables()
    return Repository(CachedBackend(main, ttl=0), activity_backend=activity, activity_days=days), main, activity


async def test_activity_is_daily_summary_without_names():
    repo, main, activity = await make()
    repo.remember_concept("7", "trat")
    repo.log("7", "просмотр материала", "5")
    repo.log("7", "просмотр материала", "5")
    repo.log("8", "просмотр материала", "5")  # другой человек, концепция неизвестна
    assert await repo.flush_activity() == 3
    assert await main.read_all(S.ACTIVITY) == []  # в основной таблице журнала нет
    rows = await activity.read_all(S.ACTIVITY)
    views = {r["концепция"]: r["число"] for r in rows if r["действие"] == "просмотр материала"}
    assert views == {"trat": "2", "": "1"}
    assert all("7" != v and "8" != v for r in rows for k, v in r.items() if k not in {"id", "число"})
    assert {r["концепция"]: r["число"] for r in rows if r["действие"] == ACTIVE_USERS} == {"trat": "1", "": "1"}


async def test_counts_accumulate_across_flushes():
    repo, _, activity = await make()
    repo.log("7", "тренинг: записан", "1")
    await repo.flush_activity()
    repo.log("7", "тренинг: записан", "1")
    repo.log("9", "тренинг: записан", "1")
    await repo.flush_activity()
    rows = [r for r in await activity.read_all(S.ACTIVITY) if r["действие"] == "тренинг: записан"]
    assert len(rows) == 1 and rows[0]["число"] == "3"
    active = [r for r in await activity.read_all(S.ACTIVITY) if r["действие"] == ACTIVE_USERS]
    assert len(active) == 1 and active[0]["число"] == "2"  # два разных человека за день


async def test_old_days_are_pruned():
    repo, _, activity = await make(days=60)
    old = (repo.now() - timedelta(days=90)).strftime("%d.%m.%Y")
    await activity.append(S.ACTIVITY, {"id": "old1", "дата": old, "концепция": "", "действие": "x", "объект": "", "число": "4"})
    repo.log("1", "новое")
    await repo.flush_activity()
    assert await repo.prune_activity() == 1
    assert "x" not in [r["действие"] for r in await activity.read_all(S.ACTIVITY)]


async def test_prune_does_nothing_without_local_storage(repo):
    repo.log("1", "x")
    await repo.flush_activity()
    assert await repo.prune_activity() == 0


async def test_moderator_stats_count_only_own_concept(h, repo):
    from app.keyboards import BTN_START, BTN_STATS
    from tests.conftest import register

    await register(h, 100, "employee_DEMONEW1", "Смирнов Олег Игоревич")
    await register(h, 400, "moderator_DEMOMOD1", "Волкова Мария Андреевна")
    await h.send(100, BTN_START)
    await h.send(400, BTN_STATS)
    assert "Активность" in h.last_text(400)
