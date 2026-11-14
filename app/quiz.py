"""Живой куиз в стиле Kahoot: синхронная игра, ведёт учитель.

Темпом управляет учитель (жмёт «Далее»): лобби → вопрос → показ ответа → … → финал.
Все отвечают одновременно, очки = правильность + скорость (как в Kahoot, 500..1000).
Realtime делается опросом (polling): клиент тянет состояние, таймер крутится локально
от присланного remaining_ms. Единственное долгое место — генерация вопросов ИИ — живёт
в эндпоинте (вне удержания единственного соединения с БД)."""
from __future__ import annotations

import secrets
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import QuizAnswer, QuizGame, QuizPlayer, User, utcnow
from .services import ServiceError, require_teacher

MIN_SECONDS, MAX_SECONDS = 5, 120
MAX_QUESTIONS = 20
BASE_POINTS = 500  # правильный ответ — минимум столько; плюс бонус за скорость до 1000


# ------------------------------------------------ очки (формула как в Kahoot)

def score_for(elapsed_ms: int, limit_ms: int, correct: bool) -> int:
    """Правильный ответ: BASE + бонус за скорость (быстрее — больше), до 1000. Неверный — 0."""
    if not correct:
        return 0
    if limit_ms <= 0:
        return 1000
    frac = min(1.0, max(0.0, elapsed_ms / limit_ms))
    return int(round(BASE_POINTS + (1000 - BASE_POINTS) * (1 - frac)))


def _limit_ms(game: QuizGame) -> int:
    return int(game.seconds) * 1000


def _elapsed_ms(game: QuizGame) -> int:
    if game.question_started_at is None:
        return 0
    return int((utcnow() - game.question_started_at).total_seconds() * 1000)


def _remaining_ms(game: QuizGame) -> int:
    return max(0, _limit_ms(game) - _elapsed_ms(game))


# ------------------------------------------------ создание / вход

async def _gen_pin(db: AsyncSession) -> str:
    """6-значный код, не совпадающий с кодом активной (не завершённой) игры."""
    for _ in range(50):
        pin = f"{secrets.randbelow(900000) + 100000}"
        busy = await db.scalar(
            select(func.count()).select_from(QuizGame).where(
                QuizGame.pin == pin, QuizGame.phase != "ended"
            )
        )
        if not busy:
            return pin
    raise ServiceError("Не удалось создать код игры, попробуйте ещё раз.", 500)


async def create_game(
    db: AsyncSession, host: User, topic: str, lang: str, questions: list[dict], seconds: int
) -> QuizGame:
    """Создать игру из уже сгенерированных вопросов (генерацию делает эндпоинт)."""
    require_teacher(host)
    if not questions:
        raise ServiceError("Не удалось собрать вопросы для куиза, попробуйте другую тему.")
    seconds = max(MIN_SECONDS, min(int(seconds or 20), MAX_SECONDS))
    pin = await _gen_pin(db)
    game = QuizGame(
        host_id=host.id, pin=pin, topic=(topic or "").strip()[:300],
        lang=lang if lang in ("ru", "uz", "en") else "ru",
        seconds=seconds, questions=questions[:MAX_QUESTIONS], phase="lobby", current_index=-1,
    )
    db.add(game)
    await db.commit()
    return game


async def _get_game(db: AsyncSession, game_id: int) -> QuizGame:
    game = await db.get(QuizGame, game_id)
    if game is None:
        raise ServiceError("Игра не найдена.", 404)
    return game


async def join(db: AsyncSession, pin: str, user: User) -> dict:
    """Войти в игру по коду. Имя обязательно (студент выкладывает результат под ФИО)."""
    pin = "".join(ch for ch in (pin or "") if ch.isdigit())
    if len(pin) != 6:
        raise ServiceError("Код игры — это 6 цифр.")
    if not (user.full_name or "").strip():
        raise ServiceError("Сначала укажите ФИО, потом входите в игру.", 409)
    game = await db.scalar(
        select(QuizGame).where(QuizGame.pin == pin, QuizGame.phase != "ended")
        .order_by(QuizGame.id.desc())
    )
    if game is None:
        raise ServiceError("Игра не найдена или уже завершена.", 404)
    if game.phase != "lobby":
        raise ServiceError("Игра уже идёт — вход закрыт.", 409)
    existing = await db.scalar(
        select(QuizPlayer).where(QuizPlayer.game_id == game.id, QuizPlayer.user_id == user.id)
    )
    if existing is None:
        db.add(QuizPlayer(game_id=game.id, user_id=user.id, name=user.full_name.strip()[:200]))
        await db.commit()
        player = await db.scalar(
            select(QuizPlayer).where(QuizPlayer.game_id == game.id, QuizPlayer.user_id == user.id)
        )
    else:
        player = existing
    return {"game_id": game.id, "player_id": player.id, "pin": pin}


