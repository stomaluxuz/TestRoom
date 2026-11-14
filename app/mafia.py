"""Игра «Мафия» (офлайн): приложение раздаёт роли и ведёт фазы по таймеру.

Обсуждение — вживую (голосом); телефон у каждого показывает роль, ночные действия
и дневное голосование. Ведущего-человека нет: фазы двигает СЕРВЕР по таймеру —
на каждом чтении состояния (или действии) проверяем, не пора ли сменить фазу, и
переводим её атомарно (guarded UPDATE), чтобы при одновременных опросах переход
случился ровно один раз. Realtime — опросом, как в куизе.
"""
from __future__ import annotations

import random
import secrets
from collections import Counter
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import MafiaAction, MafiaGame, MafiaPlayer, User, utcnow
from .quiz import AVATARS
from .services import ServiceError

MIN_PLAYERS = 4
MAX_PLAYERS = 30
ROLES_SPECIAL = ("mafia", "doctor", "commissar")
_ACTION_KIND = {"mafia": "kill", "doctor": "heal", "commissar": "check"}


def _pick_avatar(emoji: str) -> str:
    return emoji if emoji in AVATARS else secrets.choice(AVATARS)


def _remaining_ms(game: MafiaGame) -> int:
    if game.phase_ends_at is None:
        return 0
    return max(0, int((game.phase_ends_at - utcnow()).total_seconds() * 1000))


async def _players(db: AsyncSession, game_id: int) -> list[MafiaPlayer]:
    return list(await db.scalars(
        select(MafiaPlayer).where(MafiaPlayer.game_id == game_id).order_by(MafiaPlayer.joined_at)
    ))


async def _actions(db: AsyncSession, game_id: int, rnd: int) -> list[MafiaAction]:
    return list(await db.scalars(
        select(MafiaAction).where(MafiaAction.game_id == game_id, MafiaAction.round == rnd)
    ))


# ------------------------------------------------ раздача ролей / баланс

