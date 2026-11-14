from datetime import timedelta

import pytest

from app import mafia
from app import services as svc
from app.models import MafiaGame, MafiaPlayer, utcnow
from sqlalchemy import select


async def make_user(db, uid, name):
    u = await svc.get_or_create_user(db, uid)
    await svc.set_full_name(db, u, name)
    return u


async def setup_game(db, n=5):
    host = await make_user(db, 600, "Хост")
    r = await mafia.create_game(db, host)
    users = [host]
    for i in range(1, n):
        u = await make_user(db, 600 + i, f"Игрок{i}")
        await mafia.join(db, r["pin"], u)
        users.append(u)
    return r["game_id"], users


async def players_by_order(db, game_id):
    return list(await db.scalars(
        select(MafiaPlayer).where(MafiaPlayer.game_id == game_id).order_by(MafiaPlayer.joined_at)
    ))


def test_role_balance():
    assert mafia._mafia_count(4) == 1
    assert mafia._mafia_count(8) == 2
    assert mafia._mafia_count(12) == 3


async def test_create_and_join(db):
    gid, users = await setup_game(db, 5)
    ps = await players_by_order(db, gid)
    assert len(ps) == 5 and ps[0].name == "Хост"  # организатор — тоже игрок


async def test_create_needs_name(db):
    nameless = await svc.get_or_create_user(db, 650)
    with pytest.raises(svc.ServiceError) as e:
        await mafia.create_game(db, nameless)
    assert e.value.status == 409


async def test_start_requires_host_and_min_players(db):
    host = await make_user(db, 700, "Хост")
    r = await mafia.create_game(db, host)
    other = await make_user(db, 701, "Другой")
    await mafia.join(db, r["pin"], other)
    # мало игроков
    with pytest.raises(svc.ServiceError):
        await mafia.start(db, r["game_id"], host)
    # не организатор не может
    for i in range(2, 5):
        await mafia.join(db, r["pin"], await make_user(db, 700 + i, f"Игрок {i}"))
    with pytest.raises(svc.ServiceError) as e:
        await mafia.start(db, r["game_id"], other)
    assert e.value.status == 403


async def _fixed_roles(db, gid):
    """Задаём детерминированные роли: p0 мафия, p1 доктор, p2 комиссар, p3/p4 мирные."""
    ps = await players_by_order(db, gid)
    roles = ["mafia", "doctor", "commissar", "civilian", "civilian"]
    for p, role in zip(ps, roles):
        p.role, p.alive = role, True
    await db.commit()
    return ps


async def test_full_game_town_wins(db):
    gid, users = await setup_game(db, 5)
    await mafia.start(db, gid, users[0])
    ps = await _fixed_roles(db, gid)
    maf, doc, comm, civ1, civ2 = ps

    # ночь: мафия убивает civ1, доктор лечит civ2, комиссар проверяет мафию
    await mafia.night_action(db, gid, maf.id, users[0], civ1.id)
    await mafia.night_action(db, gid, doc.id, users[1], civ2.id)
    chk = await mafia.night_action(db, gid, comm.id, users[2], maf.id)
    assert chk["check_result"] == "mafia"

    # все спец-роли сходили → ночь разрешилась автоматически
    game = await db.get(MafiaGame, gid)
    await db.refresh(game)
    assert game.phase == "day" and game.last_killed_id == civ1.id
    assert (await db.get(MafiaPlayer, civ1.id)).alive is False  # не спасли

    # день истёк → голосование
    game.phase_ends_at = utcnow() - timedelta(seconds=1)
    await db.commit()
    st = await mafia.play_state(db, gid, maf.id, users[0])
    assert st["phase"] == "vote"

    # живые голосуют против мафии → мафия выбывает → город победил
    for pl, usr in [(doc, users[1]), (comm, users[2]), (civ2, users[4]), (maf, users[0])]:
        await mafia.cast_vote(db, gid, pl.id, usr, maf.id)
    game = await db.get(MafiaGame, gid)
    await db.refresh(game)
    assert game.phase == "ended" and game.winner == "town"


async def test_doctor_save_blocks_kill(db):
    gid, users = await setup_game(db, 5)
    await mafia.start(db, gid, users[0])
    maf, doc, comm, civ1, civ2 = await _fixed_roles(db, gid)
    # мафия бьёт civ1, доктор лечит именно civ1 → никто не умирает
    await mafia.night_action(db, gid, maf.id, users[0], civ1.id)
    await mafia.night_action(db, gid, doc.id, users[1], civ1.id)
    await mafia.night_action(db, gid, comm.id, users[2], civ2.id)
    game = await db.get(MafiaGame, gid)
    await db.refresh(game)
    assert game.phase == "day" and game.last_killed_id == 0
    assert (await db.get(MafiaPlayer, civ1.id)).alive is True


async def test_night_auto_resolves_on_timer(db):
    gid, users = await setup_game(db, 5)
    await mafia.start(db, gid, users[0])
    await _fixed_roles(db, gid)
    game = await db.get(MafiaGame, gid)
    game.phase_ends_at = utcnow() - timedelta(seconds=1)  # ночь истекла, никто не ходил
    await db.commit()
    st = await mafia.play_state(db, gid, (await players_by_order(db, gid))[0].id, users[0])
    assert st["phase"] == "day" and st["day"]["killed"] is None  # никого не убили


async def test_role_privacy(db):
    gid, users = await setup_game(db, 5)
    await mafia.start(db, gid, users[0])
    maf, doc, comm, civ1, civ2 = await _fixed_roles(db, gid)
    # мирный civ1 не видит чужих ролей, но видит свою
    st = await mafia.play_state(db, gid, civ1.id, users[3])
    roles_seen = {p["id"]: p["role"] for p in st["players"]}
    assert roles_seen[civ1.id] == "civilian"  # свою видит
    assert roles_seen[maf.id] is None  # чужую (живого) — нет
    assert st["me"]["role"] == "civilian"
    # мафия видит подельников (тут одна мафия — список пуст, но поле есть)
    stm = await mafia.play_state(db, gid, maf.id, users[0])
    assert "mates" in stm["night"]
