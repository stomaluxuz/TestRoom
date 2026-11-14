import pytest

from app import quiz
from app import services as svc

from .conftest import ADMIN_ID
from .test_services import make_student, make_teacher

QS = [
    {"q": "2+2?", "options": ["3", "4", "5"], "correct": 1},
    {"q": "Столица Узбекистана?", "options": ["Самарканд", "Ташкент"], "correct": 1},
    {"q": "Цвет неба?", "options": ["Зелёный", "Синий", "Красный"], "correct": 1},
]


async def _game(db, seconds=20):
    teacher = await make_teacher(db, 300, "Ведущий Куиза")
    game = await quiz.create_game(db, teacher, "Разное", "ru", QS, seconds)
    return teacher, game


def test_score_formula():
    # мгновенный правильный ответ — 1000, на пределе времени — 500, неверный — 0
    assert quiz.score_for(0, 20000, True) == 1000
    assert quiz.score_for(20000, 20000, True) == 500
    assert quiz.score_for(10000, 20000, True) == 750
    assert quiz.score_for(5000, 20000, False) == 0


async def test_create_requires_teacher(db):
    student = await make_student(db, 301)
    with pytest.raises(svc.ServiceError) as e:
        await quiz.create_game(db, student, "Тема", "ru", QS, 20)
    assert e.value.status == 403


async def test_full_game_flow(db):
    teacher, game = await _game(db)
    assert game.phase == "lobby" and len(game.pin) == 6 and game.current_index == -1

    # два студента заходят по коду
    s1 = await make_student(db, 311, "Алиса")
    s2 = await make_student(db, 312, "Боря")
    j1 = await quiz.join(db, game.pin, s1)
    j2 = await quiz.join(db, game.pin, s2)
    assert j1["game_id"] == game.id and j1["player_id"] != j2["player_id"]

    # повторный вход того же — тот же игрок, не дубль
    j1b = await quiz.join(db, game.pin, s1)
    assert j1b["player_id"] == j1["player_id"]

    # нельзя стартовать без игроков — но игроки есть; стартуем
    host = await quiz.host_state(db, game.id, teacher)
    assert host["phase"] == "lobby" and host["players"] == 2 and host["can_start"] is True

    await quiz.advance(db, game.id, teacher)  # лобби → вопрос 0
    st = await quiz.play_state(db, game.id, j1["player_id"], s1)
    assert st["phase"] == "question" and "correct" not in st["question"]
    assert st["question"]["text"] == "2+2?"

    # Алиса отвечает верно, Боря — неверно
    r1 = await quiz.submit_answer(db, game.id, j1["player_id"], s1, 0, 1)
    r2 = await quiz.submit_answer(db, game.id, j2["player_id"], s2, 0, 0)
    assert r1["correct"] is True and r1["points"] >= 500
    assert r2["correct"] is False and r2["points"] == 0

    # повторный ответ не засчитывается второй раз
    again = await quiz.submit_answer(db, game.id, j1["player_id"], s1, 0, 2)
    assert again.get("already") is True and again["points"] == r1["points"]

    # показ ответа
    await quiz.advance(db, game.id, teacher)  # вопрос → reveal
    host = await quiz.host_state(db, game.id, teacher)
    assert host["phase"] == "reveal" and host["correct"] == 1
    assert host["counts"][1] == 1 and host["counts"][0] == 1  # по одному на вариант
    assert host["leaderboard"][0]["name"] == "Алиса"  # лидирует ответившая верно

    pst = await quiz.play_state(db, game.id, j1["player_id"], s1)
    assert pst["phase"] == "reveal" and pst["you"]["correct"] is True and pst["you"]["rank"] == 1

    # доходим до конца: вопрос1, reveal1, вопрос2, reveal2, затем ended
    await quiz.advance(db, game.id, teacher)  # → вопрос 1
    await quiz.submit_answer(db, game.id, j1["player_id"], s1, 1, 1)
    await quiz.advance(db, game.id, teacher)  # reveal 1
    await quiz.advance(db, game.id, teacher)  # → вопрос 2
    await quiz.advance(db, game.id, teacher)  # reveal 2 (последний)
    host = await quiz.host_state(db, game.id, teacher)
    assert host["is_last"] is True
    await quiz.advance(db, game.id, teacher)  # → ended
    host = await quiz.host_state(db, game.id, teacher)
    assert host["phase"] == "ended" and host["podium"][0]["name"] == "Алиса"

    pst = await quiz.play_state(db, game.id, j1["player_id"], s1)
    assert pst["phase"] == "ended" and pst["rank"] == 1 and pst["score"] > 0


async def test_player_avatar(db):
    teacher, game = await _game(db)
    s1 = await make_student(db, 361, "С Аватаром")
    j = await quiz.join(db, game.pin, s1, "🦊")
    assert j["emoji"] == "🦊"
    # аватар виден в лобби у ведущего
    host = await quiz.host_state(db, game.id, teacher)
    assert host["joined"][0] == {"name": "С Аватаром", "emoji": "🦊"}
    # неизвестный эмодзи → подберётся случайный из набора (не пустой)
    s2 = await make_student(db, 362, "Без Выбора")
    j2 = await quiz.join(db, game.pin, s2, "не-эмодзи")
    assert j2["emoji"] in quiz.AVATARS
    # аватар доходит до подиума
    await quiz.advance(db, game.id, teacher)
    await quiz.advance(db, game.id, teacher)  # вопрос → reveal
    rev = await quiz.host_state(db, game.id, teacher)
    assert all("emoji" in p for p in rev["leaderboard"])


async def test_cannot_join_running_game(db):
    teacher, game = await _game(db)
    s1 = await make_student(db, 321, "Ранний")
    await quiz.join(db, game.pin, s1)
    await quiz.advance(db, game.id, teacher)  # игра пошла
    late = await make_student(db, 322, "Опоздавший")
    with pytest.raises(svc.ServiceError) as e:
        await quiz.join(db, game.pin, late)
    assert e.value.status == 409


async def test_join_needs_name(db):
    teacher, game = await _game(db)
    nameless = await svc.get_or_create_user(db, 331)  # без ФИО
    with pytest.raises(svc.ServiceError) as e:
        await quiz.join(db, game.pin, nameless)
    assert e.value.status == 409


async def test_only_host_controls(db):
    teacher, game = await _game(db)
    other = await make_teacher(db, 341, "Чужой Препод")
    with pytest.raises(svc.ServiceError) as e:
        await quiz.advance(db, game.id, other)
    assert e.value.status == 403


async def test_answer_rejected_outside_question_phase(db):
    teacher, game = await _game(db)
    s1 = await make_student(db, 351, "Игрок")
    j1 = await quiz.join(db, game.pin, s1)
    # в лобби ответить нельзя
    with pytest.raises(svc.ServiceError) as e:
        await quiz.submit_answer(db, game.id, j1["player_id"], s1, 0, 1)
    assert e.value.status == 409
