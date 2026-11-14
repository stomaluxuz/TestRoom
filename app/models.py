"""Таблицы базы данных."""
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    """Текущее время в UTC без часового пояса (так проще хранить в любой БД)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram ID
    username: Mapped[str | None] = mapped_column(String(64))
    full_name: Mapped[str | None] = mapped_column(String(200))
    # student / teacher. Студентом становятся сразу; преподавателем — после одобрения админом.
    role: Mapped[str] = mapped_column(String(16), default="student")
    teacher_pending: Mapped[bool] = mapped_column(Boolean, default=False)  # подана заявка в преподаватели
    teacher_info: Mapped[str | None] = mapped_column(Text)  # вуз (место работы)
    teacher_kafedra: Mapped[str | None] = mapped_column(Text)  # кафедра
    plan: Mapped[str] = mapped_column(String(16), default="free")
    pro_until: Mapped[datetime | None] = mapped_column(DateTime)
    # Pro+ — высший платный уровень (отдельный срок). Открывает эксклюзивные функции.
    proplus_until: Mapped[datetime | None] = mapped_column(DateTime)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    # Дневной лимит создания презентаций (по местному дню).
    pres_date: Mapped[date | None] = mapped_column(Date)
    pres_count: Mapped[int] = mapped_column(Integer, default=0)  # презентаций за сегодня (обнуляется)
    pres_total: Mapped[int] = mapped_column(Integer, default=0)  # всего презентаций (не обнуляется)
    # Баланс в сумах. Студенты платят за генерацию презентаций и тестов; преподаватели — бесплатно.
    balance: Mapped[int] = mapped_column(Integer, default=0)
    lang: Mapped[str] = mapped_column(String(2), default="ru")  # язык интерфейса бота (uz/ru/en)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    @property
    def is_teacher(self) -> bool:
        return self.role == "teacher" and not self.blocked

    @property
    def is_pro(self) -> bool:
        return self.plan == "pro" and self.pro_until is not None and self.pro_until > utcnow()

    @property
    def is_pro_plus(self) -> bool:
        """Pro+ активен. Высший уровень — открывает эксклюзивные функции и даёт безлимит."""
        return self.proplus_until is not None and self.proplus_until > utcnow()


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    tests: Mapped[list["Test"]] = relationship(back_populates="subject")


class Test(Base):
    __tablename__ = "tests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    subject: Mapped[Subject] = relationship(back_populates="tests")
    questions: Mapped[list["Question"]] = relationship(
        back_populates="test", order_by="Question.position", cascade="all, delete-orphan"
    )


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("tests.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON)  # список строк
    correct: Mapped[int] = mapped_column(Integer)  # индекс правильного варианта
    active: Mapped[bool] = mapped_column(Boolean, default=True)  # удалённые скрываем, а не стираем

    test: Mapped[Test] = relationship(back_populates="questions")


class TestSession(Base):
    """Один запуск теста для группы с кодом и таймером."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("tests.id"), index=True)
    teacher_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    group_name: Mapped[str] = mapped_column(String(100))
    code: Mapped[str] = mapped_column(String(6), index=True)
    duration_min: Mapped[int] = mapped_column(Integer)
    question_count: Mapped[int] = mapped_column(Integer)
    max_leaves: Mapped[int] = mapped_column(Integer, default=3)  # 0 — без ограничения
    max_students: Mapped[int] = mapped_column(Integer, default=0)  # 0 — без ограничения
    show_answers: Mapped[bool] = mapped_column(Boolean, default=False)
    # Защита от списывания «по очереди»: код действует join_window_min минут после старта.
    # После этого войти по коду нельзя («время вышло»). 0 — приём открыт весь тест.
    join_window_min: Mapped[int] = mapped_column(Integer, default=3)
    solo: Mapped[bool] = mapped_column(Boolean, default=False)  # тренировка студента «только для себя»
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    finished: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    notified: Mapped[bool] = mapped_column(Boolean, default=False)

    test: Mapped[Test] = relationship()
    attempts: Mapped[list["Attempt"]] = relationship(back_populates="session")

    __table_args__ = (Index("ix_sessions_code_finished", "code", "finished"),)