def _mafia_count(n: int) -> int:
    return max(1, n // 4)  # ~25% мафии


def _assign_roles(players: list[MafiaPlayer]):
    order = players[:]
    random.shuffle(order)
    n = len(order)
    roles = ["mafia"] * _mafia_count(n) + ["commissar", "doctor"]
    roles += ["civilian"] * (n - len(roles))
    for p, role in zip(order, roles[:n]):
        p.role = role
        p.alive = True


def _check_win(players: list[MafiaPlayer]) -> str | None:
    mafia = sum(1 for p in players if p.alive and p.role == "mafia")
    town = sum(1 for p in players if p.alive and p.role != "mafia")
    if mafia == 0:
        return "town"
    if mafia >= town:
        return "mafia"
    return None


# ------------------------------------------------ создание / вход

async def _gen_pin(db: AsyncSession) -> str:
    for _ in range(50):
        pin = f"{secrets.randbelow(900000) + 100000}"
        busy = await db.scalar(
            select(func.count()).select_from(MafiaGame).where(
                MafiaGame.pin == pin, MafiaGame.phase != "ended"
            )
        )
        if not busy:
            return pin
    raise ServiceError("Не удалось создать код игры, попробуйте ещё раз.", 500)


async def create_game(db: AsyncSession, host: User, emoji: str = "") -> dict:
    """Создать игру может ЛЮБОЙ пользователь. Организатор сразу становится игроком."""
    if not (host.full_name or "").strip():
        raise ServiceError("Сначала укажите ФИО, потом создавайте игру.", 409)
    pin = await _gen_pin(db)
    game = MafiaGame(host_id=host.id, pin=pin, phase="lobby", round=0)
    db.add(game)
    await db.flush()
    db.add(MafiaPlayer(game_id=game.id, user_id=host.id, name=host.full_name.strip()[:200],
                       emoji=_pick_avatar(emoji)))
    await db.commit()
    player = await db.scalar(
        select(MafiaPlayer).where(MafiaPlayer.game_id == game.id, MafiaPlayer.user_id == host.id)
    )
    return {"game_id": game.id, "player_id": player.id, "pin": pin}


async def join(db: AsyncSession, pin: str, user: User, emoji: str = "") -> dict:
    pin = "".join(ch for ch in (pin or "") if ch.isdigit())
    if len(pin) != 6:
        raise ServiceError("Код игры — это 6 цифр.")
    if not (user.full_name or "").strip():
        raise ServiceError("Сначала укажите ФИО, потом входите в игру.", 409)
    game = await db.scalar(
        select(MafiaGame).where(MafiaGame.pin == pin, MafiaGame.phase != "ended").order_by(MafiaGame.id.desc())
    )
    if game is None:
        raise ServiceError("Игра не найдена или уже завершена.", 404)
    existing = await db.scalar(
        select(MafiaPlayer).where(MafiaPlayer.game_id == game.id, MafiaPlayer.user_id == user.id)
    )
    if existing is not None:
        if emoji in AVATARS and existing.emoji != emoji:
            existing.emoji = emoji
            await db.commit()
        return {"game_id": game.id, "player_id": existing.id, "pin": pin}
    if game.phase != "lobby":
        raise ServiceError("Игра уже идёт — вход закрыт.", 409)
    if await db.scalar(select(func.count()).select_from(MafiaPlayer).where(MafiaPlayer.game_id == game.id)) >= MAX_PLAYERS:
        raise ServiceError("Достигнут предел игроков.", 409)
    db.add(MafiaPlayer(game_id=game.id, user_id=user.id, name=user.full_name.strip()[:200],
                       emoji=_pick_avatar(emoji)))
    await db.commit()
    player = await db.scalar(
        select(MafiaPlayer).where(MafiaPlayer.game_id == game.id, MafiaPlayer.user_id == user.id)
    )
    return {"game_id": game.id, "player_id": player.id, "pin": pin}


async def _get_game(db: AsyncSession, game_id: int) -> MafiaGame:
    game = await db.get(MafiaGame, game_id)
    if game is None:
        raise ServiceError("Игра не найдена.", 404)
    return game


async def _me(db: AsyncSession, game: MafiaGame, player_id: int, user: User) -> MafiaPlayer:
    player = await db.get(MafiaPlayer, player_id)
    if player is None or player.game_id != game.id or player.user_id != user.id:
        raise ServiceError("Вы не участник этой игры.", 403)
    return player


# ------------------------------------------------ старт / завершение (организатор)

async def start(db: AsyncSession, game_id: int, user: User) -> MafiaGame:
    game = await _get_game(db, game_id)
    if game.host_id != user.id:
        raise ServiceError("Начать игру может только организатор.", 403)
    if game.phase != "lobby":
        return game
    players = await _players(db, game.id)
    if len(players) < MIN_PLAYERS:
        raise ServiceError(f"Нужно минимум {MIN_PLAYERS} игрока.")
    _assign_roles(players)
    game.round = 1
    game.phase = "night"
    game.phase_ends_at = utcnow() + timedelta(seconds=game.night_seconds)
    await db.commit()
    return game


async def end_game(db: AsyncSession, game_id: int, user: User) -> MafiaGame:
    game = await _get_game(db, game_id)
    if game.host_id != user.id:
        raise ServiceError("Завершить игру может только организатор.", 403)
    if game.phase != "ended":
        game.phase = "ended"
        game.ended_at = utcnow()
        await db.commit()
    return game


# ------------------------------------------------ авто-смена фаз (ведёт сервер)

async def _claim(db: AsyncSession, game: MafiaGame, from_phase: str, from_round: int, **vals) -> bool:
    """Атомарно перевести фазу, только если игра всё ещё в ожидаемой фазе/раунде.
    Возвращает True, если именно этот вызов совершил переход (иначе — его сделал другой опрос)."""
    res = await db.execute(
        update(MafiaGame).where(
            MafiaGame.id == game.id, MafiaGame.phase == from_phase, MafiaGame.round == from_round
        ).values(**vals)
    )
    if res.rowcount != 1:
        await db.rollback()  # кто-то уже перевёл фазу — откатываем свои смерти
        return False
    await db.commit()
    return True


def _night_all_acted(players, actions) -> bool:
    alive = [p for p in players if p.alive]
    by_kind = {"kill": set(), "heal": set(), "check": set()}
    for a in actions:
        if a.kind in by_kind:
            by_kind[a.kind].add(a.actor_id)
    for p in alive:
        if p.role == "mafia" and p.id not in by_kind["kill"]:
            return False
        if p.role == "doctor" and p.id not in by_kind["heal"]:
            return False
        if p.role == "commissar" and p.id not in by_kind["check"]:
            return False
    return True


def _vote_all_voted(players, actions) -> bool:
    voters = {a.actor_id for a in actions if a.kind == "vote"}
    return all(p.id in voters for p in players if p.alive)


async def _resolve_night(db: AsyncSession, game: MafiaGame, players, actions, now):
    kills = [a.target_id for a in actions if a.kind == "kill"]
    heals = {a.target_id for a in actions if a.kind == "heal"}
    victim = None
    if kills:
        c = Counter(kills)
        top = max(c.values())
        victim = random.choice([t for t, k in c.items() if k == top])
    if victim is not None and victim in heals:
        victim = None  # доктор спас
    if victim is not None:
        vp = next((p for p in players if p.id == victim), None)
        if vp:
            vp.alive = False
    winner = _check_win(players)
    await _claim(
        db, game, "night", game.round,
        last_killed_id=victim or 0,
        phase="ended" if winner else "day",
        winner=winner, ended_at=now if winner else None,
        phase_ends_at=None if winner else now + timedelta(seconds=game.day_seconds),
    )


async def _resolve_vote(db: AsyncSession, game: MafiaGame, players, actions, now):
    votes = [a.target_id for a in actions if a.kind == "vote"]
    out = None
    if votes:
        c = Counter(votes)
        top = max(c.values())
        cands = [t for t, k in c.items() if k == top]
        if len(cands) == 1:  # ничья — никого не выгоняем
            out = cands[0]
    if out is not None:
        op = next((p for p in players if p.id == out), None)
        if op:
            op.alive = False
    winner = _check_win(players)
    await _claim(
        db, game, "vote", game.round,
        last_out_id=out or 0,
        phase="ended" if winner else "night",
        winner=winner, ended_at=now if winner else None,
        round=game.round if winner else game.round + 1,
        phase_ends_at=None if winner else now + timedelta(seconds=game.night_seconds),
    )


async def _advance_if_due(db: AsyncSession, game_id: int) -> MafiaGame:
    """Двигаем фазу, если пришло время или все сходили. Вызывается на каждом чтении/действии."""
    game = await _get_game(db, game_id)
    if game.phase in ("lobby", "ended"):
        return game
    now = utcnow()
    due = game.phase_ends_at is not None and now >= game.phase_ends_at
    players = await _players(db, game.id)
    actions = await _actions(db, game.id, game.round)
    if game.phase == "night":
        if due or _night_all_acted(players, actions):
            await _resolve_night(db, game, players, actions, now)
    elif game.phase == "day":
        if due:
            await _claim(db, game, "day", game.round, phase="vote", last_out_id=None,
                         phase_ends_at=now + timedelta(seconds=game.vote_seconds))
    elif game.phase == "vote":
        if due or _vote_all_voted(players, actions):
            await _resolve_vote(db, game, players, actions, now)
    # после Core-UPDATE (guarded) ORM-объект устаревает при expire_on_commit=False — перечитываем
    await db.refresh(game)
    return game


# ------------------------------------------------ действия игрока

async def _upsert_action(db: AsyncSession, game: MafiaGame, actor: MafiaPlayer, kind: str, target_id: int):
    row = await db.scalar(
        select(MafiaAction).where(
            MafiaAction.game_id == game.id, MafiaAction.round == game.round,
            MafiaAction.kind == kind, MafiaAction.actor_id == actor.id,
        )
    )
    if row is None:
        db.add(MafiaAction(game_id=game.id, round=game.round, kind=kind,
                           actor_id=actor.id, target_id=target_id))
    else:
        row.target_id = target_id
    await db.commit()


async def night_action(db: AsyncSession, game_id: int, player_id: int, user: User, target_id: int) -> dict:
    game = await _advance_if_due(db, game_id)
    player = await _me(db, game, player_id, user)
    if game.phase != "night":
        raise ServiceError("Сейчас не ночь.", 409)
    if not player.alive:
        raise ServiceError("Вы выбыли.", 409)
    kind = _ACTION_KIND.get(player.role)
    if not kind:
        raise ServiceError("У вашей роли нет ночного действия.", 409)
    target = await db.get(MafiaPlayer, target_id)
    if target is None or target.game_id != game.id or not target.alive:
        raise ServiceError("Нельзя выбрать этого игрока.")
    if kind in ("kill", "check") and target.id == player.id:
        raise ServiceError("Нельзя выбрать себя.")
    await _upsert_action(db, game, player, kind, target.id)
    result = None
    if kind == "check":
        result = "mafia" if target.role == "mafia" else "not"
    await _advance_if_due(db, game_id)  # вдруг все сходили — сразу резолвим
    return {"ok": True, "check_result": result}


async def cast_vote(db: AsyncSession, game_id: int, player_id: int, user: User, target_id: int) -> dict:
    game = await _advance_if_due(db, game_id)
    player = await _me(db, game, player_id, user)
    if game.phase != "vote":
        raise ServiceError("Сейчас не голосование.", 409)
    if not player.alive:
        raise ServiceError("Вы выбыли — голосовать нельзя.", 409)
    target = await db.get(MafiaPlayer, target_id)
    if target is None or target.game_id != game.id or not target.alive:
        raise ServiceError("Нельзя выбрать этого игрока.")
    await _upsert_action(db, game, player, "vote", target.id)
    await _advance_if_due(db, game_id)
    return {"ok": True}


# ------------------------------------------------ состояние для экрана

async def play_state(db: AsyncSession, game_id: int, player_id: int, user: User) -> dict:
    game = await _advance_if_due(db, game_id)
    player = await _me(db, game, player_id, user)
    players = await _players(db, game.id)
    alive = [p for p in players if p.alive]
    ended = game.phase == "ended"

    def pub(p: MafiaPlayer) -> dict:
        reveal = (not p.alive) or ended or p.id == player.id  # роль видна у мёртвых, в конце и у себя
        return {"id": p.id, "name": p.name, "emoji": p.emoji or "🙂", "alive": p.alive,
                "role": p.role if reveal else None}

    out = {
        "phase": game.phase, "round": game.round, "pin": game.pin,
        "is_host": game.host_id == user.id, "remaining_ms": _remaining_ms(game),
        "me": {"id": player.id, "name": player.name, "emoji": player.emoji or "🙂",
               "role": player.role, "alive": player.alive},
        "players": [pub(p) for p in players], "alive_count": len(alive),
    }
    if game.phase == "lobby":
        out["players_count"] = len(players)
        out["min_players"] = MIN_PLAYERS
        out["can_start"] = game.host_id == user.id and len(players) >= MIN_PLAYERS
    elif game.phase == "night":
        info = {"role": player.role, "can_act": False}
        if player.alive and player.role in ROLES_SPECIAL:
            kind = _ACTION_KIND[player.role]
            act = await db.scalar(select(MafiaAction).where(
                MafiaAction.game_id == game.id, MafiaAction.round == game.round,
                MafiaAction.kind == kind, MafiaAction.actor_id == player.id))
            info.update(can_act=True, kind=kind, acted=act.target_id if act else None)
            if player.role == "commissar" and act is not None:
                tgt = next((p for p in players if p.id == act.target_id), None)
                info["check_result"] = "mafia" if (tgt and tgt.role == "mafia") else "not"
        if player.role == "mafia":
            info["mates"] = [{"name": p.name, "emoji": p.emoji or "🙂"}
                             for p in alive if p.role == "mafia" and p.id != player.id]
        out["night"] = info
    elif game.phase == "day":
        kp = None
        if game.last_killed_id:
            k = next((p for p in players if p.id == game.last_killed_id), None)
            if k:
                kp = {"name": k.name, "emoji": k.emoji or "🙂", "role": k.role}
        out["day"] = {"killed": kp}
    elif game.phase == "vote":
        mine = await db.scalar(select(MafiaAction).where(
            MafiaAction.game_id == game.id, MafiaAction.round == game.round,
            MafiaAction.kind == "vote", MafiaAction.actor_id == player.id))
        rows = await db.execute(select(MafiaAction.target_id, func.count()).where(
            MafiaAction.game_id == game.id, MafiaAction.round == game.round,
            MafiaAction.kind == "vote").group_by(MafiaAction.target_id))
        out["vote"] = {"voted": mine.target_id if mine else None,
                       "tally": {int(t): int(c) for t, c in rows}}
    elif game.phase == "ended":
        out["result"] = {"winner": game.winner, "last_out_id": game.last_out_id or 0,
                         "roles": [{"name": p.name, "emoji": p.emoji or "🙂",
                                    "role": p.role, "alive": p.alive} for p in players]}
    return out