# ------------------------------------------------ ход игры (ведёт учитель)

async def advance(db: AsyncSession, game_id: int, host: User) -> QuizGame:
    """Следующий шаг: лобби→вопрос, вопрос→показ ответа, показ→следующий вопрос/финал."""
    game = await _get_game(db, game_id)
    if game.host_id != host.id:
        raise ServiceError("Управлять игрой может только её ведущий.", 403)
    n = len(game.questions or [])
    if game.phase == "lobby":
        players = await db.scalar(select(func.count()).select_from(QuizPlayer).where(QuizPlayer.game_id == game.id))
        if not players:
            raise ServiceError("Нет ни одного игрока — подождите, пока зайдут по коду.")
        game.current_index = 0
        game.phase = "question"
        game.question_started_at = utcnow()
    elif game.phase == "question":
        game.phase = "reveal"
    elif game.phase == "reveal":
        if game.current_index + 1 < n:
            game.current_index += 1
            game.phase = "question"
            game.question_started_at = utcnow()
        else:
            game.phase = "ended"
            game.ended_at = utcnow()
    await db.commit()
    return game


async def end_game(db: AsyncSession, game_id: int, host: User) -> QuizGame:
    game = await _get_game(db, game_id)
    if game.host_id != host.id:
        raise ServiceError("Управлять игрой может только её ведущий.", 403)
    if game.phase != "ended":
        game.phase = "ended"
        game.ended_at = utcnow()
        await db.commit()
    return game


# ------------------------------------------------ ответ игрока

async def submit_answer(
    db: AsyncSession, game_id: int, player_id: int, user: User, q_index: int, option: int
) -> dict:
    game = await _get_game(db, game_id)
    if game.phase != "question":
        raise ServiceError("Приём ответов закрыт.", 409)
    if q_index != game.current_index:
        raise ServiceError("Этот вопрос уже не активен.", 409)
    player = await db.get(QuizPlayer, player_id)
    if player is None or player.game_id != game.id or player.user_id != user.id:
        raise ServiceError("Вы не участник этой игры.", 403)
    dup = await db.scalar(
        select(QuizAnswer).where(QuizAnswer.player_id == player_id, QuizAnswer.q_index == q_index)
    )
    if dup is not None:
        return {"correct": dup.is_correct, "points": dup.points, "score": player.score, "already": True}
    q = game.questions[q_index]
    opts = q.get("options") or []
    if not isinstance(option, int) or not (0 <= option < len(opts)):
        raise ServiceError("Такого варианта нет.")
    elapsed = min(_elapsed_ms(game), _limit_ms(game))
    correct = option == int(q.get("correct", -1))
    points = score_for(elapsed, _limit_ms(game), correct)
    db.add(QuizAnswer(
        game_id=game.id, player_id=player_id, q_index=q_index, chosen=option,
        is_correct=correct, points=points, ms=elapsed,
    ))
    player.score = (player.score or 0) + points
    await db.commit()
    return {"correct": correct, "points": points, "score": player.score}


# ------------------------------------------------ состояние для экранов

async def _players_ranked(db: AsyncSession, game_id: int) -> list[QuizPlayer]:
    return list(await db.scalars(
        select(QuizPlayer).where(QuizPlayer.game_id == game_id)
        .order_by(QuizPlayer.score.desc(), QuizPlayer.joined_at)
    ))


async def _answer_counts(db: AsyncSession, game_id: int, q_index: int, n_opts: int) -> list[int]:
    rows = await db.execute(
        select(QuizAnswer.chosen, func.count()).where(
            QuizAnswer.game_id == game_id, QuizAnswer.q_index == q_index
        ).group_by(QuizAnswer.chosen)
    )
    counts = [0] * n_opts
    for chosen, cnt in rows:
        if 0 <= chosen < n_opts:
            counts[chosen] = cnt
    return counts


def _leaderboard(players: list[QuizPlayer], deltas: dict[int, int] | None = None, top: int = 5) -> list[dict]:
    out = []
    for i, p in enumerate(players[:top]):
        row = {"name": p.name, "score": p.score, "rank": i + 1}
        if deltas is not None:
            row["delta"] = deltas.get(p.id, 0)
        out.append(row)
    return out