class Attempt(Base):
    """Прохождение теста одним студентом в рамках запуска."""

    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    # done / time / leaves / kicked / teacher
    finish_reason: Mapped[str | None] = mapped_column(String(16))
    question_order: Mapped[list] = mapped_column(JSON)  # [question_id, ...]
    option_orders: Mapped[dict] = mapped_column(JSON)  # {question_id: [исходный индекс, ...]}
    current_index: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    leaves: Mapped[int] = mapped_column(Integer, default=0)
    leave_seconds: Mapped[int] = mapped_column(Integer, default=0)

    session: Mapped[TestSession] = relationship(back_populates="attempts")
    answers: Mapped[list["Answer"]] = relationship(back_populates="attempt")

    __table_args__ = (UniqueConstraint("session_id", "user_id", name="uq_attempt_user"),)

    @property
    def total(self) -> int:
        return len(self.question_order)

    @property
    def is_finished(self) -> bool:
        return self.finished_at is not None


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    chosen: Mapped[int] = mapped_column(Integer)  # исходный индекс варианта
    is_correct: Mapped[bool] = mapped_column(Boolean)
    answered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    attempt: Mapped[Attempt] = relationship(back_populates="answers")

    __table_args__ = (UniqueConstraint("attempt_id", "question_id", name="uq_answer"),)


class AdminLog(Base):
    """Журнал действий админа в чужих кабинетах и с аккаунтами."""

    __tablename__ = "admin_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[int] = mapped_column(BigInteger, index=True)
    target_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class PresentationEvent(Base):
    """Факт создания презентации — одна строка на каждую успешную генерацию.
    Нужен для дневной статистики в админке (счётчик User.pres_total даты не хранит)."""

    __tablename__ = "presentation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class LibrarySubject(Base):
    """Предмет (раздел) электронной библиотеки. Фиксированный список, правит админ."""

    __tablename__ = "library_subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LibraryDoc(Base):
    """Документ в библиотеке. Загружает преподаватель, одобряет админ, читают студенты.
    text — извлечённый текст (для поиска и будущей генерации ИИ на его основе)."""

    __tablename__ = "library_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("library_subjects.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    filename: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str | None] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer, default=0)
    path: Mapped[str] = mapped_column(String(500))  # путь к файлу на диске
    text: Mapped[str | None] = mapped_column(Text)  # извлечённый текст
    book_title: Mapped[str | None] = mapped_column(Text)  # настоящее название книги (с обложки/титула, ИИ)
    has_cover: Mapped[bool] = mapped_column(Boolean, default=False)  # есть обложка-картинка (1-я страница)
    uploaded_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending/approved/rejected
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    approved_by: Mapped[int | None] = mapped_column(BigInteger)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Статус извлечения иллюстраций из PDF (фича LIBRARY_FIGURES): None — не требуется/не трогали,
    # pending — ждёт обработки (фон или ночь), done — обработано, error — обработка упала.
    figures_status: Mapped[str | None] = mapped_column(String(16), index=True)
    # OCR сканов: None — не скан / не требует; pending — ждёт распознавания; done/error — итог.
    ocr_status: Mapped[str | None] = mapped_column(String(16), index=True)