async def host_state(db: AsyncSession, game_id: int, host: User) -> dict:
    game = await _get_game(db, game_id)
    if game.host_id != host.id:
        raise ServiceError("Это не ваша игра.", 403)
    n = len(game.questions or [])
    players = await _players_ranked(db, game.id)
    out = {
        "phase": game.phase, "pin": game.pin, "topic": game.topic,
        "total": n, "index": game.current_index, "players": len(players),
        "is_last": game.current_index + 1 >= n,
    }
    if game.phase == "lobby":
        out["joined"] = [p.name for p in players]
        out["can_start"] = len(players) > 0
    elif game.phase == "question":
        q = game.questions[game.current_index]
        answered = await db.scalar(
            select(func.count()).select_from(QuizAnswer).where(
                QuizAnswer.game_id == game.id, QuizAnswer.q_index == game.current_index
            )
        )
        out["question"] = {"text": q["q"], "options": q["options"]}
        out["answered"] = answered or 0
        out["remaining_ms"] = _remaining_ms(game)
        out["seconds"] = game.seconds
    elif game.phase == "reveal":
        q = game.questions[game.current_index]
        counts = await _answer_counts(db, game.id, game.current_index, len(q["options"]))
        deltas = {
            pid: pts for pid, pts in await db.execute(
                select(QuizAnswer.player_id, QuizAnswer.points).where(
                    QuizAnswer.game_id == game.id, QuizAnswer.q_index == game.current_index
                )
            )
        }
        out["question"] = {"text": q["q"], "options": q["options"]}
        out["correct"] = int(q["correct"])
        out["counts"] = counts
        out["leaderboard"] = _leaderboard(players, deltas)
    elif game.phase == "ended":
        out["podium"] = _leaderboard(players, top=3)
        out["leaderboard"] = _leaderboard(players, top=10)
    return out


async def play_state(db: AsyncSession, game_id: int, player_id: int, user: User) -> dict:
    game = await _get_game(db, game_id)
    player = await db.get(QuizPlayer, player_id)
    if player is None or player.game_id != game.id or player.user_id != user.id:
        raise ServiceError("Вы не участник этой игры.", 403)
    n = len(game.questions or [])
    out = {"phase": game.phase, "total": n, "name": player.name}
    if game.phase == "lobby":
        out["players"] = await db.scalar(
            select(func.count()).select_from(QuizPlayer).where(QuizPlayer.game_id == game.id)
        )
    elif game.phase == "question":
        q = game.questions[game.current_index]
        mine = await db.scalar(
            select(QuizAnswer).where(QuizAnswer.player_id == player_id, QuizAnswer.q_index == game.current_index)
        )
        out["index"] = game.current_index
        out["question"] = {"text": q["q"], "options": q["options"]}  # без правильного
        out["remaining_ms"] = _remaining_ms(game)
        out["seconds"] = game.seconds
        out["answered"] = mine is not None
        out["chosen"] = mine.chosen if mine is not None else None
    elif game.phase == "reveal":
        q = game.questions[game.current_index]
        mine = await db.scalar(
            select(QuizAnswer).where(QuizAnswer.player_id == player_id, QuizAnswer.q_index == game.current_index)
        )
        players = await _players_ranked(db, game.id)
        rank = next((i + 1 for i, p in enumerate(players) if p.id == player_id), len(players))
        out["index"] = game.current_index
        out["correct"] = int(q["correct"])
        out["you"] = {
            "answered": mine is not None,
            "correct": bool(mine.is_correct) if mine else False,
            "points": mine.points if mine else 0,
            "score": player.score, "rank": rank,
        }
        out["leaderboard"] = _leaderboard(players)
    elif game.phase == "ended":
        players = await _players_ranked(db, game.id)
        rank = next((i + 1 for i, p in enumerate(players) if p.id == player_id), len(players))
        out["podium"] = _leaderboard(players, top=3)
        out["rank"] = rank
        out["score"] = player.score
        out["players"] = len(players)
    return out


async def host_games(db: AsyncSession, host: User, limit: int = 20) -> list[dict]:
    """Последние игры ведущего (для истории/возврата в активную)."""
    rows = await db.scalars(
        select(QuizGame).where(QuizGame.host_id == host.id).order_by(QuizGame.id.desc()).limit(limit)
    )
    return [
        {"id": g.id, "pin": g.pin, "topic": g.topic, "phase": g.phase,
         "total": len(g.questions or []), "created_at": g.created_at.isoformat()}
        for g in rows
    ]