class LibraryChunk(Base):
    """Кусок текста одобренного материала библиотеки + его эмбеддинг (для RAG-генерации).

    vector — нормализованный вектор float32, упакованный в bytes (косинус = скалярное произведение)."""

    __tablename__ = "library_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("library_docs.id"), index=True)
    subject_id: Mapped[int] = mapped_column(Integer, index=True)  # денормализовано для фильтра
    idx: Mapped[int] = mapped_column(Integer, default=0)  # порядковый номер куска в документе
    text: Mapped[str] = mapped_column(Text)
    dim: Mapped[int] = mapped_column(Integer, default=0)
    vector: Mapped[bytes] = mapped_column(LargeBinary)  # float32[dim], нормализован
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LibraryFigure(Base):
    """Иллюстрация, вырезанная из PDF учебника (для подбора фото на слайды).
    caption — подпись зрением, vector — эмбеддинг подписи (поиск фигуры по теме слайда)."""

    __tablename__ = "library_figures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("library_docs.id"), index=True)
    subject_id: Mapped[int] = mapped_column(Integer, index=True)
    page: Mapped[int] = mapped_column(Integer, default=0)
    path: Mapped[str] = mapped_column(String(500))  # файл фигуры на диске
    w: Mapped[int] = mapped_column(Integer, default=0)
    h: Mapped[int] = mapped_column(Integer, default=0)
    caption: Mapped[str] = mapped_column(Text, default="")
    dim: Mapped[int] = mapped_column(Integer, default=0)
    vector: Mapped[bytes | None] = mapped_column(LargeBinary)  # эмбеддинг подписи (нормализован)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LibraryProgress(Base):
    """На какой странице читатель остановился в документе (запоминаем для каждого)."""

    __tablename__ = "library_progress"
    __table_args__ = (UniqueConstraint("user_id", "doc_id", name="uq_progress_user_doc"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("library_docs.id"), index=True)
    page: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AppSetting(Base):
    """Настройки, которые админ меняет на лету (цены, номер карты и т.п.) — ключ/значение."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class TopUp(Base):
    """Заявка студента на пополнение баланса (перевод на карту, подтверждает админ вручную)."""

    __tablename__ = "topups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)  # сумма в сумах
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending/approved/rejected
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_by: Mapped[int | None] = mapped_column(BigInteger)


# ------------------------------------------------ живой куиз (Kahoot-режим)

class QuizGame(Base):
    """Синхронная игра-куиз: учитель открывает вопросы по одному, все отвечают
    одновременно, очки — за правильность и скорость. Темпом управляет учитель."""

    __tablename__ = "quiz_games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    host_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    pin: Mapped[str] = mapped_column(String(6), index=True)  # код входа
    topic: Mapped[str] = mapped_column(String(300))
    lang: Mapped[str] = mapped_column(String(2), default="ru")
    seconds: Mapped[int] = mapped_column(Integer, default=20)  # время на вопрос
    # [{"q": str, "options": [str, ...], "correct": int}, ...]
    questions: Mapped[list] = mapped_column(JSON)
    phase: Mapped[str] = mapped_column(String(12), default="lobby")  # lobby|question|reveal|ended
    current_index: Mapped[int] = mapped_column(Integer, default=-1)  # -1 — лобби
    question_started_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (Index("ix_quiz_games_pin_phase", "pin", "phase"),)


class QuizPlayer(Base):
    """Участник живого куиза."""

    __tablename__ = "quiz_players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("quiz_games.id"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    emoji: Mapped[str] = mapped_column(String(8), default="")  # эмодзи-аватар (как в Kahoot)
    score: Mapped[int] = mapped_column(Integer, default=0)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("game_id", "user_id", name="uq_quiz_player"),)


class QuizAnswer(Base):
    """Ответ участника на один вопрос куиза (для подсчёта и статистики по вариантам)."""

    __tablename__ = "quiz_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("quiz_games.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("quiz_players.id"), index=True)
    q_index: Mapped[int] = mapped_column(Integer)
    chosen: Mapped[int] = mapped_column(Integer)
    is_correct: Mapped[bool] = mapped_column(Boolean)
    points: Mapped[int] = mapped_column(Integer, default=0)
    ms: Mapped[int] = mapped_column(Integer, default=0)  # время ответа, мс
    answered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("player_id", "q_index", name="uq_quiz_answer"),)
