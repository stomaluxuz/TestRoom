/* TestRoom Mini App — интерфейс преподавателя и студента. */
"use strict";

const tg = window.Telegram ? window.Telegram.WebApp : null;
const $app = document.getElementById("app");
const devUser = new URLSearchParams(location.search).get("dev");

let ME = null;
let navStack = [];
let timers = [];          // интервалы текущего экрана
let attemptCtx = null;    // активное прохождение теста (для отслеживания сворачивания)
let ACT_AS = null;        // админ работает в кабинете этого преподавателя
try { ACT_AS = sessionStorage.getItem("actAs"); } catch (e) {}

/* ---------------------------------------------------------------- утилиты */

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), 2800);
}
function haptic(type) { try { tg && tg.HapticFeedback.notificationOccurred(type); } catch (e) {} }
// Модальное окно (современное, скруглённое, выезжает снизу). actions: [{label, primary, onClick}].
function showModal({ icon = "", title = "", text = "", actions = [] }) {
  closeModal();
  const wrap = document.createElement("div");
  wrap.className = "modal-bg";
  wrap.id = "modal-bg";
  wrap.innerHTML = `
    <div class="modal-card" role="dialog" aria-modal="true">
      ${icon ? `<div class="modal-ic">${icon}</div>` : ""}
      ${title ? `<div class="modal-ttl">${title}</div>` : ""}
      ${text ? `<div class="modal-txt">${text}</div>` : ""}
      <div class="modal-acts">
        ${actions.map((a, i) => `<button class="btn ${a.primary ? "" : "secondary"}" data-ai="${i}">${a.label}</button>`).join("")}
      </div>
    </div>`;
  document.body.appendChild(wrap);
  requestAnimationFrame(() => wrap.classList.add("on"));
  wrap.addEventListener("click", e => { if (e.target === wrap) closeModal(); });
  actions.forEach((a, i) => {
    const btn = wrap.querySelector(`[data-ai="${i}"]`);
    if (btn) btn.addEventListener("click", () => { if (a.close !== false) closeModal(); if (a.onClick) a.onClick(); });
  });
}
function closeModal() {
  const el = document.getElementById("modal-bg");
  if (el) { el.classList.remove("on"); setTimeout(() => el.remove(), 180); }
}
function fmtTime(sec) {
  sec = Math.max(0, Math.floor(sec));
  const m = Math.floor(sec / 60), s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}
function fmtDate(iso) {
  const d = new Date(iso + "Z");
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" }) + " " +
         d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}
function fmtDay(iso) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", weekday: "short" });
}
function clearTimers() { timers.forEach(clearInterval); timers = []; }
function fmtSum(n) { return String(n | 0).replace(/\B(?=(\d{3})+(?!\d))/g, " "); }

/* ---------------------------------------------------------------- языки (i18n) */
let LANG = "ru";
try { LANG = localStorage.getItem("lang") || "ru"; } catch (e) {}
if (!["ru", "uz", "en"].includes(LANG)) LANG = "ru";

const T = {
  ru: {
    open_via_bot: "Откройте приложение через Telegram-бота.", retry: "Повторить",
    welcome: "Добро пожаловать 👋",
    name_hint: "Напишите ваши <b>Фамилию и Имя</b> полностью. Их увидит преподаватель в результатах.",
    name_ph: "Тохиржонова Марьям", save: "Сохранить",
    enter_code: "Введите код, который сказал преподаватель", start_test: "Начать тест",
    my_tests_training: "Мои тесты (тренировка)", upload_my_test: "Загрузить свой тест",
    pending_teacher: "⏳ Заявка преподавателя на рассмотрении.", become_teacher: "Стать преподавателем",
    my_results: "Мои результаты", loading: "Загрузка…", profile: "Профиль",
    no_history: "Пока нет пройденных тестов.", running: "идёт",
    code_6: "Код состоит из 6 цифр", no_conn: "Нет связи с сервером. Проверьте интернет.",
    edit_name: "Изменить ФИО", fio: "ФИО", vuz: "Вуз", kafedra: "Кафедра",
    edit_work: "Изменить вуз / кафедру", back_home: "На главную",
    study_group: "Группа", edit_student: "Изменить вуз / группу", my_vuz_group: "Вуз и группа",
    group_number: "Номер группы", group_ph: "Например: 101",
    rating_title: "Рейтинг", rating_visible: "Показывать меня в рейтинге",
    rating_hint: "Когда включено — другие видят ваше имя и место. Выключите, чтобы остаться анонимно: своё место видите только вы, баллы считаются всегда.",
    choose_vuz_student: "Выберите вуз и укажите номер группы для рейтинга.", save_vuz_group: "Сохранить",
    vuz_not_chosen: "Вуз не выбран", pick_vuz_list: "Выберите вуз из списка.",
    studrating: "Рейтинг", studrating_sub: "Общий и по группам", rating_all: "Общий",
    how_study: "Рейтинг", no_rating_groups: "Пока нет студентов с заполненной группой в вашем вузе.",
    teacher_need_vuz: "Укажите ваш вуз в профиле — тогда увидите рейтинг студентов вашего вуза.",
    rating_open: "Рейтинг", rating_sub: "Твоё место среди своих",
    rating_group: "Моя группа", rating_uni: "Мой вуз",
    rating_pts: "очк.", rating_tests_n: "тестов", anon: "Аноним",
    rating_empty: "Пока пусто — пройдите тесты, и здесь появятся баллы.",
    rating_need_group: "Укажите вуз и группу в профиле — тогда увидите рейтинг своей группы.",
    rating_need_uni: "Укажите вуз в профиле, чтобы видеть рейтинг вуза.",
    rating_your_place: "Твоё место", rating_fill: "Заполнить профиль",
    rating_off_title: "Вы скрыты в рейтинге",
    rating_off_text: "Сейчас вас не видно в таблице — вы участвуете анонимно. Хотите, чтобы одногруппники видели ваше имя и место? Включите показ в профиле.",
    rating_enable_btn: "Включить в профиле", later_btn: "Позже",
    support: "🆘 Поддержка", support_hint: "Опишите проблему или вопрос — мы ответим в чате бота.",
    support_ph: "Ваше сообщение…", support_send: "Отправить", support_sent: "Отправлено ✅ Мы ответим в боте.",
    support_empty: "Напишите сообщение.",
    create_test_title: "Создать тест", t_by_ai: "С помощью ИИ", t_by_ai_sub: "ИИ напишет вопросы",
    t_by_manual: "Вручную", t_by_manual_sub: "Добавлять самому", t_by_file: "Загрузить файл", t_by_file_sub: "docx / xlsx / txt",
    gen_test_topic: "Тема теста", gen_count: "Сколько вопросов", gen_difficulty: "Сложность",
    diff_easy: "Лёгкий", diff_medium: "Средний", diff_hard: "Сложный", gen_btn: "🤖 Сгенерировать", gen_wait: "ИИ пишет вопросы…",
    create_btn2: "Создать и наполнить",
    tab_home: "Главная", tab_games: "Игры", tab_library: "Библиотека", tab_profile: "Профиль",
    greet_morning: "Доброе утро", greet_day: "Добрый день", greet_evening: "Добрый вечер", greet_night: "Доброй ночи",
    streak_days: "дн.", st_solved: "решено", st_avg: "средний", st_mistakes: "ошибок",
    quick_title: "Создавай и учись", results_title: "Мои результаты",
    sub_history: "История", sub_apply: "Отправить заявку", sub_open_tests: "Открытые тесты", sub_upload: "Свой файл",
    mistakes_title: "Мои ошибки", sub_mistakes: "Разбор", your_answer: "Твой ответ", correct_answer: "Правильно",
    no_mistakes: "Ошибок нет — отлично! 🎉",
    courses_title: "Учебный путь", sub_courses: "Теория + тесты", theory_read: "✓ Прочитано", mark_read: "Отметить прочитанным",
    take_test: "Пройти тест", no_courses: "Пока нет курсов.", course_building: "Курс ещё собирается…",
    sources_from: "По материалам", topic_test_done: "Результат", next_q: "Дальше", finish_test: "Завершить",
    teacher: "Преподаватель", plan_free: "Бесплатный тариф", plan_pro: "Pro до",
    test_running: "Идёт тест", code: "код", time_left: "осталось",
    my_tests: "Мои тесты", upload_test: "Загрузить тест", history: "История запусков",
    take_by_code: "Пройти тест по коду", admin_panel: "Админ-панель", become_student: "Стать студентом",
    ai_assistant: "ИИ-помощник", ai_hint: "Спросите или попросите создать презентацию/тест/статью — пришлю файл в бот.",
    ai_start: "Напишите свой вопрос — например «объясни, что такое пульпит».", ai_ph: "Ваш вопрос…",
    ai_proplus_only: "💎 ИИ-помощник доступен только с подпиской Pro+.", ai_src: "Источники",
    upload_via_bot: "Тест можно загрузить и через бота: просто отправьте ему файл.",
    question: "Вопрос", of: "из", answer: "Ответить", correct_excl: "✓ Верно!", wrong_excl: "✗ Неверно",
    show_result: "Показать результат", next: "Дальше →",
    you_left: "Покидали тест:", teacher_sees: "преподаватель это видит.",
    rules: "Правила:", rules_text: "не сворачивайте приложение и не делите экран. Выход из теста и отвлечение дольше 2 секунд фиксируются и видны преподавателю.",
    guard_title: "Вернитесь к тесту", guard_text: "Разверните приложение на весь экран и не делите экран. Пока вы отвлечены, вопрос скрыт, время идёт, а нарушение видно преподавателю.",
    your_answers: "Ваши ответы", your_answer: "Ваш ответ", correct_ans: "Правильный",
    answers_locked: "🔒 Разбор ответов будет доступен после того, как преподаватель завершит тест для всех.",
    r_done: "Вы ответили на все вопросы.", r_time: "Время теста вышло.",
    r_leaves: "Тест закрыт: вы слишком часто покидали приложение.",
    r_kicked: "Преподаватель удалил вас из теста.", r_teacher: "Преподаватель завершил тест.",
    r_default: "Тест завершён.", time_word: "время",
    place_work: "Место работы", place_work_vuz: "Место работы (вуз)",
    kafedra_ph: "Напр.: Терапевтическая стоматология", send_request: "Отправить заявку",
    choose_other_vuz: "← Выбрать другой вуз", enter_kafedra: "Укажите кафедру",
    saved: "Сохранено", you_are_teacher: "Вы преподаватель", request_sent: "Заявка отправлена",
    find_then_kaf: "Найдите и выберите ваш вуз, затем укажите кафедру.",
    choose_vuz_kaf: "Выберите вуз и укажите кафедру. Заявку рассмотрит администратор.",
    search_vuz: "🔎 Поиск вуза по названию", other_vuz: "Другой вуз (ввести вручную)…",
    vuz_name: "Название вуза", vuz_name_ph: "Название вашего вуза", next_arrow: "Далее →",
    vuz_not_found: "Вуз не найден — добавьте его вручную ниже.", enter_vuz: "Введите название вуза",
    confirm_student: "Вернуться к роли студента?", now_student: "Теперь вы студент",
    archive_title: "Архив", choose_subject_hint: "Выберите предмет — внутри его тесты.",
    tab_active: "Активные", tab_archive: "Архив", archive_empty: "В архиве пусто.",
    no_subjects: "Предметов пока нет. Загрузите первый тест.", count_tests: "тест.",
    subject_word: "Предмет", subject_not_found: "Предмет не найден", questions_word: "вопросов",
    open_arrow: "Открыть ›", active_l: "активных", arch_l: "в архиве",
    arch_of_subject: "Архив предмета", subj_archive_empty: "В архиве этого предмета пусто.",
    no_tests_subject: "В этом предмете пока нет тестов.", upload_to_subject: "Загрузить тест в предмет",
    del_subject: "Удалить предмет", subject_deleted: "Предмет удалён",
    confirm_del_subject: "Удалить предмет «{n}» со всеми тестами и результатами? Это необратимо.",
    rename_btn: "Переименовать", in_archive_suffix: "в архиве", min_word: "минут",
    launch_test: "Запуск теста", group: "Группа", time_on_test: "Время на тест",
    qc_label: "Сколько вопросов дать каждому (случайно из {n})",
    ml_label: "Закрыть тест студенту после сворачиваний (0 — не закрывать)",
    ms_label: "Максимум студентов (0 — без ограничения)", jw_label: "Код действует (успеть войти)",
    jw_opt_all: "весь тест (без ограничения)",
    jw_hint: "⏰ После этого войти по коду нельзя — защита от «заходим по очереди».",
    activate_test: "Активировать тест", training_mode: "Тренировка (режим обучения)",
    training_hint_t: "Прорешать свой тест: после каждого вопроса сразу покажем правильный ответ.",
    training_hint_s: "После каждого вопроса сразу покажем правильный ответ.",
    sqc_label: "Сколько вопросов (случайно из {n})", solve: "Решать",
    questions_edit: "Вопросы и правка", download_test: "Скачать тест файлом (себе в чат)",
    file_sent_chat: "Файл теста отправлен в чат с ботом", from_archive: "Вернуть из архива",
    to_archive: "Отправить в архив", delete_test: "Удалить тест", save_title: "Сохранить название",
    cancel: "Отмена", enter_title: "Введите название", renamed: "Переименовано",
    confirm_del_test: "Удалить тест «{n}»? Вопросы и все результаты будут стёрты без восстановления.",
    test_deleted: "Тест удалён", enter_group: "Укажите группу",
    test_restored: "Тест возвращён", test_archived: "Тест в архиве",
    subject_label: "Предмет", new_subject_opt: "➕ Новый предмет…", subject_name_label: "Название предмета",
    subject_name_ph: "Анатомия", test_name_label: "Название теста", test_name_ph: "Кости скелета",
    file_label: "Файл (.docx, .xlsx или .txt)", upload_btn: "Загрузить",
    upload_format_hint: "Формат: варианты A) B) C)…, правильный отметьте звёздочкой «*» перед буквой. Шаблоны пришлёт бот по команде /template.",
    choose_file: "Выберите файл", enter_test_name: "Введите название теста",
    saved_questions: "Сохранено вопросов: {n}", found_questions: "Найдено вопросов: {n}",
    without_errors: "Без ошибок", with_errors: "С ошибками", save_valid_btn: "Сохранить {n} правильных",
    fix_and_retry: "Или исправьте файл и загрузите снова.",
    join_open_pre: "⏰ Вход по коду открыт ещё", join_open_post: "— успейте завести всех студентов",
    join_closed: "🔒 Приём закрыт — опоздавшие войти больше не смогут", group_word: "группа",
    say_code: "Скажите код студентам", left_label: "Осталось", joined_finished: "Вошли / закончили",
    minimized: "свернул", remove_from_test: "Удалить из теста",
    nobody_joined: "Пока никто не вошёл. Студенты вводят код в боте.", finish_early: "Завершить тест досрочно",
    confirm_remove: "Удалить {n} из теста?", confirm_finish: "Завершить тест для всех сейчас?",
    results_word: "Итоги", avg_result: "Средний результат", wrote: "Писали",
    still_running_online: "Тест ещё идёт — смотреть онлайн", ranking: "Рейтинг",
    nobody_took: "Никто не проходил тест.", hard_questions: "Сложные вопросы",
    answer_label: "Ответ", pct_correct: "% верно", get_excel: "📥 Получить Excel в чат",
    history_short: "История", all_groups: "Все группы", people: "чел.", no_launches: "Запусков пока не было.",
    edit_word: "Изменить", add_question: "➕ Добавить вопрос", options_word: "вариантов",
    new_question: "Новый вопрос", edit_question: "Изменить вопрос", question_text: "Текст вопроса",
    choose_correct: "Варианты (отметьте правильный)", option_word: "Вариант", add_option: "+ вариант",
    delete_question: "Удалить вопрос", confirm_del_question: "Удалить вопрос?", deleted: "Удалено",
  },
  uz: {
    open_via_bot: "Ilovani Telegram-bot orqali oching.", retry: "Qayta urinish",
    welcome: "Xush kelibsiz 👋",
    name_hint: "<b>Familiya va Ismingizni</b> to'liq yozing. Ularni o'qituvchi natijalarda ko'radi.",
    name_ph: "Tohirjonova Maryam", save: "Saqlash",
    enter_code: "O'qituvchi aytgan kodni kiriting", start_test: "Testni boshlash",
    my_tests_training: "Mening testlarim (mashq)", upload_my_test: "O'z testimni yuklash",
    pending_teacher: "⏳ O'qituvchilik arizasi ko'rib chiqilmoqda.", become_teacher: "O'qituvchi bo'lish",
    my_results: "Mening natijalarim", loading: "Yuklanmoqda…", profile: "Profil",
    no_history: "Hali yechilgan testlar yo'q.", running: "ketmoqda",
    code_6: "Kod 6 raqamdan iborat", no_conn: "Server bilan aloqa yo'q. Internetni tekshiring.",
    edit_name: "F.I.Sh. o'zgartirish", fio: "F.I.Sh.", vuz: "OTM", kafedra: "Kafedra",
    edit_work: "OTM / kafedrani o'zgartirish", back_home: "Bosh sahifaga",
    study_group: "Guruh", edit_student: "OTM / guruhni o'zgartirish", my_vuz_group: "OTM va guruh",
    group_number: "Guruh raqami", group_ph: "Masalan: 101",
    rating_title: "Reyting", rating_visible: "Reytingda ko'rsatilsin",
    rating_hint: "Yoqilganda — boshqalar ismingiz va o'rningizni ko'radi. O'chirsangiz anonim qolasiz: o'rningizni faqat o'zingiz ko'rasiz, ballar baribir hisoblanadi.",
    choose_vuz_student: "Reyting uchun OTMni tanlang va guruh raqamini kiriting.", save_vuz_group: "Saqlash",
    vuz_not_chosen: "OTM tanlanmagan", pick_vuz_list: "OTMni ro'yxatdan tanlang.",
    studrating: "Reyting", studrating_sub: "Umumiy va guruhlar bo'yicha", rating_all: "Umumiy",
    how_study: "Reyting", no_rating_groups: "Hozircha vuzingizda guruhi to'ldirilgan talabalar yo'q.",
    teacher_need_vuz: "Profilda vuzingizni ko'rsating — shunda vuzingiz talabalari reytingini ko'rasiz.",
    rating_open: "Reyting", rating_sub: "O'zingiznikilar orasida o'rningiz",
    rating_group: "Mening guruhim", rating_uni: "Mening OTM",
    rating_pts: "ball", rating_tests_n: "test", anon: "Anonim",
    rating_empty: "Hozircha bo'sh — testlardan o'ting, ballar shu yerda paydo bo'ladi.",
    rating_need_group: "Profilda OTM va guruhni ko'rsating — shunda guruh reytingini ko'rasiz.",
    rating_need_uni: "OTM reytingini ko'rish uchun profilda OTMni ko'rsating.",
    rating_your_place: "Sizning o'rningiz", rating_fill: "Profilni to'ldirish",
    rating_off_title: "Siz reytingda yashirinsiz",
    rating_off_text: "Hozir siz jadvalda ko'rinmaysiz — anonim qatnashyapsiz. Guruhdoshlaringiz ismingiz va o'rningizni ko'rishini xohlaysizmi? Profilda ko'rsatishni yoqing.",
    rating_enable_btn: "Profilda yoqish", later_btn: "Keyinroq",
    support: "🆘 Yordam", support_hint: "Muammo yoki savolni yozing — bot chatida javob beramiz.",
    support_ph: "Xabaringiz…", support_send: "Yuborish", support_sent: "Yuborildi ✅ Botda javob beramiz.",
    support_empty: "Xabar yozing.",
    create_test_title: "Test yaratish", t_by_ai: "AI yordamida", t_by_ai_sub: "AI savollar yozadi",
    t_by_manual: "Qo'lda", t_by_manual_sub: "O'zingiz qo'shasiz", t_by_file: "Fayl yuklash", t_by_file_sub: "docx / xlsx / txt",
    gen_test_topic: "Test mavzusi", gen_count: "Savollar soni", gen_difficulty: "Qiyinlik",
    diff_easy: "Oson", diff_medium: "O'rta", diff_hard: "Qiyin", gen_btn: "🤖 Yaratish", gen_wait: "AI savollarni yozmoqda…",
    create_btn2: "Yaratish va to'ldirish",
    tab_home: "Asosiy", tab_games: "O'yinlar", tab_library: "Kutubxona", tab_profile: "Profil",
    greet_morning: "Xayrli tong", greet_day: "Xayrli kun", greet_evening: "Xayrli kech", greet_night: "Xayrli tun",
    streak_days: "kun", st_solved: "yechildi", st_avg: "o'rtacha", st_mistakes: "xato",
    quick_title: "Yarating va o'rganing", results_title: "Mening natijalarim",
    sub_history: "Tarix", sub_apply: "Ariza yuborish", sub_open_tests: "Ochiq testlar", sub_upload: "O'z fayling",
    mistakes_title: "Mening xatolarim", sub_mistakes: "Tahlil", your_answer: "Sizning javobingiz", correct_answer: "To'g'ri",
    no_mistakes: "Xatolar yo'q — zo'r! 🎉",
    courses_title: "O'quv yo'li", sub_courses: "Nazariya + testlar", theory_read: "✓ O'qildi", mark_read: "O'qildi deb belgilash",
    take_test: "Testni yechish", no_courses: "Hozircha kurslar yo'q.", course_building: "Kurs hali yig'ilmoqda…",
    sources_from: "Manbalar", topic_test_done: "Natija", next_q: "Keyingi", finish_test: "Yakunlash",
    teacher: "O'qituvchi", plan_free: "Bepul tarif", plan_pro: "Pro:",
    test_running: "Test ketmoqda", code: "kod", time_left: "qoldi",
    my_tests: "Mening testlarim", upload_test: "Test yuklash", history: "Ishga tushirishlar tarixi",
    take_by_code: "Kod bo'yicha test yechish", admin_panel: "Admin-panel", become_student: "Student bo'lish",
    ai_assistant: "AI-yordamchi", ai_hint: "Savol bering yoki taqdimot/test/maqola yaratishni so'rang — faylni botga yuboraman.",
    ai_start: "Savolingizni yozing — masalan «pulpit nima?».", ai_ph: "Savolingiz…",
    ai_proplus_only: "💎 AI-yordamchi faqat Pro+ obunasida mavjud.", ai_src: "Manbalar",
    upload_via_bot: "Testni bot orqali ham yuklash mumkin: shunchaki faylni yuboring.",
    question: "Savol", of: "dan", answer: "Javob berish", correct_excl: "✓ To'g'ri!", wrong_excl: "✗ Noto'g'ri",
    show_result: "Natijani ko'rsatish", next: "Keyingi →",
    you_left: "Testdan chiqishlar:", teacher_sees: "o'qituvchi buni ko'radi.",
    rules: "Qoidalar:", rules_text: "ilovani yopmang va ekranni bo'lmang. Testdan chiqish va 2 soniyadan ortiq chalg'ish qayd etiladi va o'qituvchiga ko'rinadi.",
    guard_title: "Testga qayting", guard_text: "Ilovani to'liq ekranga yoying va ekranni bo'lmang. Chalg'iganingizda savol yashiriladi, vaqt ketadi, buzilish o'qituvchiga ko'rinadi.",
    your_answers: "Sizning javoblaringiz", your_answer: "Sizning javobingiz", correct_ans: "To'g'ri",
    answers_locked: "🔒 Javoblar tahlili o'qituvchi testni hamma uchun yakunlagach ko'rinadi.",
    r_done: "Siz barcha savollarga javob berdingiz.", r_time: "Test vaqti tugadi.",
    r_leaves: "Test yopildi: siz ilovadan juda ko'p chiqdingiz.",
    r_kicked: "O'qituvchi sizni testdan chiqarib yubordi.", r_teacher: "O'qituvchi testni yakunladi.",
    r_default: "Test yakunlandi.", time_word: "vaqt",
    place_work: "Ish joyi", place_work_vuz: "Ish joyi (OTM)",
    kafedra_ph: "Masalan: Terapevtik stomatologiya", send_request: "Ariza yuborish",
    choose_other_vuz: "← Boshqa OTM tanlash", enter_kafedra: "Kafedrani kiriting",
    saved: "Saqlandi", you_are_teacher: "Siz o'qituvchisiz", request_sent: "Ariza yuborildi",
    find_then_kaf: "OTMingizni toping va tanlang, so'ng kafedrani kiriting.",
    choose_vuz_kaf: "OTM tanlang va kafedrani kiriting. Arizani administrator ko'rib chiqadi.",
    search_vuz: "🔎 OTM nomi bo'yicha qidirish", other_vuz: "Boshqa OTM (qo'lda kiritish)…",
    vuz_name: "OTM nomi", vuz_name_ph: "OTMingiz nomi", next_arrow: "Keyingi →",
    vuz_not_found: "OTM topilmadi — uni quyida qo'lda qo'shing.", enter_vuz: "OTM nomini kiriting",
    confirm_student: "Student roliga qaytilsinmi?", now_student: "Endi siz studentsiz",
    archive_title: "Arxiv", choose_subject_hint: "Fanni tanlang — ichida uning testlari.",
    tab_active: "Faol", tab_archive: "Arxiv", archive_empty: "Arxiv bo'sh.",
    no_subjects: "Hali fanlar yo'q. Birinchi testni yuklang.", count_tests: "ta test",
    subject_word: "Fan", subject_not_found: "Fan topilmadi", questions_word: "ta savol",
    open_arrow: "Ochish ›", active_l: "faol", arch_l: "arxivda",
    arch_of_subject: "Fan arxivi", subj_archive_empty: "Bu fan arxivida bo'sh.",
    no_tests_subject: "Bu fanda hali testlar yo'q.", upload_to_subject: "Fanga test yuklash",
    del_subject: "Fanni o'chirish", subject_deleted: "Fan o'chirildi",
    confirm_del_subject: "«{n}» fani barcha testlari va natijalari bilan o'chirilsinmi? Qaytarib bo'lmaydi.",
    rename_btn: "Qayta nomlash", in_archive_suffix: "arxivda", min_word: "daqiqa",
    launch_test: "Testni ishga tushirish", group: "Guruh", time_on_test: "Testga vaqt",
    qc_label: "Har kimga nechta savol berilsin ({n} tadan tasodifiy)",
    ml_label: "Ilovadan chiqishdan keyin testni yopish (0 — yopilmasin)",
    ms_label: "Maksimal studentlar (0 — cheklovsiz)", jw_label: "Kod amal qiladi (ulgurish kerak)",
    jw_opt_all: "butun test (cheklovsiz)",
    jw_hint: "⏰ Shundan keyin kod bo'yicha kirib bo'lmaydi — «navbat bilan kirish»dan himoya.",
    activate_test: "Testni faollashtirish", training_mode: "Mashq (o'rganish rejimi)",
    training_hint_t: "O'z testingizni yechish: har savoldan keyin to'g'ri javob ko'rsatiladi.",
    training_hint_s: "Har savoldan keyin to'g'ri javob ko'rsatiladi.",
    sqc_label: "Nechta savol ({n} tadan tasodifiy)", solve: "Yechish",
    questions_edit: "Savollar va tahrir", download_test: "Testni fayl qilib olish (o'zingizga)",
    file_sent_chat: "Test fayli botga yuborildi", from_archive: "Arxivdan qaytarish",
    to_archive: "Arxivga yuborish", delete_test: "Testni o'chirish", save_title: "Nomni saqlash",
    cancel: "Bekor qilish", enter_title: "Nomni kiriting", renamed: "Qayta nomlandi",
    confirm_del_test: "«{n}» testi o'chirilsinmi? Savollar va natijalar qaytarib bo'lmas tarzda o'chadi.",
    test_deleted: "Test o'chirildi", enter_group: "Guruhni kiriting",
    test_restored: "Test qaytarildi", test_archived: "Test arxivda",
    subject_label: "Fan", new_subject_opt: "➕ Yangi fan…", subject_name_label: "Fan nomi",
    subject_name_ph: "Anatomiya", test_name_label: "Test nomi", test_name_ph: "Skelet suyaklari",
    file_label: "Fayl (.docx, .xlsx yoki .txt)", upload_btn: "Yuklash",
    upload_format_hint: "Format: variantlar A) B) C)…, to'g'risini harf oldidan «*» bilan belgilang. Namunalarni bot /template buyrug'i bilan yuboradi.",
    choose_file: "Faylni tanlang", enter_test_name: "Test nomini kiriting",
    saved_questions: "Saqlangan savollar: {n}", found_questions: "Topilgan savollar: {n}",
    without_errors: "Xatosiz", with_errors: "Xatolar bilan", save_valid_btn: "{n} to'g'risini saqlash",
    fix_and_retry: "Yoki faylni tuzatib, qayta yuklang.",
    join_open_pre: "⏰ Kod bo'yicha kirish ochiq", join_open_post: "— barcha studentlarni kiritishga ulguring",
    join_closed: "🔒 Qabul yopildi — kechikkanlar kira olmaydi", group_word: "guruh",
    say_code: "Kodni studentlarga ayting", left_label: "Qoldi", joined_finished: "Kirdi / tugatdi",
    minimized: "chiqdi", remove_from_test: "Testdan chiqarish",
    nobody_joined: "Hali hech kim kirmadi. Studentlar botda kod kiritadi.", finish_early: "Testni muddatidan oldin yakunlash",
    confirm_remove: "{n} testdan chiqarilsinmi?", confirm_finish: "Test hamma uchun hozir yakunlansinmi?",
    results_word: "Natijalar", avg_result: "O'rtacha natija", wrote: "Yozdi",
    still_running_online: "Test hali ketmoqda — onlayn ko'rish", ranking: "Reyting",
    nobody_took: "Hech kim testni yechmadi.", hard_questions: "Qiyin savollar",
    answer_label: "Javob", pct_correct: "% to'g'ri", get_excel: "📥 Excelni chatga olish",
    history_short: "Tarix", all_groups: "Barcha guruhlar", people: "kishi", no_launches: "Hali ishga tushirishlar bo'lmagan.",
    edit_word: "O'zgartirish", add_question: "➕ Savol qo'shish", options_word: "ta variant",
    new_question: "Yangi savol", edit_question: "Savolni o'zgartirish", question_text: "Savol matni",
    choose_correct: "Variantlar (to'g'risini belgilang)", option_word: "Variant", add_option: "+ variant",
    delete_question: "Savolni o'chirish", confirm_del_question: "Savol o'chirilsinmi?", deleted: "O'chirildi",
  },
  en: {
    open_via_bot: "Open the app via the Telegram bot.", retry: "Retry",
    welcome: "Welcome 👋",
    name_hint: "Enter your <b>full name</b>. Your teacher will see it in the results.",
    name_ph: "Tohirjonova Maryam", save: "Save",
    enter_code: "Enter the code your teacher gave you", start_test: "Start test",
    my_tests_training: "My tests (practice)", upload_my_test: "Upload my test",
    pending_teacher: "⏳ Teacher request is under review.", become_teacher: "Become a teacher",
    my_results: "My results", loading: "Loading…", profile: "Profile",
    no_history: "No completed tests yet.", running: "in progress",
    code_6: "The code is 6 digits", no_conn: "No connection to the server. Check your internet.",
    edit_name: "Edit name", fio: "Full name", vuz: "University", kafedra: "Department",
    edit_work: "Edit university / department", back_home: "Home",
    study_group: "Group", edit_student: "Edit university / group", my_vuz_group: "University and group",
    group_number: "Group number", group_ph: "E.g. 101",
    rating_title: "Rating", rating_visible: "Show me in the rating",
    rating_hint: "When on, others see your name and rank. Turn it off to stay anonymous: only you see your rank, and points are counted either way.",
    choose_vuz_student: "Choose your university and enter your group number for the rating.", save_vuz_group: "Save",
    vuz_not_chosen: "No university chosen", pick_vuz_list: "Choose a university from the list.",
    studrating: "Rating", studrating_sub: "Overall and by group", rating_all: "Overall",
    how_study: "Rating", no_rating_groups: "No students with a group set in your university yet.",
    teacher_need_vuz: "Set your university in the profile to see your university's student rating.",
    rating_open: "Rating", rating_sub: "Your place among peers",
    rating_group: "My group", rating_uni: "My university",
    rating_pts: "pts", rating_tests_n: "tests", anon: "Anonymous",
    rating_empty: "Empty for now — take some tests and points will show up here.",
    rating_need_group: "Set your university and group in the profile to see the group rating.",
    rating_need_uni: "Set your university in the profile to see the university rating.",
    rating_your_place: "Your place", rating_fill: "Fill in profile",
    rating_off_title: "You are hidden in the rating",
    rating_off_text: "You're not shown in the table right now — you take part anonymously. Want classmates to see your name and rank? Turn on visibility in your profile.",
    rating_enable_btn: "Enable in profile", later_btn: "Later",
    support: "🆘 Support", support_hint: "Describe your problem or question — we'll reply in the bot chat.",
    support_ph: "Your message…", support_send: "Send", support_sent: "Sent ✅ We'll reply in the bot.",
    support_empty: "Write a message.",
    create_test_title: "Create test", t_by_ai: "With AI", t_by_ai_sub: "AI writes the questions",
    t_by_manual: "Manually", t_by_manual_sub: "Add them yourself", t_by_file: "Upload file", t_by_file_sub: "docx / xlsx / txt",
    gen_test_topic: "Test topic", gen_count: "How many questions", gen_difficulty: "Difficulty",
    diff_easy: "Easy", diff_medium: "Medium", diff_hard: "Hard", gen_btn: "🤖 Generate", gen_wait: "AI is writing questions…",
    create_btn2: "Create and fill",
    tab_home: "Home", tab_games: "Games", tab_library: "Library", tab_profile: "Profile",
    greet_morning: "Good morning", greet_day: "Good afternoon", greet_evening: "Good evening", greet_night: "Good night",
    streak_days: "d", st_solved: "solved", st_avg: "average", st_mistakes: "mistakes",
    quick_title: "Create & learn", results_title: "My results",
    sub_history: "History", sub_apply: "Send a request", sub_open_tests: "Open tests", sub_upload: "Your file",
    mistakes_title: "My mistakes", sub_mistakes: "Review", your_answer: "Your answer", correct_answer: "Correct",
    no_mistakes: "No mistakes — great! 🎉",
    courses_title: "Learning path", sub_courses: "Theory + tests", theory_read: "✓ Read", mark_read: "Mark as read",
    take_test: "Take the test", no_courses: "No courses yet.", course_building: "The course is still building…",
    sources_from: "Based on", topic_test_done: "Result", next_q: "Next", finish_test: "Finish",
    teacher: "Teacher", plan_free: "Free plan", plan_pro: "Pro until",
    test_running: "Test in progress", code: "code", time_left: "left",
    my_tests: "My tests", upload_test: "Upload test", history: "Launch history",
    take_by_code: "Take a test by code", admin_panel: "Admin panel", become_student: "Switch to student",
    ai_assistant: "AI assistant", ai_hint: "Ask, or request a presentation/test/article — I'll send the file to the bot.",
    ai_start: "Type your question — e.g. \"explain what pulpitis is\".", ai_ph: "Your question…",
    ai_proplus_only: "💎 AI assistant is available only with Pro+.", ai_src: "Sources",
    upload_via_bot: "You can also upload a test via the bot: just send it the file.",
    question: "Question", of: "of", answer: "Answer", correct_excl: "✓ Correct!", wrong_excl: "✗ Wrong",
    show_result: "Show result", next: "Next →",
    you_left: "Left the test:", teacher_sees: "the teacher can see this.",
    rules: "Rules:", rules_text: "do not minimize the app or split the screen. Leaving the test or looking away for more than 2 seconds is recorded and visible to the teacher.",
    guard_title: "Return to the test", guard_text: "Make the app full screen and do not split the screen. While you are away the question is hidden, time keeps running, and the violation is visible to the teacher.",
    your_answers: "Your answers", your_answer: "Your answer", correct_ans: "Correct",
    answers_locked: "🔒 The answer review will be available after the teacher finishes the test for everyone.",
    r_done: "You answered all questions.", r_time: "Test time is up.",
    r_leaves: "Test closed: you left the app too many times.",
    r_kicked: "The teacher removed you from the test.", r_teacher: "The teacher finished the test.",
    r_default: "Test finished.", time_word: "time",
    place_work: "Workplace", place_work_vuz: "Workplace (university)",
    kafedra_ph: "e.g.: Therapeutic dentistry", send_request: "Send request",
    choose_other_vuz: "← Choose another university", enter_kafedra: "Enter the department",
    saved: "Saved", you_are_teacher: "You are a teacher", request_sent: "Request sent",
    find_then_kaf: "Find and choose your university, then enter the department.",
    choose_vuz_kaf: "Choose a university and enter the department. An admin will review the request.",
    search_vuz: "🔎 Search university by name", other_vuz: "Another university (enter manually)…",
    vuz_name: "University name", vuz_name_ph: "Your university name", next_arrow: "Next →",
    vuz_not_found: "University not found — add it manually below.", enter_vuz: "Enter the university name",
    confirm_student: "Switch back to student role?", now_student: "You are now a student",
    archive_title: "Archive", choose_subject_hint: "Choose a subject — its tests are inside.",
    tab_active: "Active", tab_archive: "Archive", archive_empty: "Archive is empty.",
    no_subjects: "No subjects yet. Upload your first test.", count_tests: "tests",
    subject_word: "Subject", subject_not_found: "Subject not found", questions_word: "questions",
    open_arrow: "Open ›", active_l: "active", arch_l: "archived",
    arch_of_subject: "Subject archive", subj_archive_empty: "This subject's archive is empty.",
    no_tests_subject: "No tests in this subject yet.", upload_to_subject: "Upload test to subject",
    del_subject: "Delete subject", subject_deleted: "Subject deleted",
    confirm_del_subject: "Delete subject «{n}» with all its tests and results? This cannot be undone.",
    rename_btn: "Rename", in_archive_suffix: "archived", min_word: "min",
    launch_test: "Launch test", group: "Group", time_on_test: "Time for the test",
    qc_label: "How many questions per student (random of {n})",
    ml_label: "Close the test after the student leaves the app (0 — don't close)",
    ms_label: "Max students (0 — no limit)", jw_label: "Code is valid for (time to join)",
    jw_opt_all: "whole test (no limit)",
    jw_hint: "⏰ After that you can't join by code — protection against taking turns.",
    activate_test: "Activate test", training_mode: "Practice (learning mode)",
    training_hint_t: "Practice your own test: the correct answer is shown after each question.",
    training_hint_s: "The correct answer is shown after each question.",
    sqc_label: "How many questions (random of {n})", solve: "Start",
    questions_edit: "Questions & editing", download_test: "Download test as a file (to your chat)",
    file_sent_chat: "The test file was sent to the bot chat", from_archive: "Restore from archive",
    to_archive: "Move to archive", delete_test: "Delete test", save_title: "Save title",
    cancel: "Cancel", enter_title: "Enter a title", renamed: "Renamed",
    confirm_del_test: "Delete test «{n}»? Questions and all results will be erased permanently.",
    test_deleted: "Test deleted", enter_group: "Enter the group",
    test_restored: "Test restored", test_archived: "Test archived",
    subject_label: "Subject", new_subject_opt: "➕ New subject…", subject_name_label: "Subject name",
    subject_name_ph: "Anatomy", test_name_label: "Test name", test_name_ph: "Skeleton bones",
    file_label: "File (.docx, .xlsx or .txt)", upload_btn: "Upload",
    upload_format_hint: "Format: options A) B) C)…, mark the correct one with an asterisk «*» before the letter. The bot sends templates via /template.",
    choose_file: "Choose a file", enter_test_name: "Enter the test name",
    saved_questions: "Questions saved: {n}", found_questions: "Questions found: {n}",
    without_errors: "Without errors", with_errors: "With errors", save_valid_btn: "Save {n} valid",
    fix_and_retry: "Or fix the file and upload again.",
    join_open_pre: "⏰ Joining by code is open for", join_open_post: "— get all students in on time",
    join_closed: "🔒 Joining closed — latecomers can no longer join", group_word: "group",
    say_code: "Tell the code to the students", left_label: "Left", joined_finished: "Joined / finished",
    minimized: "left", remove_from_test: "Remove from test",
    nobody_joined: "Nobody has joined yet. Students enter the code in the bot.", finish_early: "Finish the test early",
    confirm_remove: "Remove {n} from the test?", confirm_finish: "Finish the test for everyone now?",
    results_word: "Results", avg_result: "Average score", wrote: "Took it",
    still_running_online: "Test still running — watch online", ranking: "Ranking",
    nobody_took: "Nobody took the test.", hard_questions: "Hard questions",
    answer_label: "Answer", pct_correct: "% correct", get_excel: "📥 Get Excel in chat",
    history_short: "History", all_groups: "All groups", people: "ppl", no_launches: "No launches yet.",
    edit_word: "Edit", add_question: "➕ Add question", options_word: "options",
    new_question: "New question", edit_question: "Edit question", question_text: "Question text",
    choose_correct: "Options (mark the correct one)", option_word: "Option", add_option: "+ option",
    delete_question: "Delete question", confirm_del_question: "Delete the question?", deleted: "Deleted",
  },
};
function t(key) { return (T[LANG] && T[LANG][key]) || T.ru[key] || key; }
function langBar() {
  const b = (l, flag) => `<button class="lang ${LANG === l ? "on" : ""}" data-l="${l}">${flag}</button>`;
  return `<div class="langbar">${b("ru", "🇷🇺")}${b("uz", "🇺🇿")}${b("en", "🇬🇧")}</div>`;
}
function bindLang() {
  $app.querySelectorAll(".lang").forEach(el => el.addEventListener("click", () => setLang(el.dataset.l)));
}
function setLang(l) {
  if (l === LANG || !T[l]) return;
  LANG = l;
  try { localStorage.setItem("lang", l); } catch (e) {}
  // Сохраняем язык в БД — чтобы бот и приложение были на одном языке (fire-and-forget).
  if (ME) { ME.lang = l; api("/api/me/lang", { json: { lang: l } }).catch(() => {}); }
  const top = navStack[navStack.length - 1];
  if (top) top.screen(top.params); else if (ME) home();
}

async function api(path, opts = {}) {
  const headers = opts.headers || {};
  if (tg && tg.initData) headers["X-Init-Data"] = tg.initData;
  else if (devUser) headers["X-Dev-User"] = devUser;
  if (ACT_AS && !path.startsWith("/api/admin") && !path.startsWith("/api/student")) headers["X-Act-As"] = ACT_AS;
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.json);
  }
  // Повторять безопасно всё, кроме отметки о сворачивании (её повтор засчитал бы лишний уход).
  const retries = path.endsWith("/leave") ? 0 : 2;
  let res;
  for (let attempt = 0; ; attempt++) {
    try {
      res = await fetch(path, { method: opts.method || (opts.body ? "POST" : "GET"), headers, body: opts.body });
      break;
    } catch (e) {
      if (attempt >= retries) throw new Error(t("no_conn"));
      await new Promise(r => setTimeout(r, 400 * (attempt + 1)));
    }
  }
  let data = null;
  try { data = await res.json(); } catch (e) {}
  if (!res.ok) throw new Error((data && data.detail) || `Ошибка ${res.status}`);
  return data;
}

function render(html) {
  document.body.classList.remove("testing");
  document.body.classList.remove("home");  // ссылка на создателя — только на главном (её добавляют home-экраны)
  hideTabs();  // нижнее меню — только на корневых экранах (их функции сами его показывают)
  $app.innerHTML = html; window.scrollTo(0, 0); bindLang();
}

/* нижнее таб-меню */
const TABS = [
  { id: "home", ico: "home", go: () => home() },
  { id: "games", ico: "gamepad", go: () => goTab(gamesScreen) },
  { id: "library", ico: "book", go: () => goTab(libraryScreen) },
  { id: "profile", ico: "user", go: () => goTab(profileScreen) },
];
function tabLabel(id) {
  return { home: t("tab_home"), games: t("tab_games"), library: t("tab_library"), profile: t("tab_profile") }[id];
}
function showTabs(active) {
  const bar = document.getElementById("tabbar");
  if (!bar) return;
  document.body.classList.add("hastabs");
  bar.classList.add("on");
  bar.innerHTML = TABS.map(x => `<button class="tab ${x.id === active ? "on" : ""}" data-tab="${x.id}">
    <span class="ti">${svgIcon(x.ico)}</span><span class="tl">${tabLabel(x.id)}</span></button>`).join("");
  bar.querySelectorAll(".tab").forEach(b => b.addEventListener("click", () => {
    const tb = TABS.find(x => x.id === b.dataset.tab); if (tb) { haptic("light"); tb.go(); }
  }));
}
function hideTabs() {
  const bar = document.getElementById("tabbar");
  document.body.classList.remove("hastabs");
  if (bar) bar.classList.remove("on");
}
function goTab(screen, params = {}) {  // переход по вкладке — с «корня» (назад не нужен)
  navStack = [{ screen, params }];
  clearTimers(); updateBack(); screen(params);
}
function on(sel, ev, fn) { const el = $app.querySelector(sel); if (el) el.addEventListener(ev, fn); }
function onAll(sel, ev, fn) { $app.querySelectorAll(sel).forEach(el => el.addEventListener(ev, e => fn(el, e))); }

/* ---------------------------------------------------------------- навигация */

function go(screen, params = {}, replace = false) {
  clearTimers();
  if (replace) navStack.pop();
  navStack.push({ screen, params });
  updateBack();
  screen(params);
}
function back() {
  if (navStack.length <= 1) return;
  clearTimers();
  navStack.pop();
  const top = navStack[navStack.length - 1];
  updateBack();
  top.screen(top.params);
}
function home() {
  navStack = [];
  go(ME.is_teacher ? teacherHome : studentHome);
}
function updateBack() {
  // BackButton есть не во всех клиентах (часть версий Telegram Desktop) — без защиты падало всё приложение.
  if (!tg || !tg.BackButton) return;
  try { if (navStack.length > 1 && !attemptCtx) tg.BackButton.show(); else tg.BackButton.hide(); } catch (e) {}
}
try { if (tg && tg.BackButton) tg.BackButton.onClick(back); } catch (e) {}

/* ---------------------------------------------------------------- старт */

async function boot() {
  if (tg) { try { tg.ready(); tg.expand(); } catch (e) {} try { tg.disableVerticalSwipes(); } catch (e) {} }
  if (!(tg && tg.initData) && !devUser) {
    render(`<div class="center"><h1>TestRoom</h1><p class="muted">${t("open_via_bot")}</p></div>`);
    return;
  }
  try {
    ME = await api("/api/me");
  } catch (e) {
    if (ACT_AS) { setActAs(null); return boot(); }
    render(`<div class="center"><p>${esc(e.message)}</p><button class="btn" onclick="location.reload()">${t("retry")}</button></div>`);
    return;
  }
  // Единый язык бота и приложения.
  // Прежний выбор языка в приложении хранился ТОЛЬКО локально (в телефоне) и на
  // сервер не попадал. Поэтому при первом входе после обновления делаем разовую
  // миграцию: если локальный выбор отличается от языка на сервере — переносим
  // локальный на сервер (это прежний выбор пользователя), и бот встаёт на тот же
  // язык. Дальше источник правды — сервер (общий с ботом).
  if (ME) {
    const serverLang = ["ru", "uz", "en"].includes(ME.lang) ? ME.lang : "ru";
    let localLang = null, synced = null;
    try { localLang = localStorage.getItem("lang"); synced = localStorage.getItem("langSynced"); } catch (e) {}
    if (!synced && ["ru", "uz", "en"].includes(localLang) && localLang !== serverLang) {
      LANG = localLang;
      ME.lang = localLang;
      api("/api/me/lang", { json: { lang: localLang } }).catch(() => {});
    } else {
      LANG = serverLang;
      try { localStorage.setItem("lang", serverLang); } catch (e) {}
    }
    try { localStorage.setItem("langSynced", "1"); } catch (e) {}
  }
  updateActBar();
  // Глубокая ссылка из бота: «#song» — сразу открыть экран создания песни.
  let wantSong = false;
  try { wantSong = (location.hash || "").replace("#", "") === "song"; } catch (e) {}
  if (!ME.full_name) go(nameScreen);
  else if (wantSong && ME.song_enabled) { home(); go(songScreen); }
  else home();
}

function setActAs(id) {
  ACT_AS = id ? String(id) : null;
  try { ACT_AS ? sessionStorage.setItem("actAs", ACT_AS) : sessionStorage.removeItem("actAs"); } catch (e) {}
}
function updateActBar() {
  const bar = document.getElementById("actbar");
  if (ME && ME.acting_as) {
    bar.innerHTML = `<span>🛠 Кабинет: <b>${esc(ME.acting_as.name || ME.acting_as.id)}</b>${ME.acting_as.blocked ? " (заблокирован)" : ""}</span><button id="actexit">Выйти</button>`;
    bar.classList.remove("hidden");
    document.getElementById("actexit").onclick = async () => {
      setActAs(null); clearTimers();
      ME = await api("/api/me"); updateActBar();
      navStack = []; go(adminScreen);
    };
  } else {
    bar.classList.add("hidden"); bar.innerHTML = "";
  }
}

function nameScreen() {
  render(`
    ${langBar()}
    <h1>${t("welcome")}</h1>
    <div class="card">
      <p>${t("name_hint")}</p>
      <input id="name" placeholder="${t("name_ph")}" autocomplete="name" value="${esc(ME.full_name || "")}">
      <button class="btn" id="save">${t("save")}</button>
    </div>`);
  on("#save", "click", async () => {
    try {
      const r = await api("/api/me/name", { json: { full_name: document.getElementById("name").value } });
      ME.full_name = r.full_name; home();
    } catch (e) { toast(e.message); }
  });
}

/* ---------------------------------------------------------------- смена роли */

async function switchToStudent() {
  if (!confirm(t("confirm_student"))) return;
  try {
    await api("/api/me/role", { json: { role: "student" } });
    ME = await api("/api/me"); updateActBar();
    navStack = []; home(); toast(t("now_student"));
  } catch (e) { toast(e.message); }
}

async function universityPickerScreen(params = {}) {
  const edit = !!params.edit;  // edit=true — преподаватель меняет своё место работы; иначе заявка
  let unis = [];
  try { unis = await api("/api/universities"); } catch (e) {}

  // Шаг 2: после выбора вуза спрашиваем кафедру, затем отправляем оба поля.
  function askKafedra(vuz) {
    render(`
      ${langBar()}
      <h1>${edit ? t("place_work") : t("become_teacher")}</h1>
      <div class="card"><div class="kv"><span>${t("vuz")}</span><span>${esc(vuz)}</span></div></div>
      <label>${t("kafedra")}</label>
      <input id="kaf" placeholder="${t("kafedra_ph")}" maxlength="200" value="${esc((edit && ME.teacher_kafedra) || "")}">
      <button class="btn" id="ksend">${edit ? t("save") : t("send_request")}</button>
      <button class="link" id="kback">${t("choose_other_vuz")}</button>
    `);
    document.getElementById("kaf").focus();
    on("#ksend", "click", () => {
      const kafedra = document.getElementById("kaf").value.trim();
      if (!kafedra) return toast(t("enter_kafedra"));
      submit(vuz, kafedra);
    });
    on("#kback", "click", () => go(universityPickerScreen, params, true));
  }
  async function submit(info, kafedra) {
    try {
      if (edit) {
        await api("/api/me/workplace", { json: { info, kafedra } });
        ME = await api("/api/me"); toast(t("saved")); back();
        return;
      }
      const r = await api("/api/me/teacher-request", { json: { info, kafedra } });
      ME = await api("/api/me"); updateActBar(); navStack = []; home();
      toast(r.role === "teacher" ? t("you_are_teacher") : t("request_sent"));
    } catch (e) { toast(e.message); }
  }

  render(`
    ${langBar()}
    <h1>${edit ? t("place_work_vuz") : t("become_teacher")}</h1>
    <p class="muted">${edit ? t("find_then_kaf") : t("choose_vuz_kaf")}</p>
    <input class="search" id="usearch" placeholder="${t("search_vuz")}" autocomplete="off">
    <div id="ulist"></div>
    <div class="item" id="uother"><span class="ico">➕</span><div class="grow">${t("other_vuz")}</div></div>
    <div id="otherbox" class="card hidden">
      <label>${t("vuz_name")}</label>
      <input id="oname" placeholder="${t("vuz_name_ph")}" maxlength="200">
      <button class="btn" id="osend">${t("next_arrow")}</button>
    </div>
  `);
  function drawList(q) {
    const ql = (q || "").trim().toLowerCase();
    const found = unis.map((u, i) => ({ u, i })).filter(x => !ql || x.u.toLowerCase().includes(ql));
    const el = document.getElementById("ulist");
    if (!el) return;
    el.innerHTML = found.length
      ? found.map(x => `<div class="item uni" data-i="${x.i}"><div class="grow">${esc(x.u)}</div></div>`).join("")
      : `<p class="muted small">${t("vuz_not_found")}</p>`;
    onAll(".uni", "click", el2 => askKafedra(unis[+el2.dataset.i]));
  }
  document.getElementById("usearch").addEventListener("input", e => drawList(e.target.value));
  on("#uother", "click", () => {
    document.getElementById("otherbox").classList.remove("hidden");
    document.getElementById("oname").focus();
  });
  on("#osend", "click", () => {
    const v = document.getElementById("oname").value.trim();
    if (!v) return toast(t("enter_vuz"));
    askKafedra(v);
  });
  drawList("");
}

async function profileScreen() {
  try { ME = await api("/api/me"); } catch (e) {}
  render(`
    ${langBar()}
    <h1>${t("profile")}</h1>
    <div class="card">
      <div class="kv"><span>${t("fio")}</span><span>${esc(ME.full_name || "—")}</span></div>
      <button class="btn secondary" id="editname">${t("edit_name")}</button>
    </div>
    ${ME.is_teacher ? `
    <div class="card">
      <div class="kv"><span>${t("vuz")}</span><span>${esc(ME.teacher_info || "—")}</span></div>
      <div class="kv"><span>${t("kafedra")}</span><span>${esc(ME.teacher_kafedra || "—")}</span></div>
      <button class="btn secondary" id="editwork">${t("edit_work")}</button>
    </div>` : `
    <div class="card">
      <div class="kv"><span>${t("vuz")}</span><span class="ell">${esc(ME.university || "—")}</span></div>
      <div class="kv"><span>${t("study_group")}</span><span>${esc(ME.study_group || "—")}</span></div>
      <button class="btn secondary" id="editstud">${t("edit_student")}</button>
    </div>
    <div class="card">
      <div class="row"><b>🏆 ${t("rating_title")}</b>
        <label class="switch"><input type="checkbox" id="rtg" ${ME.rating_public ? "checked" : ""}><span class="slider"></span></label>
      </div>
      <p class="muted small" style="margin:8px 0 0">${t("rating_hint")}</p>
    </div>`}
  `);
  showTabs("profile");
  on("#editname", "click", () => go(nameScreen));
  on("#editwork", "click", () => go(universityPickerScreen, { edit: true }));
  on("#editstud", "click", () => go(studentProfileScreen));
  const rtg = document.getElementById("rtg");
  if (rtg) rtg.addEventListener("change", async () => {
    try { await api("/api/me/rating", { json: { public: rtg.checked } }); ME.rating_public = rtg.checked; haptic("success"); }
    catch (e) { rtg.checked = !rtg.checked; toast(e.message); }
  });
}

// Студент выбирает вуз СТРОГО из списка (поиск только фильтрует) и вводит номер группы.
async function studentProfileScreen() {
  let unis = [];
  try { unis = await api("/api/universities"); } catch (e) {}
  let chosen = unis.includes(ME.university) ? ME.university : "";  // только значение из списка
  render(`
    ${langBar()}
    <h1>${t("my_vuz_group")}</h1>
    <p class="muted">${t("choose_vuz_student")}</p>
    <div class="card">
      <label>${t("vuz")}</label>
      <div id="usel" class="selbox ${chosen ? "" : "empty"}">${chosen ? esc(chosen) : t("vuz_not_chosen")}</div>
      <input class="search" id="usearch" placeholder="${t("search_vuz")}" autocomplete="off">
      <div id="ulist"></div>
      <label>${t("group_number")}</label>
      <input id="grp" placeholder="${t("group_ph")}" maxlength="100" value="${esc(ME.study_group || "")}">
      <button class="btn" id="save">${t("save_vuz_group")}</button>
    </div>
  `);
  const search = document.getElementById("usearch");
  const sel = document.getElementById("usel");
  function setChosen(u) {
    chosen = u;
    sel.textContent = u || t("vuz_not_chosen");
    sel.classList.toggle("empty", !u);
    search.value = ""; document.getElementById("ulist").innerHTML = "";
  }
  function drawList(q) {
    const ql = (q || "").trim().toLowerCase();
    const el = document.getElementById("ulist");
    if (!el) return;
    if (!ql) { el.innerHTML = ""; return; }
    const found = unis.filter(u => u.toLowerCase().includes(ql)).slice(0, 20);
    el.innerHTML = found.length
      ? found.map(u => `<div class="item uni" data-u="${esc(u)}"><div class="grow">${esc(u)}</div></div>`).join("")
      : `<p class="muted small">${t("vuz_not_found")}</p>`;
    onAll(".uni", "click", el2 => setChosen(el2.dataset.u));  // выбор — ТОЛЬКО кликом по списку
  }
  search.addEventListener("input", e => drawList(e.target.value));  // ввод только фильтрует
  on("#save", "click", async () => {
    const study_group = document.getElementById("grp").value.trim();
    if (!chosen || !unis.includes(chosen)) return toast(t("pick_vuz_list"));  // строго из списка
    try {
      await api("/api/me/student-profile", { json: { university: chosen, study_group } });
      ME = await api("/api/me"); haptic("success"); toast(t("saved")); back();
    } catch (e) { toast(e.message); }
  });
}

async function supportScreen() {
  render(`
    ${langBar()}
    <h1>${t("support")}</h1>
    <div class="card">
      <p class="muted small" style="margin:0 0 8px">${t("support_hint")}</p>
      <textarea id="smsg" rows="5" placeholder="${t("support_ph")}" maxlength="2000"></textarea>
      <button class="btn" id="ssend">${t("support_send")}</button>
    </div>
  `);
  on("#ssend", "click", async () => {
    const txt = (document.getElementById("smsg").value || "").trim();
    if (!txt) { toast(t("support_empty")); return; }
    const btn = document.getElementById("ssend"); btn.disabled = true;
    try {
      await api("/api/support", { json: { text: txt } });
      haptic("success"); toast(t("support_sent")); back();
    } catch (e) { haptic("error"); toast(e.message); btn.disabled = false; }
  });
}

/* ================================================================ СТУДЕНТ */

const LIBT = {
  ru: { lib: "Библиотека", search: "Поиск по названию и тексту…", all: "Все предметы", download: "⬇️ Скачать файл",
        none: "Пока нет материалов.", upload: "Загрузить в библиотеку", subject: "Предмет", title: "Название",
        title_ph: "Например: Кариес — лекция", file: "Файл (PDF, DOCX, TXT) · до 100 МБ", send: "Загрузить", choose: "Выберите файл",
        need_title: "Введите название", sent: "Отправлено на модерацию ✅", sending: "Загрузка…",
        file_sent: "Файл отправлен в чат с ботом", moder_hint: "Материал появится в библиотеке после одобрения админом.",
        open: "Открыть", opening: "Открываю…" },
  uz: { lib: "Kutubxona", search: "Nomi va matn bo'yicha qidirish…", all: "Barcha fanlar", download: "⬇️ Faylni yuklab olish",
        none: "Hozircha materiallar yo'q.", upload: "Kutubxonaga yuklash", subject: "Fan", title: "Nomi",
        title_ph: "Masalan: Karies — ma'ruza", file: "Fayl (PDF, DOCX, TXT) · 100 MB gacha", send: "Yuklash", choose: "Faylni tanlang",
        need_title: "Nomini kiriting", sent: "Moderatsiyaga yuborildi ✅", sending: "Yuklanmoqda…",
        file_sent: "Fayl bot chatiga yuborildi", moder_hint: "Material admin tasdig'idan so'ng kutubxonada paydo bo'ladi.",
        open: "Ochish", opening: "Ochilmoqda…" },
  en: { lib: "Library", search: "Search by title and text…", all: "All subjects", download: "⬇️ Download file",
        none: "No materials yet.", upload: "Upload to library", subject: "Subject", title: "Title",
        title_ph: "E.g. Caries — lecture", file: "File (PDF, DOCX, TXT) · up to 100 MB", send: "Upload", choose: "Choose a file",
        need_title: "Enter a title", sent: "Sent for moderation ✅", sending: "Uploading…",
        file_sent: "File sent to the bot chat", moder_hint: "The material appears in the library after admin approval.",
        open: "Open", opening: "Opening…" },
};
function libT() { return LIBT[LANG] || LIBT.ru; }

// Карточка результата: тексты по языку + иконки по уровню (совпадает с бэкенд-карточкой).
const RES = {
  ru: {
    champion: { t: "Чемпион!", s: "Ты знаешь тему на отлично. Так держать!" },
    great: { t: "Отличная работа!", s: "Крепкие знания. Ещё чуть-чуть до вершины!" },
    good: { t: "Хороший старт!", s: "Движешься верно. Повтори тему — и будет отлично!" },
    start: { t: "Всё впереди!", s: "Каждый эксперт начинал с нуля. Повтори и попробуй снова!" },
    score: (x, n) => `Правильных: ${x} из ${n}`,
    share: "📤 Поделиться результатом", sharing: "Отправляю…",
    sent: "Карточка отправлена в чат с ботом — делись! 🎉",
  },
  uz: {
    champion: { t: "Chempion!", s: "Mavzuni a'lo bilasan. Shu zayilda davom et!" },
    great: { t: "Ajoyib natija!", s: "Bilimlaring mustahkam. Cho'qqiga ozgina qoldi!" },
    good: { t: "Yaxshi boshlanish!", s: "To'g'ri yo'ldasan. Mavzuni takrorla — a'lo bo'ladi!" },
    start: { t: "Hammasi oldinda!", s: "Har bir mutaxassis noldan boshlagan. Takrorlab, yana urinib ko'r!" },
    score: (x, n) => `To'g'ri: ${x} / ${n}`,
    share: "📤 Natija bilan ulashish", sharing: "Yuborilmoqda…",
    sent: "Kartochka bot chatiga yuborildi — ulash! 🎉",
  },
  en: {
    champion: { t: "Champion!", s: "You know this topic perfectly. Keep it up!" },
    great: { t: "Great job!", s: "Solid knowledge. Almost at the top!" },
    good: { t: "Good start!", s: "You're on the right track. Review and you'll ace it!" },
    start: { t: "It's just the start!", s: "Every expert started somewhere. Review and try again!" },
    score: (x, n) => `Correct: ${x} of ${n}`,
    share: "📤 Share result", sharing: "Sending…",
    sent: "Card sent to the bot chat — share it! 🎉",
  },
};
function resT() { return RES[LANG] || RES.ru; }
function resTier(x, n) { const r = n ? x / n : 0; return r >= 0.9 ? "champion" : r >= 0.7 ? "great" : r >= 0.5 ? "good" : "start"; }
const RES_ICON = {
  champion: `<svg viewBox="0 0 24 24"><path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0V4z"/><path d="M17 5h3v2a3 3 0 0 1-3 3M7 5H4v2a3 3 0 0 0 3 3"/><circle cx="12" cy="8" r="1.6" fill="#fff" stroke="none"/></svg>`,
  great: `<svg viewBox="0 0 24 24"><path d="M12 2l2.6 5.3 5.9.9-4.2 4.1 1 5.8L12 15.9 6.7 18.2l1-5.8L3.5 8.2l5.9-.9L12 2z"/></svg>`,
  good: `<svg viewBox="0 0 24 24"><path d="M3 17l6-6 4 4 7-7"/><path d="M14 8h6v6"/></svg>`,
  start: `<svg viewBox="0 0 24 24"><path d="M4.5 16.5c-1.5 1.3-2 5-2 5s3.7-.5 5-2c.7-.8.7-2 0-2.8a2 2 0 0 0-3 .8z"/><path d="M12 15l-3-3c1-5 5-8 10-8 0 5-3 9-8 10z"/><circle cx="15" cy="9" r="1.4"/></svg>`,
};

async function libraryScreen(params = {}) {
  const L = libT();
  let subjects;
  try { subjects = await api("/api/library/subjects"); } catch (e) { return toast(e.message); }
  let cur = params.subject_id || 0;
  render(`
    ${langBar()}
    <h1>📚 ${L.lib}</h1>
    <input class="search" id="q" placeholder="${L.search}">
    <select id="subjsel">
      <option value="0">${L.all}</option>
      ${subjects.map(s => `<option value="${s.id}" ${cur === s.id ? "selected" : ""}>${esc(s.name)}${s.docs ? ` (${s.docs})` : ""}</option>`).join("")}
    </select>
    <div id="list" class="muted small" style="margin-top:10px">${t("loading")}</div>
  `);
  showTabs("library");
  const q = document.getElementById("q");
  async function load() {
    const el = document.getElementById("list");
    if (!el) return;
    const params = new URLSearchParams();
    if (cur) params.set("subject_id", cur);
    if (q.value.trim()) params.set("q", q.value.trim());
    let docs;
    try { docs = await api(`/api/library/docs?${params.toString()}`); }
    catch (e) { return toast(e.message); }
    el.className = "";
    el.innerHTML = docs.length ? docs.map(d => `
      <div class="item" data-id="${d.id}">
        ${d.has_cover ? `<img class="bookcover" data-cid="${d.id}" alt="">` : `<span class="ico">📄</span>`}
        <div class="grow"><div class="ell">${esc(d.title)}</div><div class="muted small">${esc(d.subject)}${d.by ? " · " + esc(d.by) : ""}</div></div>
        <button class="mini ok openbtn">${L.open}</button>
      </div>`).join("") : `<p class="muted small">${L.none}</p>`;
    // обложки требуют авторизации — грузим через fetch и подставляем blob
    document.querySelectorAll("#list .bookcover").forEach(async img => {
      try { const buf = await fetchFile(`/api/library/docs/${img.dataset.cid}/cover`); img.src = URL.createObjectURL(new Blob([buf], { type: "image/jpeg" })); }
      catch (e) {}
    });
    onAll("#list .item", "click", el2 => {
      try { tg && tg.HapticFeedback.impactOccurred("light"); } catch (e) {}
      go(libraryDocScreen, { id: +el2.dataset.id });
    });
  }
  document.getElementById("subjsel").addEventListener("change", e => { cur = +e.target.value; load(); });
  let tmr;
  q.addEventListener("input", () => { clearTimeout(tmr); tmr = setTimeout(load, 300); });
  load();
}

let _pdfjs;
function loadPdfJs() {
  if (window.pdfjsLib) return Promise.resolve();
  if (_pdfjs) return _pdfjs;
  _pdfjs = new Promise((res, rej) => {
    const s = document.createElement("script");
    s.src = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js";
    s.onload = () => {
      try { window.pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js"; res(); }
      catch (e) { rej(e); }
    };
    s.onerror = () => rej(new Error("pdfjs"));
    document.head.appendChild(s);
  });
  return _pdfjs;
}
async function fetchFile(path) {
  const headers = {};
  if (tg && tg.initData) headers["X-Init-Data"] = tg.initData;
  else if (devUser) headers["X-Dev-User"] = devUser;
  const r = await fetch(path, { headers });
  if (!r.ok) { let m = "Ошибка загрузки файла"; try { m = (await r.json()).detail || m; } catch (e) {} throw new Error(m); }
  return await r.arrayBuffer();
}
async function openPdf(id) {
  const setStatus = (msg) => { const s = document.getElementById("pdfstatus"); if (s) s.textContent = msg; };
  try { await loadPdfJs(); } catch (e) { setStatus("Не удалось открыть просмотр. Нажмите «Скачать файл»."); return; }
  const headers = {};
  if (tg && tg.initData) headers["X-Init-Data"] = tg.initData;
  else if (devUser) headers["X-Dev-User"] = devUser;
  let pdf;
  try {
    // url + httpHeaders → PDF.js тянет страницы по мере надобности (Range), а не весь файл сразу.
    pdf = await window.pdfjsLib.getDocument({ url: `/api/library/docs/${id}/file`, httpHeaders: headers, withCredentials: false }).promise;
  } catch (e) { setStatus("Файл не читается."); return; }
  const viewer = document.getElementById("viewer");
  if (!viewer) return;
  const total = pdf.numPages;
  let cur = 1, rendering = false, zoom = 1;
  const ZMIN = 1, ZMAX = 4;
  viewer.innerHTML = `
    <div class="pdfbar">
      <button class="mini" id="pprev">‹</button>
      <span class="pdfpos"><input id="pinput" type="number" min="1" max="${total}" value="1"> / ${total}</span>
      <button class="mini" id="pnext">›</button>
      <span class="pdfzoom"><button class="mini" id="zout">−</button><span id="zlabel">100%</span><button class="mini" id="zin">+</button></span>
    </div>
    <div class="pdfsearch">
      <input id="psearch" placeholder="Поиск по книге (тема, слово)…">
      <button class="mini ok" id="pfind">Найти</button>
    </div>
    <div id="pfound"></div>
    <div id="pcanvas"><div class="muted small">${t("loading")} <span class="spin"></span></div></div>
    <div class="muted small pdfhint">Листайте свайпом ← →, кнопками + / − меняйте размер. Страница запоминается.</div>
  `;
  const box = document.getElementById("pcanvas");
  // Debounced-сохранение страницы: не дёргаем сервер на каждый свайп.
  let saveTmr;
  function saveProgress(n) {
    clearTimeout(saveTmr);
    saveTmr = setTimeout(() => {
      api(`/api/library/docs/${id}/progress`, { json: { page: n } }).catch(() => {});
    }, 800);
  }
  function setZoom(z) {
    zoom = Math.max(ZMIN, Math.min(ZMAX, z));
    const zl = document.getElementById("zlabel"); if (zl) zl.textContent = Math.round(zoom * 100) + "%";
    box.classList.toggle("zoomed", zoom > 1);
    show(cur);
  }
  async function show(n) {
    n = Math.max(1, Math.min(total, (n | 0) || 1));
    cur = n;
    const inp = document.getElementById("pinput"); if (inp) inp.value = n;
    if (rendering) return;
    rendering = true;
    try {
      const page = await pdf.getPage(n);
      const base = page.getViewport({ scale: 1 });
      const cssW = (box.clientWidth || 340) - 2;
      const fit = Math.min(cssW / base.width, 2.5);
      const scale = fit * zoom;
      const vp = page.getViewport({ scale });
      const dpr = Math.min(window.devicePixelRatio || 1, 3); // чёткость на Retina
      const canvas = document.createElement("canvas");
      canvas.className = "pdfpage";
      canvas.width = Math.floor(vp.width * dpr);
      canvas.height = Math.floor(vp.height * dpr);
      canvas.style.width = Math.floor(vp.width) + "px";
      await page.render({ canvasContext: canvas.getContext("2d"), viewport: vp, transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null }).promise;
      box.innerHTML = ""; box.appendChild(canvas);
      saveProgress(n);
    } catch (e) { box.innerHTML = `<span class="muted small">Не удалось показать страницу.</span>`; }
    finally { rendering = false; }
  }
  on("#pprev", "click", () => show(cur - 1));
  on("#pnext", "click", () => show(cur + 1));
  on("#zin", "click", () => setZoom(zoom + 0.5));
  on("#zout", "click", () => setZoom(zoom - 0.5));
  document.getElementById("pinput").addEventListener("change", e => show(+e.target.value));
  // Свайп для перелистывания. Когда страница увеличена (zoom>1), жест отдаём
  // горизонтальной прокрутке (панорамирование), а не перелистыванию.
  let tx = 0, ty = 0, tm = false;
  box.addEventListener("touchstart", e => {
    if (e.touches.length !== 1) { tm = false; return; }
    tx = e.touches[0].clientX; ty = e.touches[0].clientY; tm = true;
  }, { passive: true });
  box.addEventListener("touchend", e => {
    if (!tm) return; tm = false;
    const dx = e.changedTouches[0].clientX - tx;
    const dy = e.changedTouches[0].clientY - ty;
    if (zoom > 1) return;                       // увеличено — не листаем
    if (Math.abs(dx) < 50 || Math.abs(dx) < Math.abs(dy) * 1.5) return;
    show(dx < 0 ? cur + 1 : cur - 1);           // влево — вперёд, вправо — назад
    haptic("light");
  }, { passive: true });
  async function doSearch() {
    const q = document.getElementById("psearch").value.trim();
    const found = document.getElementById("pfound");
    if (q.length < 2) { found.innerHTML = ""; return; }
    found.innerHTML = `<span class="muted small">Ищу…</span>`;
    let r;
    try { r = await api(`/api/library/docs/${id}/search?q=${encodeURIComponent(q)}`); }
    catch (e) { found.innerHTML = ""; return toast(e.message); }
    if (!r.pages || !r.pages.length) { found.innerHTML = `<span class="muted small">Ничего не найдено (в сканах поиск не работает).</span>`; return; }
    found.innerHTML = `<div class="muted small" style="margin:4px 0">Найдено на страницах:</div><div class="chips">${r.pages.map(p => `<button class="chip" data-p="${p}">${p}</button>`).join("")}</div>`;
    onAll("#pfound .chip", "click", el => show(+el.dataset.p));
    show(r.pages[0]);
  }
  on("#pfind", "click", doSearch);
  document.getElementById("psearch").addEventListener("keydown", e => { if (e.key === "Enter") doSearch(); });
  // Открываем на странице, где читатель остановился в прошлый раз.
  let startPage = 1;
  try { const p = await api(`/api/library/docs/${id}/progress`); if (p && p.page > 0) startPage = p.page; } catch (e) {}
  show(startPage);
}
async function libraryDocScreen({ id }) {
  const L = libT();
  // Сразу показываем «Открываю… ⟳», чтобы не казалось, что приложение зависло, пока грузятся данные.
  render(`<div class="loader"><div class="spin big"></div><p class="muted">${L.opening}</p></div>`);
  loadPdfJs().catch(() => {});  // грузим движок параллельно с метаданными — открытие быстрее
  let d;
  try { d = await api(`/api/library/docs/${id}`); } catch (e) { return toast(e.message); }
  const isPdf = d.is_pdf != null ? d.is_pdf : (d.filename || "").toLowerCase().endsWith(".pdf");
  const canSend = (d.size || 0) <= 50 * 1024 * 1024; // Telegram не отдаёт файлы больше 50 МБ
  render(`
    <div class="dochead">${d.has_cover ? `<img class="bookcover big" id="dcover" alt="">` : ""}
      <div><h1 class="ell">${esc(d.title)}</h1>
      <p class="muted small">${esc(d.subject)} · ${esc(d.filename)}</p></div></div>
    ${""/* кнопка «Скачать» временно скрыта */}
    <div id="viewer" class="${isPdf ? "pdfwrap" : "card doc"}">${
      isPdf ? `<div class="muted small" id="pdfstatus">${t("loading")} <span class="spin"></span></div>`
            : (d.text ? esc(d.text).replace(/\n/g, "<br>") : '<span class="muted">—</span>')
    }</div>
  `);
  if (d.has_cover) {
    (async () => { try { const buf = await fetchFile(`/api/library/docs/${id}/cover`); const im = document.getElementById("dcover"); if (im) im.src = URL.createObjectURL(new Blob([buf], { type: "image/jpeg" })); } catch (e) {} })();
  }
  on("#dl", "click", async () => {
    try { await api(`/api/library/docs/${id}/download`, { method: "POST" }); toast(L.file_sent); haptic("success"); }
    catch (e) { toast(e.message); }
  });
  if (isPdf) openPdf(id);
}

async function libraryUploadScreen() {
  const L = libT();
  let subjects;
  try { subjects = await api("/api/library/subjects"); } catch (e) { return toast(e.message); }
  render(`
    <h1>📚 ${L.upload}</h1>
    <div class="card">
      <label>${L.subject}</label>
      <select id="subj">${subjects.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join("")}</select>
      <label>${L.title}</label><input id="title" placeholder="${L.title_ph}">
      <label>${L.file}</label><input id="file" type="file" accept=".pdf,.docx,.txt">
      <button class="btn" id="go">${L.send}</button>
    </div>
    <p class="muted small">${L.moder_hint}</p>
  `);
  on("#go", "click", async () => {
    const f = document.getElementById("file").files[0];
    const title = document.getElementById("title").value.trim();
    if (!f) return toast(L.choose);
    if (!title) return toast(L.need_title);
    const btn = document.getElementById("go");
    btn.disabled = true; btn.textContent = L.sending;
    try {
      const fd = new FormData();
      fd.append("file", f); fd.append("subject_id", document.getElementById("subj").value); fd.append("title", title);
      await api("/api/library/docs", { body: fd, method: "POST" });
      haptic("success"); toast(L.sent); back();
    } catch (e) { toast(e.message); btn.disabled = false; btn.textContent = L.send; }
  });
}

function greetByTime() {
  const h = new Date().getHours();
  return h < 6 ? t("greet_night") : h < 12 ? t("greet_morning") : h < 18 ? t("greet_day") : t("greet_evening");
}
function firstName(full) { return (full || "").trim().split(/\s+/)[0] || (full || "—"); }
function computeStats(hist) {
  const fin = (hist || []).filter(x => x.finished);
  const solved = fin.length;
  const avg = solved ? Math.round(fin.reduce((a, x) => a + (x.total ? x.correct / x.total : 0), 0) / solved * 100) : 0;
  const mistakes = fin.reduce((a, x) => a + Math.max(0, (x.total || 0) - (x.correct || 0)), 0);
  const days = new Set();
  (hist || []).forEach(x => { const d = x.date && new Date(x.date); if (d && !isNaN(d)) days.add(d.toISOString().slice(0, 10)); });
  let streak = 0; const today = new Date();
  for (let i = 0; i < 400; i++) {
    const d = new Date(today); d.setDate(today.getDate() - i);
    const key = d.toISOString().slice(0, 10);
    if (days.has(key)) streak++;
    else if (i === 0) continue;  // сегодня без активности допустимо — считаем со вчера
    else break;
  }
  return { solved, avg, mistakes, streak };
}
function heroCard() {
  return `<div class="hero">
    <div class="hi">${greetByTime()},</div>
    <div class="nm ell">${esc(firstName(ME.full_name))}</div>
    <span class="streak">🔥 <b id="h-streak">0</b> ${t("streak_days")}</span>
    <div class="tiles">
      <div class="tile"><b id="h-solved">0</b><span>${t("st_solved")}</span></div>
      <div class="tile"><b id="h-avg">0%</b><span>${t("st_avg")}</span></div>
      <div class="tile"><b id="h-mist">0</b><span>${t("st_mistakes")}</span></div>
    </div></div>`;
}
function fillHero(hist) {
  const s = computeStats(hist);
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  set("h-streak", s.streak); set("h-solved", s.solved); set("h-avg", s.avg + "%"); set("h-mist", s.mistakes);
}
const CARD_PAL = {
  blue: { bg: "#e9f1fe", acc: "#2a6ff0" }, violet: { bg: "#f0eafe", acc: "#7c3aed" },
  orange: { bg: "#fdefe1", acc: "#ef6c00" }, emerald: { bg: "#e3f6ee", acc: "#0ea47f" },
  teal: { bg: "#e2f5f8", acc: "#0a9bb0" }, pink: { bg: "#fde9f1", acc: "#e23c84" },
  amber: { bg: "#fdf3dc", acc: "#d99400" }, red: { bg: "#fde9e8", acc: "#e2403d" },
};
// Современные line-иконки (Lucide-стиль), окрашиваются в акцент карточки (currentColor).
const ICONS = {
  monitor: '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
  book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 8l5-5 5 5"/><path d="M12 3v12"/>',
  music: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
  chart: '<path d="M3 3v18h18"/><rect x="7" y="11" width="3" height="6" rx="1"/><rect x="12" y="7" width="3" height="10" rx="1"/><rect x="17" y="13" width="3" height="4" rx="1"/>',
  cap: '<path d="M22 10L12 5 2 10l10 5 10-5z"/><path d="M6 12v5c0 1 2.7 3 6 3s6-2 6-3v-5"/>',
  chat: '<path d="M21 11.5a8.5 8.5 0 0 1-12.6 7.4L3 21l2.1-5.4A8.5 8.5 0 1 1 21 11.5z"/><path d="M8.5 12h.01M12 12h.01M15.5 12h.01"/>',
  library: '<path d="M4 4h4v16H4z"/><path d="M10 4h4v16h-4z"/><path d="M16.5 4.5l3.5.7 2.3 14.6-3.5-.6z"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 0 1-4 0v-.1A1.6 1.6 0 0 0 7 19.4a1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0-1.1-2.7H1a2 2 0 0 1 0-4h.1A1.6 1.6 0 0 0 2.6 7a1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.6 1.6 0 0 0 7 2.6h.1A1.6 1.6 0 0 0 8.6 1V1a2 2 0 0 1 4 0v.1A1.6 1.6 0 0 0 17 2.6a1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V7a1.6 1.6 0 0 0 1.1 1.5H23a2 2 0 0 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1.1z"/>',
  home: '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h5v-6h4v6h5V10"/>',
  gamepad: '<rect x="2" y="6" width="20" height="12" rx="5"/><path d="M7 11v3M5.5 12.5h3"/><circle cx="15.5" cy="11.5" r="1.1"/><circle cx="18" cy="14" r="1.1"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.2 3.6-6.5 8-6.5s8 2.3 8 6.5"/>',
  repeat: '<path d="M17 2l4 4-4 4"/><path d="M3 11V10a4 4 0 0 1 4-4h14"/><path d="M7 22l-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>',
  route: '<circle cx="6" cy="19" r="3"/><circle cx="18" cy="5" r="3"/><path d="M9 19h6a4 4 0 0 0 4-4V9"/><path d="M15 5H9a4 4 0 0 0-4 4v6"/>',
  spark: '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.7 1.8L21.5 17l-1.8.7L19 19.5l-.7-1.8L16.5 17l1.8-.3z"/>',
  pencil: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  trophy: '<path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0z"/><path d="M7 5H4v2a3 3 0 0 0 3 3M17 5h3v2a3 3 0 0 1-3 3"/>',
  clipboard: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v1H9z"/><path d="M8.5 13l2.2 2.2L15.5 10"/>',
  flag: '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><path d="M4 22V15"/>',
};
function svgIcon(name) {
  const p = ICONS[name] || ICONS.book;
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
}
function gcard(id, ico, label, sub, pal) {
  const p = CARD_PAL[pal] || CARD_PAL.emerald;
  return `<div class="gcard" id="${id}" style="background:${p.bg}">
    <span class="gic" style="color:${p.acc}">${svgIcon(ico)}</span>
    <div class="gt">${label}</div>${sub ? `<div class="gs">${sub}</div>` : ""}</div>`;
}
function gcardWide(id, ico, label, sub, pal) {
  const p = CARD_PAL[pal] || CARD_PAL.emerald;
  return `<div class="gcard wide" id="${id}" style="background:${p.bg}">
    <span class="gic" style="color:${p.acc}">${svgIcon(ico)}</span>
    <div class="wtext"><div class="gt">${label}</div>${sub ? `<div class="gs">${sub}</div>` : ""}</div>
    <span class="chev">›</span></div>`;
}

async function studentHome() {
  try { ME = await api("/api/me"); } catch (e) {}
  const pr = ME.prices || {};
  const PAYT = {
    ru: { bal: "Баланс", top: "💳 Пополнить" }, uz: { bal: "Balans", top: "💳 To'ldirish" },
    en: { bal: "Balance", top: "💳 Top up" },
  }[LANG] || { bal: "Баланс", top: "💳 Пополнить" };
  const payCard = (!ME.is_teacher && ME.pays) ? `
    <div class="card"><div class="row"><b>${PAYT.bal}</b><b>${fmtSum(ME.balance || 0)} сум</b></div>
      <button class="btn secondary" id="topup" style="margin-top:8px">${PAYT.top}</button></div>` : "";
  render(`
    ${langBar()}
    ${heroCard()}
    <div class="card">
      <p class="muted small" style="margin:0 0 6px">${t("enter_code")}</p>
      <input id="code" class="code-input" inputmode="numeric" maxlength="6" placeholder="••••••" autocomplete="off">
      <button class="btn" id="join">${t("start_test")}</button>
    </div>
    ${payCard}
    <h2>${t("quick_title")}</h2>
    <div class="grid">
      ${gcardWide("courses", "route", t("courses_title"), t("sub_courses"), "blue")}
      ${gcard("presstudio", "monitor", (PRESF[LANG] || PRESF.ru).title, "ИИ", "blue")}
      ${gcard("mytests", "book", t("my_tests_training"), t("sub_open_tests"), "violet")}
      ${gcard("upload", "upload", t("upload_my_test"), t("sub_upload"), "orange")}
      ${ME.song_enabled ? gcard("song", "music", songT().title.replace("🎵 ", ""), pr.song ? fmtSum(pr.song) + " сум" : "", "pink") : ""}
      ${gcard("rating", "trophy", t("rating_open"), t("rating_sub"), "amber")}
      ${gcard("mistakes", "repeat", t("mistakes_title"), t("sub_mistakes"), "red")}
      ${gcard("results", "chart", t("results_title"), t("sub_history"), "emerald")}
      ${ME.teacher_pending ? "" : gcardWide("torole", "cap", t("become_teacher"), t("sub_apply"), "teal")}
    </div>
    ${ME.teacher_pending ? `<p class="muted small">${t("pending_teacher")}</p>` : ""}
    <button class="btn secondary" id="homesupport" style="margin-top:10px">${t("support")}</button>
  `);
  document.body.classList.add("home");  // ссылка на создателя — только здесь
  showTabs("home");
  const code = document.getElementById("code");
  code.addEventListener("input", () => { code.value = code.value.replace(/\D/g, "").slice(0, 6); });
  code.addEventListener("keydown", e => { if (e.key === "Enter") join(); });
  on("#join", "click", join);
  on("#song", "click", () => go(songScreen));
  on("#homesupport", "click", () => go(supportScreen));
  on("#presstudio", "click", () => go(presentationStudioScreen));
  on("#mytests", "click", () => go(testsScreen));
  on("#upload", "click", () => go(uploadScreen));
  on("#torole", "click", () => go(universityPickerScreen));
  on("#results", "click", () => go(studentResultsScreen));
  on("#rating", "click", () => go(ratingScreen));
  on("#mistakes", "click", () => go(mistakesScreen));
  on("#courses", "click", () => go(coursesScreen));
  on("#topup", "click", () => { toast("Откройте чат бота и нажмите «💳 Пополнить баланс»"); try { tg && tg.close(); } catch (e) {} });
  async function join() {
    if (code.value.length !== 6) { toast(t("code_6")); return; }
    try {
      const st = await api("/api/student/join", { json: { code: code.value } });
      go(attemptScreen, { state: st });
    } catch (e) { haptic("error"); toast(e.message); }
  }
  try { fillHero(await api("/api/student/history")); } catch (e) {}
}

// Отдельный экран «Мои результаты» (история прохождений)
async function studentResultsScreen() {
  render(`${langBar()}<h1>📊 ${t("results_title")}</h1><div id="hist" class="muted small">${t("loading")}</div>`);
  let h;
  try { h = await api("/api/student/history"); } catch (e) { return toast(e.message); }
  const el = document.getElementById("hist");
  if (!el) return;
  el.className = "";
  el.innerHTML = h.length ? h.map(x => `
    <div class="item" data-id="${x.attempt_id}">
      <div class="grow"><div class="ell">${esc(x.test_title)}</div><div class="muted small">${fmtDate(x.date)}</div></div>
      <span class="badge">${x.finished ? `${x.correct}/${x.total}` : t("running")}</span>
    </div>`).join("") : `<p class="muted small">${t("no_history")}</p>`;
  onAll("#hist .item", "click", async el2 => {
    try { go(attemptScreen, { state: await api(`/api/student/attempts/${el2.dataset.id}`) }); }
    catch (e) { toast(e.message); }
  });
}

// Рейтинг студента: «Моя группа» / «Мой вуз». Скрытые — «Аноним», себя видно всегда.
async function ratingScreen(params = {}) {
  const scope = params.scope === "uni" ? "uni" : "group";
  render(`
    ${langBar()}
    <h1>🏆 ${t("rating_open")}</h1>
    <div class="tabs">
      <button class="${scope === "group" ? "on" : ""}" id="t-grp">${t("rating_group")}</button>
      <button class="${scope === "uni" ? "on" : ""}" id="t-uni">${t("rating_uni")}</button>
    </div>
    <div id="rbody" class="muted small">${t("loading")}</div>
  `);
  on("#t-grp", "click", () => go(ratingScreen, { scope: "group" }, true));
  on("#t-uni", "click", () => go(ratingScreen, { scope: "uni" }, true));
  let data;
  try { data = await api(`/api/rating?scope=${scope}`); } catch (e) { return toast(e.message); }
  const body = document.getElementById("rbody");
  if (!body) return;
  body.className = "";

  if (!data.available) {
    body.innerHTML = `
      <div class="card" style="text-align:center">
        <div class="modal-ic" style="margin:0 auto 10px">${svgIcon("trophy")}</div>
        <p class="muted" style="margin:0 0 12px">${data.need === "uni" ? t("rating_need_uni") : t("rating_need_group")}</p>
        <button class="btn" id="fill">${t("rating_fill")}</button>
      </div>`;
    on("#fill", "click", () => go(studentProfileScreen));
    return;
  }

  // всплывающее окно, если студент скрыт в рейтинге
  if (!data.rating_public) {
    showModal({
      icon: "🙈", title: t("rating_off_title"), text: t("rating_off_text"),
      actions: [
        { label: t("rating_enable_btn"), primary: true, onClick: () => go(studentProfileScreen) },
        { label: t("later_btn") },
      ],
    });
  }

  const testsWord = n => LANG === "ru"
    ? (n % 10 === 1 && n % 100 !== 11 ? "тест" : (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? "теста" : "тестов"))
    : LANG === "en" ? (n === 1 ? "test" : "tests") : "test";
  const medal = r => r === 1 ? "🥇" : r === 2 ? "🥈" : r === 3 ? "🥉" : `<span class="rnum">${r}</span>`;
  const rowHtml = r => `
    <div class="rrow${r.is_me ? " me" : ""}">
      <div class="rmed">${medal(r.rank)}</div>
      <div class="grow"><div class="ell">${esc(r.name)}${r.is_me && r.hidden ? ` <span class="muted small">(${t("anon").toLowerCase()})</span>` : ""}</div>
        <div class="muted small">${r.tests} ${testsWord(r.tests)}</div></div>
      <div class="rpts">${r.points} <span>${t("rating_pts")}</span></div>
    </div>`;

  const hasScores = data.top.some(r => r.points > 0);
  body.innerHTML = data.top.length && hasScores
    ? `<div class="rlist">${data.top.map(rowHtml).join("")}</div>`
    : `<div class="card muted" style="text-align:center">${t("rating_empty")}</div>`;

  // «Твоё место» — закреплённая строка, если себя нет в видимом топе
  if (data.me && !data.top.some(r => r.is_me)) {
    body.insertAdjacentHTML("beforeend",
      `<div class="muted small" style="margin:12px 0 4px">${t("rating_your_place")}</div><div class="rlist">${rowHtml(data.me)}</div>`);
  }
}

// Преподаватель: «Как учатся студенты» — выбор группы и успеваемость по его тестам.
async function teacherRatingScreen(params = {}) {
  render(`${langBar()}<h1>🏆 ${t("how_study")}</h1><div id="rtop"></div><div id="rbody" class="muted small">${t("loading")}</div>`);
  let groups;
  try { groups = await api("/api/teacher/rating/groups"); } catch (e) { return toast(e.message); }
  if (!groups.length) {
    // различаем «вуз не указан» и «нет студентов»
    let d = {};
    try { d = await api("/api/teacher/rating?group="); } catch (e) {}
    const msg = d.need_vuz ? t("teacher_need_vuz") : t("no_rating_groups");
    const body = document.getElementById("rbody");
    body.className = "";
    body.innerHTML = `<div class="card muted" style="text-align:center">${msg}${d.need_vuz ? `<br><button class="btn secondary" id="goprof" style="margin-top:10px">${t("edit_work")}</button>` : ""}</div>`;
    on("#goprof", "click", () => goTab(profileScreen));
    return;
  }
  const cur = (params.group && groups.includes(params.group)) ? params.group : "";  // "" — общий рейтинг
  document.getElementById("rtop").innerHTML = `
    <label>${t("group")}</label>
    <select id="grpsel">
      <option value="" ${cur === "" ? "selected" : ""}>${t("rating_all")}</option>
      ${groups.map(g => `<option value="${esc(g)}" ${g === cur ? "selected" : ""}>${esc(g)}</option>`).join("")}
    </select>`;
  document.getElementById("grpsel").addEventListener("change", e => go(teacherRatingScreen, { group: e.target.value }, true));
  await loadGroup(cur);

  async function loadGroup(group) {
    const body = document.getElementById("rbody");
    body.className = "muted small"; body.textContent = t("loading");
    let data;
    try { data = await api(`/api/teacher/rating?group=${encodeURIComponent(group)}`); } catch (e) { return toast(e.message); }
    body.className = "";
    if (!data.rows.length) { body.innerHTML = `<div class="card muted" style="text-align:center">${t("rating_empty")}</div>`; return; }
    const medal = r => r === 1 ? "🥇" : r === 2 ? "🥈" : r === 3 ? "🥉" : `<span class="rnum">${r}</span>`;
    const tw = n => LANG === "ru"
      ? (n % 10 === 1 && n % 100 !== 11 ? "тест" : (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? "теста" : "тестов"))
      : LANG === "en" ? (n === 1 ? "test" : "tests") : "test";
    const showGroup = !data.group;  // в «Общем» показываем группу студента
    body.innerHTML = `<div class="rlist">${data.rows.map(r => `
      <div class="rrow">
        <div class="rmed">${medal(r.rank)}</div>
        <div class="grow"><div class="ell">${esc(r.name)}</div>
          <div class="muted small">${showGroup && r.group ? esc(r.group) + " · " : ""}${r.tests} ${tw(r.tests)}${r.tests ? ` · ${r.avg}%` : ""}</div></div>
        <div class="rpts">${r.points} <span>${t("rating_pts")}</span></div>
      </div>`).join("")}</div>`;
  }
}

// «Мои ошибки» — разбор неверно отвеченных вопросов
async function mistakesScreen() {
  render(`${langBar()}<h1>🔁 ${t("mistakes_title")}</h1><div id="mk" class="muted small">${t("loading")}</div>`);
  let list;
  try { list = await api("/api/student/mistakes"); } catch (e) { return toast(e.message); }
  const el = document.getElementById("mk");
  if (!el) return;
  el.className = "";
  if (!list.length) { el.innerHTML = `<div class="card muted" style="text-align:center">${t("no_mistakes")}</div>`; return; }
  el.innerHTML = list.map(q => {
    const opts = (q.options || []).map((o, i) => {
      let cls = "mkopt";
      if (i === q.correct) cls += " ok";
      else if (i === q.chosen) cls += " bad";
      const tag = i === q.correct ? ` <b class="mktag ok">✓ ${t("correct_answer")}</b>`
        : (i === q.chosen ? ` <b class="mktag bad">✗ ${t("your_answer")}</b>` : "");
      return `<div class="${cls}">${esc(o)}${tag}</div>`;
    }).join("");
    return `<div class="card"><div style="font-weight:600;margin-bottom:8px">${esc(q.text)}</div>${opts}</div>`;
  }).join("");
}

// ---- студент: учебный путь (курсы → темы → теория + тест)
async function coursesScreen() {
  render(`${langBar()}<h1>🎓 ${t("courses_title")}</h1><div id="cl" class="muted small">${t("loading")}</div>`);
  let list;
  try { list = await api("/api/courses"); } catch (e) { return toast(e.message); }
  const el = document.getElementById("cl"); if (!el) return;
  el.className = "";
  el.innerHTML = list.length ? list.map(c => `
    <div class="item" data-id="${c.id}"><span class="ico">🎓</span>
      <div class="grow"><div class="ell">${esc(c.title)}</div><div class="muted small">${esc(c.info || "")}${c.info ? " · " : ""}${c.topics} тем</div></div>
      <span class="muted">›</span></div>`).join("") : `<div class="card muted">${t("no_courses")}</div>`;
  onAll("#cl .item", "click", e => go(courseScreen, { id: +e.dataset.id }));
}

async function courseScreen({ id }) {
  render(`${langBar()}<div id="cv" class="muted small">${t("loading")}</div>`);
  let d;
  try { d = await api(`/api/courses/${id}`); } catch (e) { return toast(e.message); }
  const el = document.getElementById("cv"); if (!el) return;
  el.className = "";
  const topics = d.topics.map((tp, i) => {
    const ready = tp.status === "done";
    const score = tp.best_total ? ` · ${tp.best_correct}/${tp.best_total}` : "";
    const badge = !ready ? `<span class="badge warn">…</span>` : (tp.read ? `<span class="badge ok">✓</span>` : "");
    return `<div class="item" data-tid="${tp.id}" data-ok="${ready ? 1 : 0}">
      <span class="ico" style="font-weight:700;color:var(--brand)">${i + 1}</span>
      <div class="grow"><div class="ell">${esc(tp.title)}</div>
        <div class="muted small">${ready ? (t("sub_courses") + score) : t("course_building")}</div></div>
      ${badge}<span class="muted">›</span></div>`;
  }).join("");
  el.innerHTML = `<h1 class="ell">${esc(d.title)}</h1>${d.info ? `<p class="muted small" style="margin:-6px 0 10px">${esc(d.info)}</p>` : ""}${topics}`;
  onAll("#cv .item", "click", e => { if (e.dataset.ok === "1") go(topicScreen, { id: +e.dataset.tid }); else toast(t("course_building")); });
}

function _theoryHtml(s) {
  const body = esc(s || "").replace(/\n{2,}/g, "</p><p>").replace(/\n/g, "<br>");
  return `<p>${body}</p>`;
}

async function topicScreen({ id }) {
  render(`${langBar()}<div class="center muted">${t("loading")}</div>`);
  let d;
  try { d = await api(`/api/courses/topics/${id}`); } catch (e) { return toast(e.message); }
  drawTheory();
  function drawTheory() {
    $app.innerHTML = `${langBar()}
      <h1 class="ell">${esc(d.title)}</h1>
      ${d.sources && d.sources.length ? `<p class="muted small" style="margin:-6px 0 8px">📚 ${t("sources_from")}: ${d.sources.map(esc).join("; ")}</p>` : ""}
      <div class="card theory">${_theoryHtml(d.theory)}</div>
      <button class="btn secondary" id="read" ${d.read ? "disabled" : ""}>${d.read ? t("theory_read") : t("mark_read")}</button>
      ${d.questions && d.questions.length ? `<button class="btn" id="test">${t("take_test")}${d.best_total ? ` · ${d.best_correct}/${d.best_total}` : ""}</button>` : ""}`;
    bindLang();
    on("#read", "click", async () => {
      try { await api(`/api/courses/topics/${id}/read`, { method: "POST" }); d.read = true; haptic("success"); drawTheory(); }
      catch (e) { toast(e.message); }
    });
    on("#test", "click", startTest);
  }
  // Практика (не экзамен): сетка номеров со свободным переходом и сменой ответа —
  // как «Практика» в референсе. Разбор правильных показываем в конце (можно менять ответы до «Завершить»).
  const PRAC = {
    ru: { prev: "‹ Назад", next: "Далее ›", finish: "Завершить практику", answered: "Отвечено",
      confirm: "Завершить? Без ответа: {n}." },
    uz: { prev: "‹ Orqaga", next: "Keyingi ›", finish: "Mashqni yakunlash", answered: "Javob berildi",
      confirm: "Yakunlaymizmi? Javobsiz: {n}." },
    en: { prev: "‹ Back", next: "Next ›", finish: "Finish practice", answered: "Answered",
      confirm: "Finish? Unanswered: {n}." },
  };
  function startTest() {
    const qs = d.questions;
    const chosen = new Array(qs.length).fill(null);  // выбранный индекс ответа или null
    const flags = new Array(qs.length).fill(false);  // «отмечено» для возврата
    const L = PRAC[LANG] || PRAC.ru;
    let cur = 0;
    drawQ();
    function drawQ() {
      const q = qs[cur];
      const ansN = chosen.filter(x => x !== null).length;
      const nav = qs.map((_, k) => {
        let c = "ts-n tap";
        if (k === cur) c += " cur"; else if (chosen[k] !== null) c += " done";
        if (flags[k]) c += " flag";
        return `<span class="${c}" data-k="${k}">${k + 1}</span>`;
      }).join("");
      $app.innerHTML = `
        <div class="ts-head">
          <div class="ts-head-top">
            <div class="ts-ic">${svgIcon("book")}</div>
            <div class="ts-meta"><b>${esc(d.title)}</b><span class="muted small">${L.answered}: ${ansN}/${qs.length}</span></div>
            <button class="ts-flag ${flags[cur] ? "on" : ""}" id="flag" aria-label="flag">${svgIcon("flag")}</button>
          </div>
          <div class="ts-progwrap">
            <div class="ts-prog"><span style="width:${Math.round(ansN * 100 / qs.length)}%"></span></div>
            <span class="ts-progn">${cur + 1}/${qs.length}</span>
          </div>
          <div class="ts-nav" id="nav">${nav}</div>
        </div>
        <div class="ts-q">${esc(q.q)}</div>
        <div class="ts-opts" id="opts">
          ${q.options.map((o, oi) => `<div class="option ${chosen[cur] === oi ? "selected" : ""}" data-i="${oi}"><span class="ts-badge">${String.fromCharCode(65 + oi)}</span><span>${esc(o)}</span></div>`).join("")}
        </div>
        <div class="ts-foot">
          <button class="btn secondary ts-prev" id="prev" ${cur === 0 ? "disabled" : ""}>${L.prev}</button>
          ${cur < qs.length - 1
            ? `<button class="btn" id="next">${L.next}</button>`
            : `<button class="btn" id="finish">${L.finish}</button>`}
        </div>`;
      onAll("#opts .option", "click", el => {
        chosen[cur] = +el.dataset.i;
        $app.querySelectorAll("#opts .option").forEach(b => b.classList.toggle("selected", b === el));
        const slot = $app.querySelector(`#nav .ts-n[data-k="${cur}"]`);
        if (slot && !slot.classList.contains("cur")) slot.classList.add("done");
      });
      onAll("#nav .ts-n", "click", el => { cur = +el.dataset.k; drawQ(); });
      on("#flag", "click", () => { flags[cur] = !flags[cur]; drawQ(); });
      on("#prev", "click", () => { if (cur > 0) { cur--; drawQ(); } });
      on("#next", "click", () => { if (cur < qs.length - 1) { cur++; drawQ(); } });
      on("#finish", "click", finishTest);
    }
    async function finishTest() {
      const left = chosen.filter(x => x === null).length;
      if (left && !confirm(L.confirm.replace("{n}", left))) return;
      let correct = 0;
      qs.forEach((q, k) => { if (chosen[k] === q.correct) correct++; });
      try { await api(`/api/courses/topics/${id}/test`, { json: { correct, total: qs.length } }); } catch (e) {}
      d.best_correct = correct; d.best_total = qs.length;
      const review = qs.map((q, k) => {
        const pick = chosen[k];
        const opts = q.options.map((o, oi) => {
          let cls = "mkopt";
          if (oi === q.correct) cls += " ok"; else if (oi === pick) cls += " bad";
          const tag = oi === q.correct ? ` <b class="mktag ok">✓ ${t("correct_answer")}</b>`
            : (oi === pick ? ` <b class="mktag bad">✗ ${t("your_answer")}</b>` : "");
          return `<div class="${cls}">${esc(o)}${tag}</div>`;
        }).join("");
        return `<div class="card"><div style="font-weight:600;margin-bottom:8px">${k + 1}. ${esc(q.q)}</div>${opts}</div>`;
      }).join("");
      $app.innerHTML = `<div class="verdict ${correct / qs.length >= 0.6 ? "ok" : "bad"}">${t("topic_test_done")}: ${correct} / ${qs.length}</div>
        ${review}
        <button class="btn" id="again">${t("take_test")}</button><button class="btn secondary" id="back">${t("back_home")}</button>`;
      haptic("success");
      on("#again", "click", startTest);
      on("#back", "click", drawTheory);
    }
  }
}

function attemptScreen({ state }) {
  if (state.status === "finished") { stopAttemptTracking(); return resultScreen(state); }
  startAttemptTracking(state.attempt_id, state.solo);
  let deadline = Date.now() + state.seconds_left * 1000;
  let selected = null;
  const q = state.question;
  const warn = state.leaves > 0
    ? `<div class="warnbox">⚠️ ${t("you_left")} ${state.leaves}${state.max_leaves ? "/" + state.max_leaves : ""} — ${t("teacher_sees")}</div>` : "";
  // Предупреждение в начале теста (не на тренировке).
  const rules = (q.number === 1 && !state.solo)
    ? `<div class="warnbox">⚠️ <b>${t("rules")}</b> ${t("rules_text")}</div>`
    : "";
  // Экзамен — анти-чит: сервер отдаёт по одному вопросу, назад нельзя, прыжков НЕТ.
  // Шапка: иконка + таймер-пилюля + сплошная полоса прогресса (без сетки-навигатора).
  render(`
    <div class="ts-head">
      <div class="ts-head-top">
        <div class="ts-ic">${svgIcon("clipboard")}</div>
        <div class="ts-meta"><b>${esc(state.test_title)}</b><span class="muted small">${esc(state.subject)}</span></div>
        <span class="timer ts-timer" id="timer">⏱ ${fmtTime(state.seconds_left)}</span>
      </div>
      <div class="ts-progwrap">
        <div class="ts-prog"><span style="width:${Math.round(state.answered * 100 / state.total)}%"></span></div>
        <span class="ts-progn">${t("question")} ${q.number} ${t("of")} ${state.total}</span>
      </div>
    </div>
    ${rules}${warn}
    <div class="ts-q">${esc(q.text)}</div>
    <div class="ts-opts">
      ${q.options.map((o, i) => `<div class="option" data-i="${i}"><span class="ts-badge">${String.fromCharCode(65 + i)}</span><span>${esc(o)}</span></div>`).join("")}
    </div>
    <button class="btn" id="answer" disabled>${t("answer")}</button>
  `);
  // Во время теста прячем подпись-ссылку на Instagram внизу — чтобы студент
  // случайно не нажал на неё и не вышел из теста.
  document.body.classList.add("testing");
  let answered = false, pendingNext = null;  // режим обучения: сначала показать ответ, потом «Дальше»
  onAll(".option", "click", el => {
    if (answered) return;
    $app.querySelectorAll(".option").forEach(x => x.classList.remove("selected"));
    el.classList.add("selected"); selected = +el.dataset.i;
    document.getElementById("answer").disabled = false;
  });
  on("#answer", "click", async () => {
    const btn = document.getElementById("answer");
    if (answered) {  // второе нажатие — переход к следующему вопросу/результату
      clearTimers();
      if (pendingNext.status === "finished") resultScreen(pendingNext);
      else attemptScreen({ state: pendingNext });
      return;
    }
    if (selected === null) return;
    btn.disabled = true;
    try {
      const st = await api(`/api/student/attempts/${state.attempt_id}/answer`, { json: { question_id: q.id, option_index: selected } });
      if (st.feedback) {  // режим обучения (тренировка): показываем верно/неверно и правильный вариант
        answered = true; pendingNext = st;
        const opts = $app.querySelectorAll(".option");
        opts.forEach(o => { o.classList.remove("selected"); o.style.pointerEvents = "none"; });
        if (opts[st.feedback.correct_index]) opts[st.feedback.correct_index].classList.add("correct");
        if (!st.feedback.is_correct && opts[st.feedback.chosen_index]) opts[st.feedback.chosen_index].classList.add("wrong");
        const info = document.createElement("div");
        info.className = "fbbox " + (st.feedback.is_correct ? "ok" : "no");
        info.textContent = st.feedback.is_correct ? t("correct_excl") : t("wrong_excl");
        btn.parentNode.insertBefore(info, btn);
        btn.textContent = st.status === "finished" ? t("show_result") : t("next");
        btn.disabled = false;
      } else {  // обычный тест (экзамен) — сразу к следующему без разбора
        clearTimers(); attemptScreen({ state: st });
      }
    } catch (e) { btn.disabled = false; toast(e.message); }
  });
  const tick = async () => {
    const left = (deadline - Date.now()) / 1000;
    const el = document.getElementById("timer");
    if (el) { el.textContent = "⏱ " + fmtTime(left); el.classList.toggle("low", left < 60); }
    if (left <= 0) {
      clearTimers();
      try { attemptScreen({ state: await api(`/api/student/attempts/${state.attempt_id}`) }); } catch (e) { toast(e.message); }
    }
  };
  timers.push(setInterval(tick, 500));
}

function resultScreen(st) {
  const reasons = {
    done: t("r_done"), time: t("r_time"), leaves: t("r_leaves"),
    kicked: t("r_kicked"), teacher: t("r_teacher"),
  };
  const pct = st.total ? Math.round(st.correct * 100 / st.total) : 0;
  let review = "";
  if (st.review && st.review.length) {
    review = `<h2>${t("your_answers")}</h2>` + st.review.map((r, i) => `
      <div class="card small">
        <div><b>${i + 1}.</b> ${esc(r.text)}</div>
        <div class="${r.is_correct ? "right" : "wrong"}">${r.is_correct ? "✓" : "✗"} ${t("your_answer")}: ${esc(r.chosen ?? "—")}</div>
        ${(!r.is_correct && r.correct) ? `<div class="right">${t("correct_ans")}: ${esc(r.correct)}</div>` : ""}
      </div>`).join("");
  }
  // Пока тест идёт для группы — разбор скрыт целиком (защита от списывания).
  if (st.answers_later) review += `<div class="card muted small">${t("answers_locked")}</div>`;
  const tier = resTier(st.correct, st.total);
  const R = resT();
  render(`
    <div class="rcard rt-${tier}">
      <div class="rc-ic">${RES_ICON[tier]}</div>
      <div class="rc-title">${R[tier].t}</div>
      <div class="rc-fio">${esc(ME && ME.full_name || "")}</div>
      <div class="rc-score">${R.score(st.correct, st.total)}</div>
      <div class="rc-sub">${R[tier].s}</div>
      <div class="rc-test">${esc(st.test_title || "")}</div>
    </div>
    <button class="btn" id="share">${R.share}</button>
    <p class="muted small" style="text-align:center">${t("time_word")} ${fmtTime(st.duration_sec)} · ${esc(reasons[st.reason] || t("r_default"))}</p>
    ${review}
    <button class="btn secondary" id="home">${t("back_home")}</button>
  `);
  haptic("success");
  on("#share", "click", async (e) => {
    const b = e.currentTarget, old = b.textContent;
    b.disabled = true; b.textContent = R.sharing;
    try { await api(`/api/student/attempts/${st.attempt_id}/share`, { json: {} }); toast(R.sent); }
    catch (err) { toast(err.message); }
    finally { b.disabled = false; b.textContent = old; }
  });
  on("#home", "click", home);
}

/* ---- отслеживание сворачивания приложения во время теста ---- */

let awaySince = null, awayForce = false;
let maxVH = 0, baseW = 0, splitActive = false;
let guardEl = null, guardTimer = null;

// Доступная высота окна: берём «стабильную» высоту от Telegram (она меняется при
// разделении экрана/плавающем окне), иначе — обычную высоту окна.
function viewH() {
  try { if (tg && tg.viewportStableHeight) return tg.viewportStableHeight; } catch (e) {}
  try { if (tg && tg.viewportHeight) return tg.viewportHeight; } catch (e) {}
  return window.innerHeight;
}

function startAttemptTracking(attemptId, solo) {
  if (attemptCtx && attemptCtx.id === attemptId) return;
  attemptCtx = { id: attemptId, solo: !!solo };
  maxVH = viewH(); baseW = window.innerWidth; splitActive = false; awaySince = null; awayForce = false;
  updateBack();
  try { tg && tg.enableClosingConfirmation(); } catch (e) {}
  clearInterval(guardTimer);
  if (!solo) guardTimer = setInterval(() => { checkHeight(); updateGuard(); }, 1000);  // на тренировке не нужно
}
function stopAttemptTracking() {
  attemptCtx = null; awaySince = null; awayForce = false; splitActive = false;
  clearInterval(guardTimer); hideGuard();
  updateBack();
  try { tg && tg.disableClosingConfirmation(); } catch (e) {}
}

/* Заслонка: пока студент не в полном фокусе (свернул / разделил экран / оверлей),
   прячем вопрос — нельзя одновременно видеть задание и подсказку. */
function isAway() {
  const unfocused = (typeof document.hasFocus === "function") ? !document.hasFocus() : false;
  return document.hidden || unfocused || splitActive;
}
function showGuard() {
  if (!guardEl) {
    guardEl = document.createElement("div");
    guardEl.className = "guard";
    guardEl.innerHTML = `<div><div style="font-size:46px">⚠️</div>
      <h2>${t("guard_title")}</h2>
      <p>${t("guard_text")}</p></div>`;
    document.body.appendChild(guardEl);
  }
  guardEl.style.display = "flex";
}
function hideGuard() { if (guardEl) guardEl.style.display = "none"; }
function updateGuard() {
  if (attemptCtx && !attemptCtx.solo && isAway()) showGuard(); else hideGuard();
}

// force=true — засчитать независимо от длительности (сворачивание / разделение экрана).
function wentAway(force) {
  if (!attemptCtx) return;
  if (awaySince === null) { awaySince = Date.now(); awayForce = !!force; }
  else if (force) awayForce = true;
  updateGuard();
}
async function cameBack() {
  updateGuard();
  if (!attemptCtx || awaySince === null) return;
  const seconds = Math.round((Date.now() - awaySince) / 1000);
  const force = awayForce;
  awaySince = null; awayForce = false;
  if (!force && seconds < 2) return;  // мелкое отвлечение (< 2 сек) не считаем
  try {
    const st = await api(`/api/student/attempts/${attemptCtx.id}/leave`, { json: { seconds: Math.max(seconds, 1) } });
    clearTimers(); haptic("warning");
    attemptScreen({ state: st });
  } catch (e) {}
}
// Сворачивание приложения — засчитываем сразу (force).
document.addEventListener("visibilitychange", () => { document.hidden ? wentAway(true) : cameBack(); });
if (tg) {
  try { tg.onEvent("deactivated", () => wentAway(true)); tg.onEvent("activated", cameBack); } catch (e) {}
}
// Потеря фокуса (боковая кнопка, плавающее окно, оверлей) — считаем, если дольше 2 сек.
window.addEventListener("blur", () => wentAway(false));
window.addEventListener("focus", cameBack);
// Разделение экрана / плавающее окно: доступная высота окна резко падает (ширина та же).
function checkHeight() {
  if (!attemptCtx) return;
  const h = viewH(), w = window.innerWidth;
  if (baseW && Math.abs(w - baseW) > baseW * 0.25) { baseW = w; maxVH = h; splitActive = false; updateGuard(); return; } // поворот — пересчёт
  if (h > maxVH) maxVH = h;
  const split = maxVH && h < maxVH * 0.78;   // высота упала больше ~22% → экран разделён
  if (split && !splitActive) { splitActive = true; wentAway(true); }
  else if (!split && splitActive) { splitActive = false; cameBack(); }
  updateGuard();
}
window.addEventListener("resize", checkHeight);
if (tg) { try { tg.onEvent("viewportChanged", checkHeight); } catch (e) {} }

/* ================================================================ ПРЕПОДАВАТЕЛЬ */

async function teacherHome() {
  try { ME = await api("/api/me"); } catch (e) {}
  const a = ME.active_session;
  render(`
    ${langBar()}
    <div class="hero">
      <div class="hi">${greetByTime()},</div>
      <div class="nm ell">${esc(firstName(ME.full_name))}</div>
      <span class="streak">${ME.is_pro_plus ? "💎 Pro+" : (ME.plan === "pro" ? "⭐ Pro" : "🎓 " + t("teacher"))}</span>
    </div>
    ${a ? `<div class="banner" id="active"><b>${t("test_running")} · ${esc(a.group)}</b><br>
      <span class="small">${esc(a.test_title)} · ${t("code")} <b>${a.code}</b> · ${t("time_left")} <span id="aleft">${fmtTime(a.seconds_left)}</span></span></div>` : ""}
    <h2>${t("quick_title")}</h2>
    <div class="grid">
      ${gcard("tests", "book", t("my_tests"), "", "blue")}
      ${gcard("createtest", "spark", t("create_test_title"), "ИИ", "orange")}
      ${gcard("studrating", "trophy", t("studrating"), t("studrating_sub"), "amber")}
      ${gcard("presstudio", "monitor", (PRESF[LANG] || PRESF.ru).title, "ИИ", "violet")}
      ${gcard("aichat", "chat", t("ai_assistant"), ME.is_pro_plus || ME.is_admin ? "" : "Pro+", "teal")}
      ${ME.song_enabled ? gcard("song", "music", songT().title.replace("🎵 ", ""), "", "pink") : ""}
      ${gcard("libupload", "library", libT().upload, "", "emerald")}
      ${gcard("history", "clock", t("history"), "", "amber")}
      ${ME.is_admin && !ME.acting_as ? gcard("admin", "settings", t("admin_panel"), "", "red") : ""}
    </div>
    ${ME.acting_as ? "" : `<button class="link" id="student">🎓 ${t("take_by_code")}</button>`}
    ${ME.is_admin || ME.acting_as ? "" : `<button class="link" id="torole">🎓 ${t("become_student")}</button>`}
    <p class="muted small" style="margin-top:6px">${t("upload_via_bot")}</p>
    <button class="btn secondary" id="homesupport" style="margin-top:8px">${t("support")}</button>
  `);
  document.body.classList.add("home");  // показываем ссылку на создателя только здесь
  showTabs("home");
  if (a) {
    on("#active", "click", () => go(liveScreen, { id: a.id }));
    const end = Date.now() + a.seconds_left * 1000;
    timers.push(setInterval(() => { const el = document.getElementById("aleft"); if (el) el.textContent = fmtTime((end - Date.now()) / 1000); }, 1000));
  }
  on("#tests", "click", () => go(testsScreen));
  on("#createtest", "click", () => go(testCreateScreen));
  on("#studrating", "click", () => go(teacherRatingScreen));
  on("#history", "click", () => go(historyScreen));
  on("#presstudio", "click", () => go(presentationStudioScreen));
  on("#song", "click", () => go(songScreen));
  on("#aichat", "click", () => go(aiChatScreen));
  on("#libupload", "click", () => go(libraryUploadScreen));
  on("#student", "click", () => go(studentHome));
  on("#admin", "click", () => go(adminScreen));
  on("#torole", "click", switchToStudent);
  on("#homesupport", "click", () => go(supportScreen));
}

// Список предметов-папок. Внутри каждой — свои тесты (экран subjectScreen).
async function testsScreen(params = {}) {
  const showArchive = !!params.archive;
  render(`<h1>${t("my_tests")}</h1><div class="muted">${t("loading")}</div>`);
  let subjects;
  try { subjects = await api("/api/teacher/subjects"); } catch (e) { return toast(e.message); }
  const archivedCount = subjects.reduce((n, s) => n + s.tests.filter(tt => tt.archived).length, 0);
  const folders = subjects
    .map(s => ({ s, n: s.tests.filter(tt => tt.archived === showArchive).length }))
    .filter(x => !showArchive || x.n > 0);  // в архиве показываем только предметы с архивными тестами
  const word = n => LANG === "ru" ? ((n % 10 === 1 && n % 100 !== 11) ? "тест" : "тестов") : t("count_tests");
  const list = folders.length ? folders.map(({ s, n }) => `
    <div class="item subj" data-id="${s.id}" data-n="${esc(s.name)}">
      <span class="ico">📁</span>
      <div class="grow"><div class="ell">${esc(s.name)}</div><div class="muted small">${n} ${word(n)}</div></div>
      <span class="muted">›</span>
    </div>`).join("")
    : `<div class="card muted">${showArchive ? t("archive_empty") : t("no_subjects")}</div>`;
  render(`
    ${langBar()}
    <h1>${showArchive ? t("archive_title") : t("my_tests")}</h1>
    <p class="muted small" style="margin:-4px 0 10px">${t("choose_subject_hint")}</p>
    <div class="tabs"><button class="${showArchive ? "" : "on"}" id="t-act">${t("tab_active")}</button>
      <button class="${showArchive ? "on" : ""}" id="t-arc">${t("tab_archive")} (${archivedCount})</button></div>
    ${list}
    <button class="btn" id="upload">✨ ${t("create_test_title")}</button>
  `);
  on("#t-act", "click", () => go(testsScreen, {}, true));
  on("#t-arc", "click", () => go(testsScreen, { archive: true }, true));
  on("#upload", "click", () => go(testCreateScreen));
  onAll(".subj", "click", el => go(subjectScreen, { id: +el.dataset.id, name: el.dataset.n, archive: showArchive }));
}

// Тесты внутри одного предмета.
async function subjectScreen(params = {}) {
  const id = params.id, showArchive = !!params.archive;
  render(`<h1 class="ell">📁 ${esc(params.name || t("subject_word"))}</h1><div class="muted">${t("loading")}</div>`);
  let subjects;
  try { subjects = await api("/api/teacher/subjects"); } catch (e) { return toast(e.message); }
  const s = subjects.find(x => x.id === id);
  if (!s) { toast(t("subject_not_found")); return back(); }
  const active = s.tests.filter(tt => !tt.archived).length;
  const archived = s.tests.filter(tt => tt.archived).length;
  const tests = s.tests.filter(tt => tt.archived === showArchive);
  const list = tests.length ? tests.map(tt => `
    <div class="card">
      <div class="ttoggle ell">${esc(tt.title)}</div>
      <div class="row" style="margin-top:8px">
        <span class="muted small">${tt.questions} ${t("questions_word")}</span>
        <button class="openbtn open" data-id="${tt.id}">${t("open_arrow")}</button>
      </div>
    </div>`).join("")
    : `<p class="muted small">${showArchive ? t("subj_archive_empty") : t("no_tests_subject")}</p>`;
  render(`
    ${langBar()}
    <h1 class="ell">📁 ${esc(s.name)}</h1>
    <p class="muted small" style="margin:-4px 0 10px">${showArchive ? t("arch_of_subject") : `${active} ${t("active_l")} · ${archived} ${t("arch_l")}`}</p>
    ${list}
    <button class="btn" id="upload">✨ ${t("create_test_title")}</button>
    ${showArchive ? "" : `<button class="btn danger delsubj" data-id="${s.id}" data-n="${esc(s.name)}">🗑 ${t("del_subject")}</button>`}
  `);
  onAll(".ttoggle", "click", (el, e) => { e.stopPropagation(); el.classList.toggle("ell"); });
  onAll(".open", "click", el => go(testScreen, { id: +el.dataset.id }));
  on("#upload", "click", () => go(testCreateScreen, { subject_id: s.id }));
  onAll(".delsubj", "click", async el => {
    if (!confirm(t("confirm_del_subject").replace("{n}", el.dataset.n))) return;
    try { await api(`/api/teacher/subjects/${el.dataset.id}`, { method: "DELETE" }); toast(t("subject_deleted")); back(); }
    catch (e) { toast(e.message); }
  });
}

async function testScreen({ id }) {
  let test;
  try { test = await api(`/api/teacher/tests/${id}`); } catch (e) { return toast(e.message); }
  const n = test.questions.length;
  const minOpt = (arr) => arr.map(m => `<option value="${m}" ${m === 30 ? "selected" : ""}>${m} ${t("min_word")}</option>`).join("");
  render(`
    ${langBar()}
    <p class="muted small" style="margin:0">${esc(test.subject)}</p>
    <h1 id="ttl" class="ell">${esc(test.title)}</h1>
    <button class="link" id="rename">✏️ ${t("rename_btn")}</button>
    <p class="muted">${n} ${t("questions_word")}${test.archived ? " · " + t("in_archive_suffix") : ""}</p>
    ${test.archived ? "" : `
    ${ME.is_teacher ? `
    <div class="card">
      <b>${t("launch_test")}</b>
      <label>${t("group")}</label><input id="group" placeholder="101" maxlength="100">
      <label>${t("time_on_test")}</label>
      <select id="dur">${minOpt([5, 10, 15, 20, 30, 40, 45, 60, 80, 90, 120])}</select>
      <label>${t("qc_label").replace("{n}", n)}</label>
      <input id="qc" type="number" min="1" max="${n}" value="${Math.min(n, 25)}">
      <label>${t("ml_label")}</label>
      <input id="ml" type="number" min="0" max="20" value="3">
      <label>${t("ms_label")}</label>
      <input id="ms" type="number" min="0" value="0">
      <label>${t("jw_label")}</label>
      <select id="jw">
        <option value="2">2 ${t("min_word")}</option>
        <option value="3" selected>3 ${t("min_word")}</option>
        <option value="5">5 ${t("min_word")}</option>
        <option value="10">10 ${t("min_word")}</option>
        <option value="0">${t("jw_opt_all")}</option>
      </select>
      <p class="muted small" style="margin:4px 0 0">${t("jw_hint")}</p>
      <button class="btn" id="start">▶️ ${t("activate_test")}</button>
    </div>` : ""}
    <div class="card">
      <b>${t("training_mode")}</b>
      <p class="muted small" style="margin:4px 0 0">${ME.is_teacher ? t("training_hint_t") : t("training_hint_s")}</p>
      <label>${t("sqc_label").replace("{n}", n)}</label>
      <input id="sqc" type="number" min="1" max="${n}" value="${Math.min(n, 25)}">
      <label>${t("time_on_test")}</label>
      <select id="sdur">${minOpt([5, 10, 15, 20, 30, 45, 60])}</select>
      <button class="btn" id="solo">▶️ ${t("solve")}</button>
    </div>`}
    <div class="item" id="edit"><span class="ico">✏️</span><div class="grow">${t("questions_edit")}</div><span class="muted">›</span></div>
    ${ME.acting_as ? `<button class="btn secondary" id="download">📥 ${t("download_test")}</button>` : ""}
    <button class="btn secondary" id="arch">${test.archived ? t("from_archive") : t("to_archive")}</button>
    <button class="btn danger" id="del">🗑 ${t("delete_test")}</button>
  `);
  on("#download", "click", async () => {
    try { await api(`/api/teacher/tests/${id}/download`, { method: "POST" }); toast(t("file_sent_chat")); haptic("success"); }
    catch (e) { toast(e.message); }
  });
  on("#rename", "click", () => {
    const h = document.getElementById("ttl");
    h.innerHTML = `<input id="newttl" value="${esc(test.title)}" maxlength="300" style="font-size:18px">`;
    document.getElementById("rename").outerHTML =
      `<button class="btn" id="savettl">${t("save_title")}</button><button class="link" id="cancelttl">${t("cancel")}</button>`;
    const inp = document.getElementById("newttl"); inp.focus();
    on("#savettl", "click", async () => {
      const title = inp.value.trim();
      if (!title) return toast(t("enter_title"));
      try {
        await api(`/api/teacher/tests/${id}`, { method: "PATCH", json: { title } });
        test.title = title; haptic("success"); toast(t("renamed")); go(testScreen, { id }, true);
      } catch (e) { toast(e.message); }
    });
    on("#cancelttl", "click", () => go(testScreen, { id }, true));
  });
  on("#del", "click", async () => {
    if (!confirm(t("confirm_del_test").replace("{n}", test.title))) return;
    try {
      await api(`/api/teacher/tests/${id}`, { method: "DELETE" });
      haptic("success"); toast(t("test_deleted")); back();
    } catch (e) { toast(e.message); }
  });
  on("#start", "click", async () => {
    const body = {
      test_id: id,
      group_name: document.getElementById("group").value,
      duration_min: +document.getElementById("dur").value,
      question_count: +document.getElementById("qc").value,
      max_leaves: +document.getElementById("ml").value,
      max_students: +document.getElementById("ms").value,
      join_window_min: +document.getElementById("jw").value,
    };
    if (!body.group_name.trim()) return toast(t("enter_group"));
    try {
      const s = await api("/api/teacher/sessions", { json: body });
      haptic("success");
      go(liveScreen, { id: s.id }, true);
    } catch (e) { toast(e.message); }
  });
  on("#solo", "click", async () => {
    try {
      const st = await api("/api/student/solo", {
        json: {
          test_id: id,
          question_count: +document.getElementById("sqc").value,
          duration_min: +document.getElementById("sdur").value,
        },
      });
      haptic("success");
      go(attemptScreen, { state: st }, true);
    } catch (e) { toast(e.message); }
  });
  on("#edit", "click", () => go(editorScreen, { id }));
  on("#arch", "click", async () => {
    try { await api(`/api/teacher/tests/${id}/archive`, { json: { archived: !test.archived } }); toast(test.archived ? t("test_restored") : t("test_archived")); back(); }
    catch (e) { toast(e.message); }
  });
}

async function liveScreen({ id }) {
  let first = true;
  async function load() {
    let d;
    try { d = await api(`/api/teacher/sessions/${id}/live`); } catch (e) { if (first) toast(e.message); return; }
    if (!d.active) { clearTimers(); go(resultsScreen, { id }, true); return; }
    const scroll = window.scrollY;
    const end = Date.now() + d.seconds_left * 1000;
    const joinEnd = Date.now() + d.join_seconds_left * 1000;
    const joinLine = d.join_window_min
      ? (d.join_seconds_left > 0
          ? `<div class="banner" style="text-align:center;cursor:default">${t("join_open_pre")} <b id="jleft">${fmtTime(d.join_seconds_left)}</b> ${t("join_open_post")}</div>`
          : `<div class="warnbox" style="text-align:center">${t("join_closed")}</div>`)
      : "";
    $app.innerHTML = `
      <p class="muted small" style="text-align:center;margin:0">${esc(d.test_title)} · ${t("group_word")} ${esc(d.group)}</p>
      <div class="big-code">${d.code.slice(0, 3)} ${d.code.slice(3)}</div>
      <p class="muted small" style="text-align:center;margin:0">${t("say_code")}</p>
      ${joinLine}
      <div class="stats">
        <div class="stat"><span class="muted small">${t("left_label")}</span><b class="timer" id="left">${fmtTime(d.seconds_left)}</b></div>
        <div class="stat"><span class="muted small">${t("joined_finished")}</span><b>${d.joined}${d.max_students ? "/" + d.max_students : ""} · ${d.finished_count}</b></div>
      </div>
      ${d.students.length ? d.students.map(s => `
        <div class="card">
          <div class="row"><span>${esc(s.name)}</span>
            <span>${s.leaves ? `<span class="badge warn">${t("minimized")} ${s.leaves}</span> ` : ""}${s.finished ? `<span class="badge ok">${esc(s.reason)}</span>` : `<span class="muted small">${s.answered}/${s.total}</span>`}</span></div>
          <div class="bar"><span style="width:${Math.round(s.answered * 100 / s.total)}%"></span></div>
          ${s.finished ? "" : `<button class="link kick" data-a="${s.attempt_id}" data-n="${esc(s.name)}">${t("remove_from_test")}</button>`}
        </div>`).join("") : `<div class="card muted">${t("nobody_joined")}</div>`}
      <button class="btn danger" id="finish">${t("finish_early")}</button>`;
    window.scrollTo(0, scroll);
    clearInterval(liveScreen._tick);
    liveScreen._tick = setInterval(() => {
      const el = document.getElementById("left"); if (el) el.textContent = fmtTime((end - Date.now()) / 1000);
      const jl = document.getElementById("jleft"); if (jl) jl.textContent = fmtTime(Math.max(0, (joinEnd - Date.now()) / 1000));
    }, 1000);
    timers.push(liveScreen._tick);
    onAll(".kick", "click", async el => {
      if (!confirm(t("confirm_remove").replace("{n}", el.dataset.n))) return;
      try { await api(`/api/teacher/sessions/${id}/kick`, { json: { attempt_id: +el.dataset.a } }); load(); } catch (e) { toast(e.message); }
    });
    on("#finish", "click", async () => {
      if (!confirm(t("confirm_finish"))) return;
      try { await api(`/api/teacher/sessions/${id}/finish`, { method: "POST" }); clearTimers(); go(resultsScreen, { id }, true); } catch (e) { toast(e.message); }
    });
    first = false;
  }
  render(`<div class="center muted">${t("loading")}</div>`);
  await load();
  timers.push(setInterval(load, 3000));
}

async function resultsScreen({ id }) {
  let r;
  try { r = await api(`/api/teacher/sessions/${id}/results`); } catch (e) { return toast(e.message); }
  render(`
    ${langBar()}
    <p class="muted small" style="margin:0">${esc(r.test_title)}</p>
    <h1>${t("results_word")} · ${t("group_word")} ${esc(r.group)}</h1>
    <div class="stats">
      <div class="stat"><span class="muted small">${t("avg_result")}</span><b>${r.avg_percent ?? "—"}${r.avg_percent != null ? "%" : ""}</b></div>
      <div class="stat"><span class="muted small">${t("wrote")}</span><b>${r.ranking.length}</b></div>
    </div>
    ${r.active ? `<button class="btn secondary" id="live">${t("still_running_online")}</button>` : ""}
    <h2>${t("ranking")}</h2>
    ${r.ranking.length ? `<div class="card">${r.ranking.map((x, i) => `
      <div class="row" style="padding:5px 0">
        <span>${i + 1}. ${esc(x.name)} ${x.suspicious ? `<span class="badge warn">${t("minimized")} ${x.leaves}</span>` : ""}</span>
        <span><b>${x.correct}/${x.total}</b> <span class="muted small">${fmtTime(x.duration_sec)}</span></span>
      </div>`).join("")}</div>` : `<div class="card muted">${t("nobody_took")}</div>`}
    ${r.hardest.length ? `<h2>${t("hard_questions")}</h2>` + r.hardest.slice(0, 5).map(h => `
      <div class="card small"><div>${esc(h.text)}</div>
      <div class="row"><span class="right">${t("answer_label")}: ${esc(h.right_answer)}</span><span class="badge ${h.correct_percent < 50 ? "danger" : ""}">${h.correct_percent}${t("pct_correct")}</span></div></div>`).join("") : ""}
    <button class="btn" id="export">${t("get_excel")}</button>
  `);
  on("#live", "click", () => go(liveScreen, { id }, true));
  on("#export", "click", async () => {
    try { await api(`/api/teacher/sessions/${id}/export`, { method: "POST" }); toast(t("file_sent_chat")); haptic("success"); }
    catch (e) { toast(e.message); }
  });
}

async function historyScreen() {
  render(`<h1>${t("history_short")}</h1><div class="muted">${t("loading")}</div>`);
  let list;
  try { list = await api("/api/teacher/sessions"); } catch (e) { return toast(e.message); }
  const groups = [...new Set(list.map(x => x.group))];
  const draw = (g) => {
    const rows = list.filter(x => !g || x.group === g);
    $app.innerHTML = `
      <h1>${t("history")}</h1>
      <select id="g"><option value="">${t("all_groups")}</option>${groups.map(x => `<option ${x === g ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>
      <div style="margin-top:10px">${rows.length ? rows.map(x => `
        <div class="item" data-id="${x.id}" data-active="${x.active}">
          <div class="grow"><div class="ell">${esc(x.test_title)}</div><div class="muted small">${t("group_word")} ${esc(x.group)} · ${fmtDate(x.started_at)} · ${x.students} ${t("people")}</div></div>
          ${x.active ? `<span class="badge ok">${t("running")}</span>` : `<b>${x.avg_percent ?? "—"}${x.avg_percent != null ? "%" : ""}</b>`}
        </div>`).join("") : `<div class="card muted">${t("no_launches")}</div>`}</div>`;
    on("#g", "change", e => draw(e.target.value));
    onAll(".item", "click", el => go(el.dataset.active === "true" ? liveScreen : resultsScreen, { id: +el.dataset.id }));
  };
  draw("");
}

// Хаб создания теста: ИИ / вручную / файл. Преподу больше не нужно уметь писать вопросы.
async function testCreateScreen(params = {}) {
  render(`
    ${langBar()}
    <h1>${t("create_test_title")}</h1>
    <div class="grid">
      ${gcardWide("c-ai", "spark", t("t_by_ai"), t("t_by_ai_sub"), "orange")}
      ${gcardWide("c-man", "pencil", t("t_by_manual"), t("t_by_manual_sub"), "blue")}
      ${gcardWide("c-file", "upload", t("t_by_file"), t("t_by_file_sub"), "emerald")}
    </div>
  `);
  on("#c-ai", "click", () => go(testAiScreen, params));
  on("#c-man", "click", () => go(testManualScreen, params));
  on("#c-file", "click", () => go(uploadScreen, params));
}

// Выбор предмета (select + «новый предмет»). Возвращает id предмета, создавая его при нужде.
function subjectPicker(subjects, params) {
  const html = `
    <label>${t("subject_label")}</label>
    <select id="subj">${subjects.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join("")}<option value="new">${t("new_subject_opt")}</option></select>
    <div id="newsubj" class="${subjects.length ? "hidden" : ""}"><label>${t("subject_name_label")}</label><input id="sname" placeholder="${t("subject_name_ph")}"></div>`;
  const wire = () => {
    const subj = document.getElementById("subj");
    if (params.subject_id && subjects.some(s => s.id === params.subject_id)) subj.value = String(params.subject_id);
    else if (!subjects.length) subj.value = "new";
    subj.addEventListener("change", () => document.getElementById("newsubj").classList.toggle("hidden", subj.value !== "new"));
  };
  const resolve = async () => {
    const subj = document.getElementById("subj");
    if (subj.value === "new") {
      const s = await api("/api/teacher/subjects", { json: { name: document.getElementById("sname").value } });
      return s.id;
    }
    return +subj.value;
  };
  return { html, wire, resolve };
}

// ИИ генерирует тест по теме → сразу открываем редактор с готовыми вопросами.
async function testAiScreen(params = {}) {
  let subjects = [];
  try { subjects = await api("/api/teacher/subjects"); } catch (e) { return toast(e.message); }
  const picker = subjectPicker(subjects, params);
  const counts = [5, 10, 15, 20, 30];
  const diffs = [["easy", t("diff_easy")], ["medium", t("diff_medium")], ["hard", t("diff_hard")]];
  render(`
    ${langBar()}
    <h1>🤖 ${t("t_by_ai")}</h1>
    <div class="card">
      ${picker.html}
      <label>${t("gen_test_topic")}</label><input id="topic" placeholder="${t("test_name_ph")}">
      <label>${t("gen_count")}</label>
      <select id="count">${counts.map(c => `<option value="${c}" ${c === 10 ? "selected" : ""}>${c}</option>`).join("")}</select>
      <label>${t("gen_difficulty")}</label>
      <select id="diff">${diffs.map(([v, l], i) => `<option value="${v}" ${i === 1 ? "selected" : ""}>${l}</option>`).join("")}</select>
      <button class="btn" id="go">${t("gen_btn")}</button>
    </div>
  `);
  picker.wire();
  on("#go", "click", async () => {
    const topic = document.getElementById("topic").value.trim();
    if (!topic) return toast(t("gen_test_topic"));
    const btn = document.getElementById("go");
    btn.disabled = true; btn.textContent = t("gen_wait");
    try {
      const subject_id = await picker.resolve();
      const r = await api("/api/teacher/tests/generate", { json: {
        subject_id, topic, title: topic,
        count: +document.getElementById("count").value,
        difficulty: document.getElementById("diff").value, lang: LANG,
      } });
      haptic("success");
      go(editorScreen, { id: r.test_id }, true);
    } catch (e) {
      toast(e.message); btn.disabled = false; btn.textContent = t("gen_btn");
    }
  });
}

// Создать пустой тест и добавлять вопросы вручную.
async function testManualScreen(params = {}) {
  let subjects = [];
  try { subjects = await api("/api/teacher/subjects"); } catch (e) { return toast(e.message); }
  const picker = subjectPicker(subjects, params);
  render(`
    ${langBar()}
    <h1>✍️ ${t("t_by_manual")}</h1>
    <div class="card">
      ${picker.html}
      <label>${t("test_name_label")}</label><input id="title" placeholder="${t("test_name_ph")}">
      <button class="btn" id="go">${t("create_btn2")}</button>
    </div>
  `);
  picker.wire();
  on("#go", "click", async () => {
    const title = document.getElementById("title").value.trim();
    if (!title) return toast(t("enter_test_name"));
    const btn = document.getElementById("go");
    btn.disabled = true;
    try {
      const subject_id = await picker.resolve();
      const r = await api("/api/teacher/tests/empty", { json: { subject_id, title } });
      haptic("success");
      go(editorScreen, { id: r.test_id }, true);
    } catch (e) { toast(e.message); btn.disabled = false; }
  });
}

async function uploadScreen(params = {}) {
  let subjects = [];
  try { subjects = await api("/api/teacher/subjects"); } catch (e) { return toast(e.message); }
  render(`
    ${langBar()}
    <h1>${t("upload_test")}</h1>
    <div class="card">
      <label>${t("subject_label")}</label>
      <select id="subj">${subjects.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join("")}<option value="new">${t("new_subject_opt")}</option></select>
      <div id="newsubj" class="${subjects.length ? "hidden" : ""}"><label>${t("subject_name_label")}</label><input id="sname" placeholder="${t("subject_name_ph")}"></div>
      <label>${t("test_name_label")}</label><input id="title" placeholder="${t("test_name_ph")}">
      <label>${t("file_label")}</label><input id="file" type="file" accept=".docx,.xlsx,.txt">
      <button class="btn" id="go">${t("upload_btn")}</button>
    </div>
    <div id="report"></div>
    <p class="muted small">${t("upload_format_hint")}</p>
  `);
  const subj = document.getElementById("subj");
  if (params.subject_id && subjects.some(s => s.id === params.subject_id)) subj.value = String(params.subject_id);
  else if (!subjects.length) subj.value = "new";
  subj.addEventListener("change", () => document.getElementById("newsubj").classList.toggle("hidden", subj.value !== "new"));

  async function send(saveValid) {
    const f = document.getElementById("file").files[0];
    const title = document.getElementById("title").value.trim();
    if (!f) return toast(t("choose_file"));
    if (!title) return toast(t("enter_test_name"));
    try {
      let sid = subj.value;
      if (sid === "new") {
        const s = await api("/api/teacher/subjects", { json: { name: document.getElementById("sname").value } });
        sid = s.id;
        subj.insertAdjacentHTML("afterbegin", `<option value="${s.id}">${esc(s.name)}</option>`);
        subj.value = s.id; document.getElementById("newsubj").classList.add("hidden");
      }
      const fd = new FormData();
      fd.append("file", f); fd.append("subject_id", sid); fd.append("title", title); fd.append("save_valid", saveValid ? "true" : "false");
      const r = await api("/api/teacher/tests/upload", { body: fd, method: "POST" });
      if (r.saved) { haptic("success"); toast(t("saved_questions").replace("{n}", r.valid)); go(testScreen, { id: r.test_id }, true); return; }
      document.getElementById("report").innerHTML = `
        <div class="card">
          <b>${t("found_questions").replace("{n}", r.found)}</b><br>✅ ${t("without_errors")}: ${r.valid}<br>⚠️ ${t("with_errors")}: ${r.errors.length}
          ${r.errors.slice(0, 30).map(e => `<div class="errbox"><b>№${e.number}:</b> ${esc(e.message)}<br><span class="muted small">${esc(e.preview)}</span></div>`).join("")}
          ${r.valid ? `<button class="btn" id="savevalid">${t("save_valid_btn").replace("{n}", r.valid)}</button>` : ""}
          <p class="muted small">${t("fix_and_retry")}</p>
        </div>`;
      on("#savevalid", "click", () => send(true));
    } catch (e) { toast(e.message); }
  }
  on("#go", "click", () => send(false));
}

async function editorScreen({ id }) {
  let test;
  try { test = await api(`/api/teacher/tests/${id}`); } catch (e) { return toast(e.message); }
  render(`
    ${langBar()}
    <h1 class="ell">${esc(test.title)}</h1>
    <p class="muted">${test.questions.length} ${t("questions_word")}</p>
    ${test.questions.length && ME.is_teacher ? `<button class="btn" id="launch">▶️ ${t("launch_test")}</button>` : ""}
    <div id="list">${test.questions.map((q, i) => `
      <div class="card" data-qi="${i}">
        <div class="row"><b>№${i + 1}</b><span><button class="link ed" data-qi="${i}">${t("edit_word")}</button></span></div>
        <div style="white-space:pre-wrap">${esc(q.text)}</div>
        <div class="small right">✓ ${esc(q.options[q.correct])}</div>
        <div class="muted small">${q.options.length} ${t("options_word")}</div>
      </div>`).join("")}</div>
    <button class="btn secondary" id="add">${t("add_question")}</button>
  `);
  on("#launch", "click", () => go(testScreen, { id }));
  onAll(".ed", "click", el => go(questionForm, { testId: id, q: test.questions[+el.dataset.qi] }));
  on("#add", "click", () => go(questionForm, { testId: id, q: null }));
}

function questionForm({ testId, q }) {
  const opts = q ? [...q.options] : ["", "", "", ""];
  let correct = q ? q.correct : 0;
  const draw = () => {
    $app.innerHTML = `
      <h1>${q ? t("edit_question") : t("new_question")}</h1>
      <div class="card qedit">
        <label>${t("question_text")}</label><textarea id="qt">${esc(q ? q.text : "")}</textarea>
        <label>${t("choose_correct")}</label>
        ${opts.map((o, i) => `<div class="opt"><input type="radio" name="c" value="${i}" ${i === correct ? "checked" : ""}>
          <input class="ot" data-i="${i}" value="${esc(o)}" placeholder="${t("option_word")} ${String.fromCharCode(65 + i)}">
          ${opts.length > 2 ? `<button class="link rm" data-i="${i}">✕</button>` : ""}</div>`).join("")}
        ${opts.length < 10 ? `<button class="link" id="addopt">${t("add_option")}</button>` : ""}
        <button class="btn" id="save">${t("save")}</button>
        ${q ? `<button class="btn danger" id="del">${t("delete_question")}</button>` : ""}
      </div>`;
    const sync = () => { $app.querySelectorAll(".ot").forEach(el => opts[+el.dataset.i] = el.value); const r = $app.querySelector("input[name=c]:checked"); correct = r ? +r.value : 0; };
    on("#addopt", "click", () => { sync(); opts.push(""); draw(); });
    onAll(".rm", "click", el => { sync(); const i = +el.dataset.i; opts.splice(i, 1); if (correct >= opts.length) correct = 0; else if (i < correct) correct--; draw(); });
    on("#save", "click", async () => {
      sync();
      const body = { text: document.getElementById("qt").value, options: opts, correct };
      try {
        if (q) await api(`/api/teacher/questions/${q.id}`, { method: "PUT", json: body });
        else await api(`/api/teacher/tests/${testId}/questions`, { json: body });
        toast(t("saved")); back();
      } catch (e) { toast(e.message); }
    });
    on("#del", "click", async () => {
      if (!confirm(t("confirm_del_question"))) return;
      try { await api(`/api/teacher/questions/${q.id}`, { method: "DELETE" }); toast(t("deleted")); back(); } catch (e) { toast(e.message); }
    });
  };
  draw();
}

/* ================================================================ АДМИН */

async function adminScreen(params = {}) {
  const tab = params.tab || "teachers";
  render(`<h1>Админ-панель</h1><div class="muted">Загрузка…</div>`);
  let st;
  try { st = await api("/api/admin/stats"); } catch (e) { return toast(e.message); }
  render(`
    <h1>Админ-панель</h1>
    <div class="stats">
      <div class="stat"><span class="muted small">Преподавателей</span><b>${st.teachers}</b></div>
      <div class="stat"><span class="muted small">Заявок</span><b>${st.pending}</b></div>
      <div class="stat"><span class="muted small">Pro-подписок</span><b>${st.pro}</b></div>
      <div class="stat"><span class="muted small">💎 Pro+ подписок</span><b>${st.proplus ?? 0}</b></div>
      <div class="stat tap" id="m-users"><span class="muted small">👥 Пользователей сегодня ›</span><b>${st.users_today ?? 0}</b></div>
      <div class="stat tap" id="m-tests"><span class="muted small">📝 Тестов сегодня ›</span><b>${st.tests_today ?? 0}</b></div>
      <div class="stat tap" id="m-pres"><span class="muted small">🖥 Презентаций сегодня ›</span><b>${st.presentations_today ?? 0}</b></div>
      <div class="stat tap" id="m-rev"><span class="muted small">💰 Заработано сегодня, сум ›</span><b>${fmtSum(st.revenue_today ?? 0)}</b></div>
      <div class="stat tap" id="m-sess"><span class="muted small">🚀 Запусков сегодня ›</span><b>${st.sessions_today ?? 0}</b></div>
      <div class="stat"><span class="muted small">🧾 Пополнений ждут</span><b>${st.topups_pending ?? 0}</b></div>
      <div class="stat"><span class="muted small">Прохождений за неделю</span><b>${st.attempts_week}</b></div>
    </div>
    <div class="tabs"><button class="${tab === "teachers" ? "on" : ""}" id="t1">Преподаватели</button>
      <button class="${tab === "pay" ? "on" : ""}" id="t3">💰 Оплата</button>
      <button class="${tab === "lib" ? "on" : ""}" id="t5">📚 Библиотека</button>
      <button class="${tab === "courses" ? "on" : ""}" id="t6">🎓 Курсы</button>
      <button class="${tab === "cast" ? "on" : ""}" id="t4">📢 Рассылка</button>
      <button class="${tab === "log" ? "on" : ""}" id="t2">Журнал</button></div>
    <div id="body"></div>
  `);
  on("#t1", "click", () => go(adminScreen, { tab: "teachers" }, true));
  on("#t2", "click", () => go(adminScreen, { tab: "log" }, true));
  on("#t3", "click", () => go(adminScreen, { tab: "pay" }, true));
  on("#t4", "click", () => go(adminScreen, { tab: "cast" }, true));
  on("#t5", "click", () => go(adminScreen, { tab: "lib" }, true));
  on("#t6", "click", () => go(adminScreen, { tab: "courses" }, true));
  on("#m-users", "click", () => go(adminMetricScreen, { metric: "users" }));
  on("#m-tests", "click", () => go(adminMetricScreen, { metric: "tests" }));
  on("#m-pres", "click", () => go(adminMetricScreen, { metric: "presentations" }));
  on("#m-rev", "click", () => go(adminMetricScreen, { metric: "revenue" }));
  on("#m-sess", "click", () => go(adminMetricScreen, { metric: "sessions" }));
  const body = document.getElementById("body");
  if (tab === "pay") { await paymentsTab(body); return; }
  if (tab === "lib") { await libraryTab(body); return; }
  if (tab === "courses") { await coursesTab(body); return; }
  if (tab === "cast") { broadcastTab(body); return; }
  if (tab === "log") {
    const log = await api("/api/admin/log");
    body.innerHTML = log.length ? log.map(x => `
      <div class="card small"><div class="row"><b>${esc(x.target)}</b><span class="muted">${fmtDate(x.at)}</span></div>
      <div>${esc(x.action)} <span class="muted">· ${esc(x.admin)}</span></div></div>`).join("") : `<div class="card muted">Пока пусто.</div>`;
    return;
  }
  body.innerHTML = `<input class="search" id="q" placeholder="Поиск: ФИО, @username, вуз, ID"><div id="list" class="muted">Загрузка…</div>`;
  const statusBadge = t => t.blocked ? `<span class="badge danger">заблокирован</span>`
    : t.status === "pending" ? `<span class="badge warn">заявка</span>`
    : t.status === "rejected" ? `<span class="badge">отклонён</span>`
    : t.plan === "pro" ? `<span class="badge pro">Pro</span>` : `<span class="badge">free</span>`;
  async function load(q) {
    let list;
    try { list = await api("/api/admin/teachers?q=" + encodeURIComponent(q || "")); } catch (e) { return toast(e.message); }
    const el = document.getElementById("list");
    if (!el) return;
    el.className = "";
    el.innerHTML = list.length ? list.map(t => `
      <div class="item" data-id="${t.id}">
        <div class="grow"><div>${esc(t.name || "без имени")}</div>
          <div class="muted small">${esc(t.info || "")}${t.kafedra ? " · " + esc(t.kafedra) : ""}${t.username ? " · @" + esc(t.username) : ""}</div>
          <div class="muted small">тестов ${t.tests} · запусков ${t.sessions} · прохождений ${t.attempts}</div></div>
        ${statusBadge(t)}
      </div>`).join("") : `<div class="card muted">Никого не найдено.</div>`;
    onAll("#list .item", "click", it => go(adminTeacherScreen, { t: list.find(x => x.id === +it.dataset.id) }));
  }
  let tmr;
  document.getElementById("q").addEventListener("input", e => { clearTimeout(tmr); tmr = setTimeout(() => load(e.target.value), 300); });
  load("");
}

const METRIC_META = {
  users: { title: "👥 Пользователи", today: "Сегодня добавилось", unit: "", fmt: n => String(n), hint: "Сколько новых пользователей появлялось в каждый день." },
  revenue: { title: "💰 Заработано", today: "Сегодня заработано", unit: " сум", fmt: n => fmtSum(n), hint: "Сумма подтверждённых пополнений по дню их подтверждения." },
  presentations: { title: "🖥 Презентации", today: "Сегодня создано", unit: "", fmt: n => String(n), hint: "Сколько презентаций создано в каждый день. Факты записываются с момента обновления — более ранние дни могут быть пустыми." },
  tests: { title: "📝 Тесты", today: "Сегодня создано", unit: "", fmt: n => String(n), hint: "Сколько тестов создано в каждый день." },
  sessions: { title: "🚀 Запуски тестов", today: "Сегодня запусков", unit: "", fmt: n => String(n), hint: "Сколько раз преподаватели запускали тесты в каждый день." },
};

async function adminMetricScreen({ metric }) {
  const meta = METRIC_META[metric];
  if (!meta) return toast("Неизвестная метрика");
  render(`<h1>${meta.title}</h1><div class="muted">Загрузка… <span class="spin"></span></div>`);
  let d;
  try { d = await api(`/api/admin/stats/daily?metric=${metric}&days=30`); } catch (e) { return toast(e.message); }
  const max = Math.max(1, ...d.series.map(x => x.value));
  const rows = d.series.slice().reverse().map(x => {
    const pct = Math.round(x.value * 100 / max);
    return `<div class="daystat">
      <div class="drow"><span class="muted">${fmtDay(x.date)}</span><b>${meta.fmt(x.value)}${x.value ? meta.unit : ""}</b></div>
      <div class="bar"><span style="width:${pct}%"></span></div>
    </div>`;
  }).join("");
  const allTime = (d.all_time != null)
    ? `<div class="stat"><span class="muted small">Всего за всё время</span><b>${meta.fmt(d.all_time)}${meta.unit}</b></div>`
    : "";
  render(`
    <h1>${meta.title}</h1>
    <div class="stats">
      <div class="stat"><span class="muted small">${meta.today}</span><b>${meta.fmt(d.today)}${meta.unit}</b></div>
      <div class="stat"><span class="muted small">За 30 дней</span><b>${meta.fmt(d.total)}${meta.unit}</b></div>
      ${allTime}
    </div>
    <h2>По дням</h2>
    <div class="daylist">${rows}</div>
    <p class="muted small">${meta.hint} День — по местному времени.</p>
  `);
}

function broadcastTab(body) {
  body.innerHTML = `
    <div class="card">
      <h2 style="margin-top:0">📢 Рассылка сообщений</h2>
      <label>Текст сообщения</label>
      <textarea id="msg" rows="5" placeholder="Напишите сообщение…"></textarea>
      <button class="btn" id="toteachers">👨‍🏫 Отправить преподавателям</button>
      <button class="btn secondary" id="tostudents">🎓 Отправить студентам</button>
      <button class="link" id="toall" style="display:block;margin:10px auto 0">Отправить всем</button>
      <p class="muted small">Сообщение придёт каждому в личный чат с ботом. Обычный текст, до 4000 символов.</p>
    </div>
  `;
  const send = async (audience, label) => {
    const text = document.getElementById("msg").value.trim();
    if (!text) return toast("Введите текст сообщения");
    if (!confirm(`Отправить сообщение ${label}?`)) return;
    try {
      const r = await api("/api/admin/broadcast", { json: { audience, text } });
      toast(`Рассылка запущена: ${r.queued} чел. Отчёт придёт в бот.`); haptic("success");
    } catch (e) { toast(e.message); }
  };
  on("#toteachers", "click", () => send("teachers", "всем преподавателям"));
  on("#tostudents", "click", () => send("students", "всем студентам"));
  on("#toall", "click", () => send("all", "всем пользователям"));
}

async function paymentsTab(body) {
  body.innerHTML = `<div class="muted">Загрузка…</div>`;
  let cfg, topups;
  try {
    cfg = await api("/api/admin/settings");
    topups = await api("/api/admin/topups?status=pending");
  } catch (e) { return toast(e.message); }
  body.innerHTML = `
    <div class="card">
      <h2 style="margin-top:0">Цены и карта</h2>
      <label>Цена презентации (сум)</label>
      <input id="pp" type="number" min="0" value="${cfg.price_presentation}">
      <label>Цена теста (сум)</label>
      <input id="pt" type="number" min="0" value="${cfg.price_test}">
      <label>Цена реферата (сум)</label>
      <input id="pr" type="number" min="0" value="${cfg.price_referat ?? 5000}">
      <label>Цена песни (сум) — платят все</label>
      <input id="psg" type="number" min="0" value="${cfg.price_song ?? 15000}">
      <label>Номер карты</label>
      <input id="card" value="${esc(cfg.card_number)}">
      <label>Владелец карты</label>
      <input id="holder" value="${esc(cfg.card_holder)}">
      <label>Суммы пополнения (через запятую)</label>
      <input id="amts" value="${esc(cfg.topup_amounts)}">
      <label>🎁 Бонус новому пользователю (сум)</label>
      <input id="wbonus" type="number" min="0" value="${cfg.welcome_bonus ?? 0}">
      <button class="btn" id="save">💾 Сохранить</button>
      <p class="muted small">Цены действуют только для студентов. Преподаватели создают тесты и презентации бесплатно.</p>
    </div>
    <div class="card">
      <h2 style="margin-top:0">💸 Начислить баланс</h2>
      <label>Сумма (сум)</label>
      <input id="gamt" type="number" min="1" value="5000">
      <label class="check"><input type="checkbox" id="gnotify" checked> Уведомить получателей в боте</label>
      <button class="btn" id="gstudents">🎓 Начислить всем студентам</button>
      <button class="btn secondary" id="gall">Начислить всем</button>
      <p class="muted small">Сумма прибавится к текущему балансу каждого (заблокированные пропускаются).</p>
    </div>
    <h2>Заявки на пополнение</h2>
    <div id="tlist"></div>
  `;
  on("#save", "click", async () => {
    const payload = {
      price_presentation: +document.getElementById("pp").value || 0,
      price_test: +document.getElementById("pt").value || 0,
      price_referat: +document.getElementById("pr").value || 0,
      price_song: +document.getElementById("psg").value || 0,
      card_number: document.getElementById("card").value.trim(),
      card_holder: document.getElementById("holder").value.trim(),
      topup_amounts: document.getElementById("amts").value.trim(),
      welcome_bonus: +document.getElementById("wbonus").value || 0,
    };
    try { await api("/api/admin/settings", { json: payload }); toast("Сохранено ✅"); haptic("success"); }
    catch (e) { toast(e.message); }
  });
  const grant = async (audience, label) => {
    const amount = +document.getElementById("gamt").value || 0;
    const notify = document.getElementById("gnotify").checked;
    if (amount < 1) return toast("Введите сумму");
    if (!confirm(`Начислить ${fmtSum(amount)} сум ${label}?`)) return;
    try {
      const r = await api("/api/admin/grant", { json: { audience, amount, notify } });
      toast(`Начислено ${r.granted} чел. по ${fmtSum(r.amount)} сум`); haptic("success");
    } catch (e) { toast(e.message); }
  };
  on("#gstudents", "click", () => grant("students", "всем студентам"));
  on("#gall", "click", () => grant("all", "всем пользователям"));
  const tlist = document.getElementById("tlist");
  function renderTopups(list) {
    tlist.innerHTML = list.length ? list.map(x => `
      <div class="card small" data-id="${x.id}">
        <div class="row"><b>${esc(x.name)}</b><span class="muted">${fmtDate(x.created_at)}</span></div>
        <div class="row" style="margin-top:6px;align-items:center">
          <span><b>${fmtSum(x.amount)}</b> сум</span>
          <span><button class="mini ok" data-ok="${x.id}">✅ Зачислить</button>
          <button class="mini no" data-no="${x.id}">❌</button></span>
        </div>
      </div>`).join("") : `<div class="card muted">Нет заявок, ожидающих подтверждения. Их также можно подтверждать прямо в чате бота.</div>`;
    onAll("[data-ok]", "click", e => decide(e.dataset.ok, true));
    onAll("[data-no]", "click", e => decide(e.dataset.no, false));
  }
  async function decide(id, approve) {
    if (!confirm(approve ? "Подтвердить оплату и зачислить баланс?" : "Отклонить заявку?")) return;
    try {
      await api(`/api/admin/topups/${id}/decide`, { json: { approve } });
      toast(approve ? "Зачислено ✅" : "Отклонено"); haptic("success");
      topups = await api("/api/admin/topups?status=pending");
      renderTopups(topups);
    } catch (e) { toast(e.message); }
  }
  renderTopups(topups);
}

async function libraryTab(body) {
  body.innerHTML = `<div class="muted">Загрузка…</div>`;
  let pending, subjects;
  try {
    pending = await api("/api/admin/library/pending");
    subjects = await api("/api/library/subjects");
  } catch (e) { return toast(e.message); }
  body.innerHTML = `
    <div class="card">
      <h2 style="margin-top:0">📚 Массовая загрузка книг</h2>
      <p class="muted small" style="margin:0 0 8px">Выберите сразу несколько файлов (.pdf, .docx, .txt) — ИИ сам разложит их по предметам. Отчёт придёт в бот, затем подтвердите материалы ниже.</p>
      <input id="bulkfiles" type="file" accept=".pdf,.docx,.txt" multiple>
      <button class="btn" id="bulkgo" style="margin-top:8px">⬆️ Загрузить пачкой</button>
    </div>
    <h2>На модерации (${pending.length})</h2>
    <div id="pend"></div>
    <div class="card">
      <h2 style="margin-top:0">Предметы библиотеки</h2>
      <div id="subs"></div>
      <label>Новый предмет</label>
      <div class="row" style="align-items:center"><input id="newsub" placeholder="Название предмета"><button class="mini ok" id="addsub" style="white-space:nowrap">➕ Добавить</button></div>
    </div>
  `;
  function renderPending(list) {
    const el = document.getElementById("pend");
    el.innerHTML = list.length ? list.map(d => `
      <div class="card small" data-id="${d.id}">
        <div class="row"><b>${esc(d.title)}</b><span class="muted">${fmtDate(d.created_at)}</span></div>
        <div class="muted small">${esc(d.subject)}${d.by ? " · " + esc(d.by) : ""} · ${esc(d.filename)}</div>
        <div class="row" style="margin-top:8px;align-items:center">
          <button class="mini" data-dl="${d.id}">⬇️ Файл</button>
          <span><button class="mini ok" data-ok="${d.id}">✅ Одобрить</button><button class="mini no" data-no="${d.id}">❌</button></span>
        </div>
      </div>`).join("") : `<div class="card muted">Нет материалов на модерации.</div>`;
    onAll("[data-dl]", "click", e => dl(e.dataset.dl));
    onAll("[data-ok]", "click", e => decide(e.dataset.ok, true));
    onAll("[data-no]", "click", e => decide(e.dataset.no, false));
  }
  async function dl(id) {
    try { await api(`/api/admin/library/docs/${id}/download`, { method: "POST" }); toast("Файл отправлен в бот"); }
    catch (e) { toast(e.message); }
  }
  async function decide(id, approve) {
    if (!confirm(approve ? "Одобрить материал? Он станет виден студентам." : "Отклонить материал?")) return;
    try {
      await api(`/api/admin/library/docs/${id}/decide`, { json: { approve } });
      toast(approve ? "Одобрено ✅" : "Отклонено"); haptic("success");
      pending = await api("/api/admin/library/pending");
      document.querySelector("#body h2").textContent = `На модерации (${pending.length})`;
      renderPending(pending);
    } catch (e) { toast(e.message); }
  }
  function renderSubs(list) {
    const el = document.getElementById("subs");
    el.innerHTML = list.map(s => `
      <div class="row sub" data-id="${s.id}" style="align-items:center">
        <span class="grow">${esc(s.name)} <span class="muted small">(${s.docs})</span></span>
        <button class="mini" data-ren="${s.id}">✏️</button><button class="mini no" data-del="${s.id}">🗑</button>
      </div>`).join("");
    onAll("[data-ren]", "click", e => ren(e.dataset.ren, list));
    onAll("[data-del]", "click", e => del(e.dataset.del));
  }
  async function reloadSubs() { subjects = await api("/api/library/subjects"); renderSubs(subjects); }
  async function ren(id, list) {
    const s = list.find(x => x.id === +id);
    const name = prompt("Новое название предмета:", s ? s.name : "");
    if (!name) return;
    try { await api(`/api/admin/library/subjects/${id}`, { method: "PATCH", json: { name } }); toast("Готово"); reloadSubs(); }
    catch (e) { toast(e.message); }
  }
  async function del(id) {
    if (!confirm("Удалить предмет? (можно только если в нём нет материалов)")) return;
    try { await api(`/api/admin/library/subjects/${id}`, { method: "DELETE" }); toast("Удалено"); reloadSubs(); }
    catch (e) { toast(e.message); }
  }
  on("#addsub", "click", async () => {
    const name = document.getElementById("newsub").value.trim();
    if (!name) return toast("Введите название");
    try { await api("/api/admin/library/subjects", { json: { name } }); document.getElementById("newsub").value = ""; toast("Добавлено"); reloadSubs(); }
    catch (e) { toast(e.message); }
  });
  on("#bulkgo", "click", async () => {
    const files = document.getElementById("bulkfiles").files;
    if (!files || !files.length) return toast("Выберите файлы");
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    const btn = document.getElementById("bulkgo"); btn.disabled = true; btn.textContent = "Загрузка…";
    try {
      const r = await api("/api/admin/library/bulk_upload", { body: fd, method: "POST" });
      haptic("success"); toast(`Принято ${r.count}. Разложу по предметам — отчёт придёт в бот.`);
      document.getElementById("bulkfiles").value = "";
    } catch (e) { toast(e.message); }
    btn.disabled = false; btn.textContent = "⬆️ Загрузить пачкой";
  });
  renderPending(pending);
  renderSubs(subjects);
}

// ---- админ: курсы из силлабуса
async function coursesTab(body) {
  body.innerHTML = `<div class="muted">Загрузка…</div>`;
  let courses, subjects;
  try {
    courses = await api("/api/admin/courses");
    subjects = await api("/api/library/subjects");
  } catch (e) { return toast(e.message); }
  let lang = "ru";
  body.innerHTML = `
    <div class="card">
      <h2 style="margin-top:0">🎓 Создать курс из силлабуса</h2>
      <p class="muted small" style="margin:0 0 8px">Выберите предмет и курс, затем загрузите силлабус (.pdf / .docx / .txt). ИИ вытащит темы, вы подтвердите — он напишет теорию и тесты <b>по книгам выбранного предмета</b>.</p>
      <label>Предмет</label>
      <select id="csubj"><option value="0">— любой (по всей библиотеке) —</option>${subjects.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join("")}</select>
      <div class="row" style="gap:10px">
        <div class="grow"><label>Курс</label><select id="cyear"><option value="0">—</option>${[1, 2, 3, 4, 5, 6].map(y => `<option value="${y}">${y} курс</option>`).join("")}</select></div>
        <div class="grow"><label>Семестр</label><select id="csem"><option value="0">—</option><option value="1">1</option><option value="2">2</option></select></div>
      </div>
      <label>Язык курса</label>
      <div class="langpick" id="clang">
        ${["ru", "uz", "en"].map(l => `<button class="lbtn ${l === "ru" ? "on" : ""}" data-l="${l}">${l === "ru" ? "🇷🇺 Рус" : l === "uz" ? "🇺🇿 Ўзб" : "🇬🇧 Eng"}</button>`).join("")}
      </div>
      <label style="display:block;margin-top:8px">Силлабус</label>
      <input id="syl" type="file" accept=".pdf,.docx,.txt">
      <button class="btn" id="parse" style="margin-top:8px">🔍 Разобрать силлабус</button>
      <div id="draft"></div>
    </div>
    <h2>Курсы (${courses.length})</h2>
    <div id="clist"></div>
  `;
  onAll("#clang .lbtn", "click", el => { lang = el.dataset.l; $app.querySelectorAll("#clang .lbtn").forEach(b => b.classList.toggle("on", b === el)); });
  function renderList(list) {
    const el = document.getElementById("clist");
    el.innerHTML = list.length ? list.map(c => `
      <div class="card small"><div class="row"><b>${esc(c.title)}</b>
        <span class="badge ${c.status === "ready" ? "ok" : "warn"}">${c.status === "ready" ? "готов" : "сборка"} ${c.ready}/${c.topics}</span></div>
        <div class="muted small">${esc(c.info || "")}</div>
        <button class="link danger" data-del="${c.id}" style="margin-top:4px">🗑 Удалить</button>
      </div>`).join("") : `<div class="card muted">Пока нет курсов.</div>`;
    onAll("[data-del]", "click", async e => {
      if (!confirm("Удалить курс со всеми темами?")) return;
      try { await api(`/api/admin/courses/${e.dataset.del}`, { method: "DELETE" }); toast("Удалено"); coursesTab(body); }
      catch (err) { toast(err.message); }
    });
  }
  on("#parse", "click", async () => {
    const f = document.getElementById("syl").files[0];
    if (!f) return toast("Выберите файл силлабуса");
    const btn = document.getElementById("parse"); btn.disabled = true; btn.textContent = "Разбираю…";
    try {
      const fd = new FormData(); fd.append("file", f); fd.append("lang", lang);
      showDraft(await api("/api/admin/course/parse", { body: fd, method: "POST" }));
    } catch (e) { toast(e.message); }
    btn.disabled = false; btn.textContent = "🔍 Разобрать силлабус";
  });
  function showDraft(d) {
    const subjSel = document.getElementById("csubj");
    const subjId = +subjSel.value;
    const subjName = subjId ? subjSel.selectedOptions[0].textContent : "";
    const year = +document.getElementById("cyear").value;
    const sem = +document.getElementById("csem").value;
    const defTitle = subjName || d.title || "";
    const defInfo = year ? `${year} курс${sem ? `, ${sem} семестр` : ""}` : (d.info || "");
    const el = document.getElementById("draft");
    el.innerHTML = `
      <hr style="border:none;border-top:1px solid var(--bg2);margin:12px 0">
      <label>Название предмета</label><input id="ctitle" value="${esc(defTitle)}">
      <label>Курс / семестр</label><input id="cinfo" value="${esc(defInfo)}">
      <label>Темы (по одной в строке) — ${(d.topics || []).length}</label>
      <textarea id="ctopics" rows="10">${(d.topics || []).map(esc).join("\n")}</textarea>
      <button class="btn" id="create" style="margin-top:8px">🚀 Создать курс</button>
      <p class="muted small" style="margin-top:4px">${subjId ? "Теория и тесты — строго по книгам этого предмета. " : ""}ИИ соберёт их в фоне, отчёт придёт в бот.</p>`;
    on("#create", "click", async () => {
      const title = document.getElementById("ctitle").value.trim();
      const info = document.getElementById("cinfo").value.trim();
      const topics = document.getElementById("ctopics").value.split("\n").map(s => s.trim()).filter(Boolean);
      if (!topics.length) return toast("Нет тем");
      const btn = document.getElementById("create"); btn.disabled = true; btn.textContent = "Создаю…";
      try {
        const r = await api("/api/admin/course/create", {
          json: { title, info, lang, topics, subject_id: subjId || null, year, semester: sem },
        });
        haptic("success"); toast(`Курс создаётся: ${r.topics} тем. Отчёт придёт в бот.`);
        coursesTab(body);
      } catch (e) { toast(e.message); btn.disabled = false; btn.textContent = "🚀 Создать курс"; }
    });
  }
  renderList(courses);
}

function adminTeacherScreen({ t }) {
  const act = async (path, body, msg) => {
    try { await api(`/api/admin/teachers/${t.id}/${path}`, { json: body }); toast(msg); back(); }
    catch (e) { toast(e.message); }
  };
  render(`
    <h1>${esc(t.name || "без имени")}</h1>
    <div class="card">
      <div class="kv"><span>Telegram ID</span><span>${t.id}</span></div>
      ${t.username ? `<div class="kv"><span>Username</span><span>@${esc(t.username)}</span></div>` : ""}
      <div class="kv"><span>Вуз</span><span>${esc(t.info || "—")}</span></div>
      <div class="kv"><span>Кафедра</span><span>${esc(t.kafedra || "—")}</span></div>
      <div class="kv"><span>Статус</span><span>${{ pending: "заявка", teacher: "преподаватель" }[t.status] || t.status}${t.blocked ? ", заблокирован" : ""}</span></div>
      <div class="kv"><span>Тариф</span><span>${t.is_pro_plus ? "💎 Pro+ до " + new Date(t.proplus_until + "Z").toLocaleDateString("ru-RU") : (t.plan === "pro" ? "Pro до " + new Date(t.pro_until + "Z").toLocaleDateString("ru-RU") : "бесплатный")}</span></div>
      <div class="kv"><span>Тестов / запусков</span><span>${t.tests} / ${t.sessions}</span></div>
      <div class="kv"><span>Прохождений студентами</span><span>${t.attempts}</span></div>
      <div class="kv"><span>Последний запуск</span><span>${t.last_session ? fmtDate(t.last_session) : "—"}</span></div>
      <div class="kv"><span>Зарегистрирован</span><span>${fmtDate(t.created_at)}</span></div>
    </div>
    ${t.status === "pending" ? `<button class="btn" id="ok">✅ Одобрить заявку</button><button class="btn danger" id="no">Отклонить</button>` : ""}
    ${t.status === "teacher" ? `<button class="btn" id="enter">🛠 Открыть кабинет преподавателя</button>` : ""}
    ${t.status === "teacher" ? `<label>Выдать Pro (дней)</label><input id="days" type="number" value="30" min="1"><button class="btn secondary" id="pro">⭐ Выдать Pro</button>` : ""}
    ${t.plan === "pro" ? `<button class="btn secondary" id="unpro">✖️ Снять Pro</button>` : ""}
    <label>💎 Выдать Pro+ (дней)</label><input id="ppdays" type="number" value="30" min="1"><button class="btn secondary" id="proplus">💎 Выдать Pro+</button>
    ${t.is_pro_plus ? `<button class="btn secondary" id="unproplus">✖️ Снять Pro+</button>` : ""}
    ${t.status === "teacher" && !t.is_admin ? `<button class="btn danger" id="demote">🎓 Снять роль преподавателя</button>` : ""}
    ${t.is_admin ? "" : `<button class="btn ${t.blocked ? "secondary" : "danger"}" id="block">${t.blocked ? "Разблокировать" : "Заблокировать"}</button>`}
    ${t.username ? `<button class="btn secondary" id="chat">✉️ Написать в Telegram</button>` : ""}
  `);
  on("#ok", "click", () => act("decide", { approve: true }, "Заявка одобрена"));
  on("#no", "click", () => act("decide", { approve: false }, "Заявка отклонена"));
  on("#pro", "click", () => act("pro", { days: +document.getElementById("days").value }, "Pro выдан"));
  on("#unpro", "click", () => { if (confirm("Снять Pro-подписку? Пользователь перейдёт на бесплатный тариф.")) act("unpro", {}, "Pro снят"); });
  on("#proplus", "click", () => act("proplus", { days: +document.getElementById("ppdays").value }, "Pro+ выдан"));
  on("#unproplus", "click", () => { if (confirm("Снять Pro+?")) act("unproplus", {}, "Pro+ снят"); });
  on("#demote", "click", () => {
    if (confirm(`Снять роль преподавателя у «${t.name || t.id}»? Он станет обычным пользователем (Pro тоже снимется). Тесты и история сохранятся, роль можно вернуть при новой заявке.`))
      act("remove", {}, "Роль преподавателя снята");
  });
  on("#block", "click", () => { if (confirm(t.blocked ? "Разблокировать?" : "Заблокировать преподавателя?")) act("block", { blocked: !t.blocked }, "Готово"); });
  on("#chat", "click", () => { const u = "https://t.me/" + t.username; tg ? tg.openTelegramLink(u) : window.open(u); });
  on("#enter", "click", async () => {
    try {
      await api(`/api/admin/teachers/${t.id}/enter`, { method: "POST" });
      setActAs(t.id);
      ME = await api("/api/me"); updateActBar();
      navStack = []; go(teacherHome);
    } catch (e) { setActAs(null); toast(e.message); }
  });
}

/* ---------------------------------------------------------------- подпись */
(function () {
  const ig = document.getElementById("iglink");
  if (ig) ig.addEventListener("click", e => {
    e.preventDefault();
    const u = "https://instagram.com/aat.abdurazzakov";
    try { tg ? tg.openLink(u) : window.open(u, "_blank"); } catch (_) { window.open(u, "_blank"); }
  });
})();

/* ------------------------------------------------- Презентация (форма в приложении) */
const PRESF = {
  ru: { title: "Презентация", topic: "Тема", topic_ph: "Например: Анатомия сердца",
        lang: "Язык презентации", slides: "Сколько слайдов (до 20)", group: "Группа (необязательно)",
        group_ph: "Напр. 201-С", pick_books: "📚 Выбрать книги из библиотеки",
        subject: "Предмет", subject_pick: "— выберите предмет —",
        books_pro: "Выбор книг для презентации доступен в Pro+.", create: "Создать презентацию",
        deliver: "Готовый файл придёт в чат с ботом (это займёт немного времени).",
        need_topic: "Напишите тему", sending: "Отправляю…", done: "Готово", change: "Изменить",
        chosen: "Выбрано книг", pick_subject_first: "Сначала выберите предмет", nobooks: "В этом предмете пока нет книг.",
        queued: "⏳ Генерирую! Файл придёт в чат с ботом." },
  uz: { title: "Taqdimot", topic: "Mavzu", topic_ph: "Masalan: Yurak anatomiyasi",
        lang: "Taqdimot tili", slides: "Nechta slayd (20 gacha)", group: "Guruh (ixtiyoriy)",
        group_ph: "Masalan 201-S", pick_books: "📚 Kutubxonadan kitob tanlash",
        subject: "Fan", subject_pick: "— fanni tanlang —",
        books_pro: "Kitob tanlash Pro+ da mavjud.", create: "Taqdimot yaratish",
        deliver: "Tayyor fayl bot chatiga keladi (biroz vaqt oladi).",
        need_topic: "Mavzuni yozing", sending: "Yuborilmoqda…", done: "Tayyor", change: "O'zgartirish",
        chosen: "Tanlangan kitoblar", pick_subject_first: "Avval fanni tanlang", nobooks: "Bu fanda hali kitob yo'q.",
        queued: "⏳ Yaratyapman! Fayl bot chatiga keladi." },
  en: { title: "Presentation", topic: "Topic", topic_ph: "E.g. Heart anatomy",
        lang: "Presentation language", slides: "Number of slides (up to 20)", group: "Group (optional)",
        group_ph: "E.g. 201-C", pick_books: "📚 Pick library books",
        subject: "Subject", subject_pick: "— choose a subject —",
        books_pro: "Choosing books is available in Pro+.", create: "Create presentation",
        deliver: "The file will arrive in the bot chat (takes a little time).",
        need_topic: "Type the topic", sending: "Sending…", done: "Done", change: "Edit",
        chosen: "Books selected", pick_subject_first: "Choose a subject first", nobooks: "No books in this subject yet.",
        queued: "⏳ Generating! The file will arrive in the bot chat." },
};

async function presentationStudioScreen() {
  try { ME = await api("/api/me"); } catch (e) {}
  const P = PRESF[LANG] || PRESF.ru;
  const proplus = !!(ME.is_pro_plus || ME.is_admin);
  let allBooks = [], subjects = [];
  if (proplus) {
    try { allBooks = await api("/api/library/docs"); } catch (e) {}
    try { subjects = (await api("/api/library/subjects")).filter(s => s.docs > 0); } catch (e) {}
  }
  // состояние выбора книг: open — открыт ли выбор, subject — выбранный предмет, picked — {id: название}
  const bk = { open: false, subject: "", picked: {} };

  render(`
    ${langBar()}
    <h1>🖥 ${P.title}</h1>
    <div class="card">
      <label>${P.topic}</label>
      <input id="ptopic" placeholder="${P.topic_ph}">
      <label>${P.lang}</label>
      <div class="langpick">${["ru", "uz", "en"].map(l => `<button class="lbtn ${l === LANG ? "on" : ""}" data-l="${l}">${l.toUpperCase()}</button>`).join("")}</div>
      <label>${P.slides}</label>
      <input id="pslides" type="number" min="1" max="20" value="10">
      <label>${P.group}</label>
      <input id="pgroup" placeholder="${P.group_ph}">
      <div id="bookblock" style="margin-top:8px"></div>
      <button class="btn" id="pcreate">✨ ${P.create}</button>
      <p class="muted small">${P.deliver}</p>
    </div>
    <button class="link" id="pback">${t("back") || "Назад"}</button>
  `);
  let plang = LANG;
  onAll(".lbtn", "click", el => { plang = el.dataset.l; $app.querySelectorAll(".lbtn").forEach(x => x.classList.toggle("on", x === el)); });
  on("#pback", "click", () => back());

  function renderBooks() {
    const el = document.getElementById("bookblock");
    if (!el) return;
    if (!proplus) { el.innerHTML = `<div class="card muted small">🔒 ${P.books_pro}</div>`; return; }
    const ids = Object.keys(bk.picked);
    if (!bk.open) {  // свёрнуто: либо сводка выбранного, либо кнопка «Выбрать книги»
      el.innerHTML = ids.length
        ? `<div class="booksum"><span class="grow">📚 ${P.chosen}: <b>${ids.length}</b> — ${ids.map(id => esc(bk.picked[id])).join(", ")}</span><button class="link" id="bkedit">${P.change}</button></div>`
        : `<button class="btn secondary" id="bkopen">${P.pick_books}</button>`;
      on("#bkedit", "click", () => { bk.open = true; renderBooks(); });
      on("#bkopen", "click", () => { bk.open = true; renderBooks(); });
      return;
    }
    // раскрыто: сначала предмет, затем книги этого предмета
    el.innerHTML = `
      <label>${P.subject}</label>
      <select id="bksubj">
        <option value="">${P.subject_pick}</option>
        ${subjects.map(s => `<option value="${s.id}" ${String(s.id) === bk.subject ? "selected" : ""}>${esc(s.name)} (${s.docs})</option>`).join("")}
      </select>
      <div id="bklist" class="booksel" style="margin-top:6px"></div>
      <button class="btn" id="bkdone">✓ ${P.done} (${ids.length})</button>`;
    on("#bksubj", "change", e => { bk.subject = e.target.value; renderBookList(); });
    on("#bkdone", "click", () => { bk.open = false; renderBooks(); });
    renderBookList();
  }
  function renderBookList() {
    const list = document.getElementById("bklist");
    if (!list) return;
    if (!bk.subject) { list.innerHTML = `<p class="muted small">${P.pick_subject_first}</p>`; return; }
    const items = allBooks.filter(b => String(b.subject_id) === bk.subject);
    list.innerHTML = items.length
      ? items.map(b => `<label class="bchk"><input type="checkbox" value="${b.id}" ${bk.picked[b.id] ? "checked" : ""}><span class="grow">${esc(b.title)}</span></label>`).join("")
      : `<p class="muted small">${P.nobooks}</p>`;
    list.querySelectorAll("input").forEach(inp => inp.addEventListener("change", () => {
      const book = allBooks.find(b => String(b.id) === inp.value);
      if (inp.checked) bk.picked[inp.value] = (book && book.title) || inp.value;
      else delete bk.picked[inp.value];
      const d = document.getElementById("bkdone");
      if (d) d.textContent = `✓ ${P.done} (${Object.keys(bk.picked).length})`;
    }));
  }
  renderBooks();

  on("#pcreate", "click", async (e) => {
    const topic = document.getElementById("ptopic").value.trim();
    if (!topic) { toast(P.need_topic); return; }
    const slides = +document.getElementById("pslides").value || 10;
    const group = document.getElementById("pgroup").value.trim();
    const book_ids = Object.keys(bk.picked).map(Number);
    const b = e.currentTarget, old = b.textContent;
    b.disabled = true; b.textContent = P.sending;
    try {
      await api("/api/ai/presentation", { json: { topic, lang: plang, slides, group, book_ids } });
      toast(P.queued); haptic("success");
      setTimeout(() => back(), 900);
    } catch (err) { toast(err.message); b.disabled = false; b.textContent = old; }
  });
}

/* ---------------------------------------------------------------- ИИ-чат (Pro+) */
let _aichat = [];
function aiChatScreen() {
  if (!(ME.is_pro_plus || ME.is_admin)) {
    render(`<h1>💬 ${t("ai_assistant")}</h1><div class="card"><p>${t("ai_proplus_only")}</p></div>`);
    return;
  }
  _aichat = [];
  drawAiChat(false);
}
function drawAiChat(loading) {
  const rows = _aichat.map(m => m.role === "user"
    ? `<div class="chatrow you"><div class="bubble you">${esc(m.content)}</div></div>`
    : `<div class="chatrow ai"><div class="bubble ai">${esc(m.content).replace(/\n/g, "<br>")}</div>${m.sources && m.sources.length ? `<div class="muted small chsrc">📄 ${t("ai_src")}: ${m.sources.map(esc).join(" · ")}</div>` : ""}</div>`
  ).join("");
  render(`
    <h1>💬 ${t("ai_assistant")}</h1>
    <p class="muted small" style="margin:-4px 0 10px">${t("ai_hint")}</p>
    <div id="chatbox" class="chatbox">${rows || `<div class="muted small" style="padding:8px">${t("ai_start")}</div>`}${loading ? `<div class="chatrow ai"><div class="bubble ai muted">… <span class="spin"></span></div></div>` : ""}</div>
    <div class="chatinput"><textarea id="q" rows="2" placeholder="${t("ai_ph")}"></textarea><button class="btn" id="send" ${loading ? "disabled" : ""}>➤</button></div>
  `);
  const box = document.getElementById("chatbox"); if (box) box.scrollTop = box.scrollHeight;
  const send = async () => {
    if (loading) return;
    const ta = document.getElementById("q"); const txt = (ta && ta.value || "").trim();
    if (!txt) return;
    _aichat.push({ role: "user", content: txt });
    drawAiChat(true);
    try {
      const r = await api("/api/ai/chat", { json: { messages: _aichat.map(m => ({ role: m.role, content: m.content })), lang: LANG } });
      _aichat.push({ role: "assistant", content: r.answer || "—", sources: r.sources || [] });
    } catch (e) {
      _aichat.push({ role: "assistant", content: "❌ " + e.message, sources: [] });
    }
    drawAiChat(false);
  };
  on("#send", "click", send);
  const ta = document.getElementById("q");
  if (ta) ta.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
}

/* ================================================================ живой куиз (Kahoot) */

const QUIZ = {
  ru: {
    host_entry: "🎮 Куиз (как Kahoot)", join_entry: "🎮 Войти в куиз",
    create_title: "Новый куиз", topic_ph: "Тема (напр. «Анатомия: череп»)",
    count_label: "Сколько вопросов", seconds_label: "Секунд на вопрос", lang_label: "Язык вопросов",
    create_btn: "🚀 Создать игру", generating: "Perga придумывает вопросы…",
    pin_title: "Код игры", joined: "В игре", start_btn: "▶️ Начать игру", nobody: "Пока никто не зашёл — назови код",
    waiting_host: "Ждём, пока ведущий начнёт…", you_in: "Ты в игре!",
    q_of: "Вопрос {i} из {n}", answered_n: "Ответили", reveal_btn: "Показать ответ",
    pick: "Выбери ответ", answered_wait: "Ответ принят — ждём остальных", time_up: "Время вышло",
    correct_was: "Правильный ответ", next_btn: "Следующий вопрос →", finish_btn: "🏁 Завершить",
    leaderboard: "Таблица лидеров", place: "место", players_word: "игроков",
    correct_word: "Верно!", wrong_word: "Мимо", no_answer: "Не успел(а)",
    results_title: "🏆 Итоги", your_place: "Твоё место", of_n: "из {n}", home_btn: "На главную",
    end_host: "Игра окончена", join_title: "Войти в куиз", join_hint: "Введи код игры от преподавателя",
    join_btn: "Войти", score_word: "очков", pick_avatar: "Выбери аватар",
    mode_label: "Переход вопросов", mode_auto: "Авто", mode_manual: "Вручную", next_in: "Дальше через",
    games_entry: "Игры", games_title: "Игры", games_hint: "Выбери игру",
    quiz_name: "Куиз", quiz_desc: "Викторина как Kahoot: вопросы на скорость и таблица лидеров",
    mafia_name: "Мафия", mafia_desc: "Ролевая игра на логику: город против мафии",
    snake_name: "Змейка", snake_desc: "Классика на перемену: собирай яблоки, не влетай в стену и в себя",
    fight_name: "Файтинг", fight_desc: "Выбери бойца и дерись с компьютером: удары, блок, спецудар, KO",
    soon: "Скоро", in_dev: "В разработке — скоро добавим! 🔧",
  },
  uz: {
    host_entry: "🎮 Kuiz (Kahoot kabi)", join_entry: "🎮 Kuizga kirish",
    create_title: "Yangi kuiz", topic_ph: "Mavzu (masalan «Anatomiya: bosh suyagi»)",
    count_label: "Nechta savol", seconds_label: "Har savolga soniya", lang_label: "Savollar tili",
    create_btn: "🚀 O'yin yaratish", generating: "Perga savollar o'ylab topmoqda…",
    pin_title: "O'yin kodi", joined: "O'yinda", start_btn: "▶️ Boshlash", nobody: "Hali hech kim kirmadi — kodni ayting",
    waiting_host: "Boshlovchi boshlashini kutyapmiz…", you_in: "O'yindasiz!",
    q_of: "{n} dan {i}-savol", answered_n: "Javob berdi", reveal_btn: "Javobni ko'rsatish",
    pick: "Javobni tanlang", answered_wait: "Javob qabul qilindi — kutamiz", time_up: "Vaqt tugadi",
    correct_was: "To'g'ri javob", next_btn: "Keyingi savol →", finish_btn: "🏁 Yakunlash",
    leaderboard: "Peshqadamlar", place: "o'rin", players_word: "o'yinchi",
    correct_word: "To'g'ri!", wrong_word: "Xato", no_answer: "Ulgurmadingiz",
    results_title: "🏆 Natijalar", your_place: "Sizning o'rningiz", of_n: "{n} dan", home_btn: "Bosh sahifa",
    end_host: "O'yin tugadi", join_title: "Kuizga kirish", join_hint: "O'qituvchidan olgan kodni kiriting",
    join_btn: "Kirish", score_word: "ball", pick_avatar: "Avatar tanlang",
    mode_label: "Savollar o'tishi", mode_auto: "Avto", mode_manual: "Qo'lda", next_in: "Keyingisi",
    games_entry: "O'yinlar", games_title: "O'yinlar", games_hint: "O'yinni tanlang",
    quiz_name: "Kuiz", quiz_desc: "Kahoot kabi viktorina: tezlikka savollar va peshqadamlar",
    mafia_name: "Mafiya", mafia_desc: "Mantiqqa mo'ljallangan rolli o'yin: shahar mafiyaga qarshi",
    snake_name: "Ilon", snake_desc: "Tanaffusga klassika: olma yig', devorga va o'zingga urilma",
    fight_name: "Jang", fight_desc: "Jangchi tanla va kompyuter bilan jang qil: zarba, blok, super zarba, KO",
    soon: "Tez orada", in_dev: "Ishlanmoqda — tez orada qo'shamiz! 🔧",
  },
  en: {
    host_entry: "🎮 Quiz (Kahoot-style)", join_entry: "🎮 Join a quiz",
    create_title: "New quiz", topic_ph: "Topic (e.g. “Anatomy: the skull”)",
    count_label: "Questions", seconds_label: "Seconds per question", lang_label: "Questions language",
    create_btn: "🚀 Create game", generating: "Perga is writing questions…",
    pin_title: "Game PIN", joined: "In the game", start_btn: "▶️ Start game", nobody: "No one has joined yet — read out the PIN",
    waiting_host: "Waiting for the host to start…", you_in: "You're in!",
    q_of: "Question {i} of {n}", answered_n: "Answered", reveal_btn: "Show answer",
    pick: "Pick an answer", answered_wait: "Answer locked in — waiting for others", time_up: "Time's up",
    correct_was: "Correct answer", next_btn: "Next question →", finish_btn: "🏁 Finish",
    leaderboard: "Leaderboard", place: "place", players_word: "players",
    correct_word: "Correct!", wrong_word: "Wrong", no_answer: "No answer",
    results_title: "🏆 Results", your_place: "Your place", of_n: "of {n}", home_btn: "Home",
    end_host: "Game over", join_title: "Join a quiz", join_hint: "Enter the game PIN from your teacher",
    join_btn: "Join", score_word: "pts", pick_avatar: "Pick your avatar",
    mode_label: "Question transitions", mode_auto: "Auto", mode_manual: "Manual", next_in: "Next in",
    games_entry: "Games", games_title: "Games", games_hint: "Pick a game",
    quiz_name: "Quiz", quiz_desc: "Kahoot-style quiz: fast answers and a leaderboard",
    mafia_name: "Mafia", mafia_desc: "Social deduction game: town vs. mafia",
    snake_name: "Snake", snake_desc: "Classic break-time game: eat apples, don't hit walls or yourself",
    fight_name: "Fighter", fight_desc: "Pick a fighter and battle the computer: punch, kick, block, special, KO",
    soon: "Soon", in_dev: "In development — coming soon! 🔧",
  },
};
const QUIZ_REVEAL_MS = 10000;  // сколько показывать правильный ответ до авто-перехода
function quizT() { return QUIZ[LANG] || QUIZ.ru; }
const QUIZ_SHAPE = ["▲", "◆", "●", "■", "★", "✚"];
const QUIZ_AVATARS = ["😎", "🦊", "🐱", "🐼", "🐸", "🦁", "🐯", "🐵", "🐨", "🐰",
  "🦄", "🐲", "🐙", "🦖", "🐬", "🦅", "🐝", "🌟", "🔥", "🚀",
  "🎧", "⚽", "🎮", "🍕", "🦈", "🐧", "👑", "🤖"];

function quizOptions(options, { correct = null, chosen = null, counts = null, tappable = false } = {}) {
  return `<div class="qopts">` + options.map((o, i) => {
    let cls = "qopt c" + i;
    if (correct !== null) cls += i === correct ? " correct" : " dim";
    if (chosen === i) cls += " chosen";
    const cnt = counts ? `<span class="qcount">${counts[i] || 0}</span>` : "";
    return `<button class="${cls}" ${tappable ? `data-opt="${i}"` : "disabled"}>
      <span class="qshape">${QUIZ_SHAPE[i] || "●"}</span><span class="qtext">${esc(o)}</span>${cnt}</button>`;
  }).join("") + `</div>`;
}

// ---- хаб «Игры»: список игр (куиз, мафия…)
function gamesScreen() {
  const Q = quizT();
  const isHost = ME.is_teacher || ME.is_admin;
  const tile = (id, emoji, name, desc, ready) => `
    <div class="item gtile" id="g-${id}">
      <span class="ico">${emoji}</span>
      <div class="grow"><div><b>${name}</b>${ready ? "" : ` <span class="badge">${Q.soon}</span>`}</div>
        <div class="muted small">${desc}</div></div>
      <span class="muted">›</span>
    </div>`;
  render(`
    ${langBar()}
    <h1>${Q.games_title}</h1>
    <p class="muted small" style="margin:-6px 0 12px">${Q.games_hint}</p>
    ${tile("quiz", "🎯", Q.quiz_name, Q.quiz_desc, true)}
    ${tile("mafia", "🕵️", Q.mafia_name, Q.mafia_desc, true)}
    ${tile("snake", "🐍", Q.snake_name, Q.snake_desc, true)}
    ${tile("fight", "🥊", Q.fight_name, Q.fight_desc, true)}
  `);
  showTabs("games");
  on("#g-quiz", "click", () => go(isHost ? quizCreateScreen : quizJoinScreen));
  on("#g-mafia", "click", () => go(mafiaMenuScreen));
  on("#g-snake", "click", () => go(snakeScreen));
  on("#g-fight", "click", () => go(fightSelectScreen));
}

// ---- заглушка игры «в разработке»
function gameSoonScreen({ emoji, name, desc }) {
  const Q = quizT();
  render(`
    <div class="center">
      <div class="qbig">${emoji}</div>
      <h1>${name}</h1>
      <p class="muted">${desc}</p>
      <div class="card" style="margin-top:16px">${Q.in_dev}</div>
    </div>
  `);
}

// ---- Змейка: соло-игра на перемену (canvas, без сервера; рекорд — локально)
function snakeScreen() {
  const SNK = {
    ru: { title: "Змейка", score: "Счёт", best: "Рекорд", start: "Свайпай по полю или жми стрелки",
      over: "Игра окончена", go_btn: "▶️ Старт", again: "🔄 Заново" },
    uz: { title: "Ilon", score: "Hisob", best: "Rekord", start: "Maydonni suring yoki strelka bosing",
      over: "O'yin tugadi", go_btn: "▶️ Start", again: "🔄 Qayta" },
    en: { title: "Snake", score: "Score", best: "Best", start: "Swipe the board or use arrows",
      over: "Game over", go_btn: "▶️ Start", again: "🔄 Restart" },
  };
  const L = SNK[LANG] || SNK.ru;
  const COLS = 16, ROWS = 16;
  let best = 0; try { best = +localStorage.getItem("snake_best") || 0; } catch (e) {}
  render(`
    ${langBar()}
    <h1>🐍 ${L.title}</h1>
    <div class="sk-top">
      <span class="sk-chip">${L.score}: <b id="sk-score">0</b></span>
      <span class="sk-chip">${L.best}: <b id="sk-best">${best}</b></span>
      <button class="sk-pause" id="sk-pause" aria-label="pause">⏸</button>
    </div>
    <div class="sk-board">
      <canvas id="sk"></canvas>
      <div class="sk-over on" id="sk-over">
        <div class="sk-over-t" id="sk-msg">${L.start}</div>
        <div class="sk-over-s" id="sk-sub"></div>
        <button class="btn" id="sk-go">${L.go_btn}</button>
      </div>
    </div>
    <div class="sk-pad">
      <button class="sk-b" data-d="up">▲</button>
      <div class="sk-row">
        <button class="sk-b" data-d="left">◀</button>
        <button class="sk-b" data-d="down">▼</button>
        <button class="sk-b" data-d="right">▶</button>
      </div>
    </div>
  `);
  showTabs("games");
  const cv = document.getElementById("sk");
  const ctx = cv.getContext("2d");
  const avail = Math.min((cv.parentElement && cv.parentElement.clientWidth) || 320, 360);
  const DPR = window.devicePixelRatio || 1;
  cv.style.width = avail + "px"; cv.style.height = avail + "px";
  cv.width = Math.round(avail * DPR); cv.height = Math.round(avail * DPR);
  const cell = cv.width / COLS;
  const css = getComputedStyle(document.documentElement);
  const C = n => (css.getPropertyValue(n) || "").trim();
  const brand = C("--brand") || "#0ea47f", brand2 = C("--brand-2") || "#0b7d63";
  const boardBg = C("--bg") || "#fff", grid = C("--bg2") || "#eee", danger = C("--danger") || "#e5484d";
  let snake, dir, nextDir, food, score, loop = null, playing = false, paused = false, speed, ticks = 0;

  const fill = (x, y, w, h, r) => { ctx.beginPath(); if (ctx.roundRect) ctx.roundRect(x, y, w, h, r); else ctx.rect(x, y, w, h); ctx.fill(); };
  function placeFood() {
    for (;;) { const f = { x: (Math.random() * COLS) | 0, y: (Math.random() * ROWS) | 0 };
      if (!snake.some(s => s.x === f.x && s.y === f.y)) { food = f; return; } }
  }
  const cx = s => s.x * cell + cell / 2, cy = s => s.y * cell + cell / 2;
  function draw() {
    ctx.fillStyle = boardBg; fill(0, 0, cv.width, cv.height, 16 * DPR);
    ctx.save();
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(0, 0, cv.width, cv.height, 16 * DPR); else ctx.rect(0, 0, cv.width, cv.height);
    ctx.clip();  // всё рисуем внутри скруглённого поля
    ctx.strokeStyle = grid; ctx.lineWidth = Math.max(1, DPR * 0.7);
    for (let i = 1; i < COLS; i++) {
      ctx.beginPath(); ctx.moveTo(i * cell, 0); ctx.lineTo(i * cell, cv.height); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(0, i * cell); ctx.lineTo(cv.width, i * cell); ctx.stroke();
    }
    // яблоко: красный кружок + зелёный листик + блик
    const ax = food.x * cell + cell / 2, ay = food.y * cell + cell / 2, ar = cell * 0.32;
    ctx.fillStyle = danger; ctx.beginPath(); ctx.arc(ax, ay, ar, 0, 7); ctx.fill();
    ctx.fillStyle = brand; ctx.beginPath(); ctx.ellipse(ax + ar * 0.5, ay - ar * 0.85, ar * 0.5, ar * 0.24, -0.6, 0, 7); ctx.fill();
    ctx.fillStyle = "rgba(255,255,255,.55)"; ctx.beginPath(); ctx.arc(ax - ar * 0.33, ay - ar * 0.33, ar * 0.2, 0, 7); ctx.fill();
    // змейка: гладкое тело (градиент голова→хвост), круглая голова, глаза, мелькающий язычок
    ctx.lineJoin = "round"; ctx.lineCap = "round";
    const head = snake[0], tail = snake[snake.length - 1];
    const g = ctx.createLinearGradient(cx(head), cy(head), cx(tail), cy(tail));
    g.addColorStop(0, brand2); g.addColorStop(1, brand);
    ctx.strokeStyle = g; ctx.lineWidth = cell * 0.72;
    ctx.beginPath(); ctx.moveTo(cx(snake[0]), cy(snake[0]));
    for (let i = 1; i < snake.length; i++) ctx.lineTo(cx(snake[i]), cy(snake[i]));
    if (snake.length === 1) ctx.lineTo(cx(snake[0]) + 0.01, cy(snake[0]));
    ctx.stroke();
    const hx = cx(head), hy = cy(head), hr = cell * 0.42, dx = dir.x, dy = dir.y, px = -dy, py = dx;
    ctx.fillStyle = brand2; ctx.beginPath(); ctx.arc(hx, hy, hr, 0, 7); ctx.fill();
    if ((ticks % 6) < 1) {  // раздвоенный язычок мелькает
      ctx.strokeStyle = "#e5484d"; ctx.lineWidth = Math.max(1.5, cell * 0.06);
      const bx = hx + dx * hr, by = hy + dy * hr, fx = hx + dx * hr * 1.8, fy = hy + dy * hr * 1.8;
      ctx.beginPath(); ctx.moveTo(bx, by); ctx.lineTo(fx, fy);
      ctx.moveTo(fx, fy); ctx.lineTo(fx + px * hr * 0.3 + dx * hr * 0.2, fy + py * hr * 0.3 + dy * hr * 0.2);
      ctx.moveTo(fx, fy); ctx.lineTo(fx - px * hr * 0.3 + dx * hr * 0.2, fy - py * hr * 0.3 + dy * hr * 0.2);
      ctx.stroke();
    }
    const ex = hx + dx * hr * 0.2, ey = hy + dy * hr * 0.2;  // глаза по направлению движения
    for (const sgn of [1, -1]) {
      const exx = ex + px * hr * 0.48 * sgn, eyy = ey + py * hr * 0.48 * sgn;
      ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.arc(exx, eyy, hr * 0.3, 0, 7); ctx.fill();
      ctx.fillStyle = "#15241d"; ctx.beginPath(); ctx.arc(exx + dx * hr * 0.12, eyy + dy * hr * 0.12, hr * 0.15, 0, 7); ctx.fill();
    }
    ctx.restore();
  }
  function reset() {
    snake = [{ x: 7, y: 8 }, { x: 6, y: 8 }, { x: 5, y: 8 }];
    dir = { x: 1, y: 0 }; nextDir = dir; score = 0; speed = 210; ticks = 0;
    document.getElementById("sk-score").textContent = "0"; placeFood(); draw();
  }
  function restartLoop() { if (loop) clearInterval(loop); loop = setInterval(step, speed); timers.push(loop); }
  function step() {
    dir = nextDir; ticks++;
    const head = { x: snake[0].x + dir.x, y: snake[0].y + dir.y };
    if (head.x < 0 || head.x >= COLS || head.y < 0 || head.y >= ROWS || snake.some(s => s.x === head.x && s.y === head.y))
      return gameOver();
    snake.unshift(head);
    if (head.x === food.x && head.y === food.y) {
      score++; document.getElementById("sk-score").textContent = score; haptic("light");
      if (score % 5 === 0 && speed > 130) { speed -= 8; restartLoop(); }
      placeFood();
    } else snake.pop();
    draw();
  }
  function start() {
    reset(); playing = true; paused = false;
    document.getElementById("sk-over").classList.remove("on");
    document.getElementById("sk-pause").textContent = "⏸";
    restartLoop();
  }
  function gameOver() {
    if (loop) clearInterval(loop); loop = null; playing = false; haptic("error");
    if (score > best) { best = score; try { localStorage.setItem("snake_best", best); } catch (e) {}
      document.getElementById("sk-best").textContent = best; }
    document.getElementById("sk-msg").textContent = L.over;
    document.getElementById("sk-sub").textContent = `${L.score}: ${score} · ${L.best}: ${best}`;
    document.getElementById("sk-go").textContent = L.again;
    document.getElementById("sk-over").classList.add("on");
  }
  function setDir(d) {
    const m = { up: { x: 0, y: -1 }, down: { x: 0, y: 1 }, left: { x: -1, y: 0 }, right: { x: 1, y: 0 } }[d];
    if (!m || (m.x === -dir.x && m.y === -dir.y)) return;  // нельзя развернуться на 180°
    nextDir = m;
  }
  onAll(".sk-b", "click", el => { if (playing && !paused) setDir(el.dataset.d); });
  let tx = 0, ty = 0;
  cv.addEventListener("touchstart", e => { const t = e.touches[0]; tx = t.clientX; ty = t.clientY; }, { passive: true });
  cv.addEventListener("touchend", e => {
    const t = e.changedTouches[0], dx = t.clientX - tx, dy = t.clientY - ty;
    if (Math.abs(dx) < 16 && Math.abs(dy) < 16) return;
    if (!playing || paused) return;
    setDir(Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "right" : "left") : (dy > 0 ? "down" : "up"));
  }, { passive: true });
  on("#sk-go", "click", start);
  on("#sk-pause", "click", () => {
    if (!playing) return;
    paused = !paused;
    if (paused) { if (loop) clearInterval(loop); loop = null; document.getElementById("sk-pause").textContent = "▶️"; }
    else { restartLoop(); document.getElementById("sk-pause").textContent = "⏸"; }
  });
  reset();
}

// ---- Файтинг: выбор персонажа + бой против компьютера (canvas, без сервера)
const FIGHTERS = {
  tooth: { emoji: "🦷", color: "#cde0ec", ru: "Зуб", uz: "Tish", en: "Tooth" },
  lungs: { emoji: "🫁", color: "#f2aab3", ru: "Лёгкие", uz: "O'pka", en: "Lungs" },
  heart: { emoji: "🫀", color: "#ff6b78", ru: "Сердце", uz: "Yurak", en: "Heart" },
  book: { emoji: "📚", color: "#6c93f0", ru: "Книга", uz: "Kitob", en: "Book" },
  brain: { emoji: "🧠", color: "#efa6c6", ru: "Мозг", uz: "Miya", en: "Brain" },
};
const FIGHT_ORDER = ["tooth", "lungs", "heart", "book", "brain"];
function fName(id) { return FIGHTERS[id][LANG] || FIGHTERS[id].ru; }

function fightSelectScreen() {
  const L = ({
    ru: { title: "Выбери бойца", sub: "Бой против компьютера · до 2 побед" },
    uz: { title: "Jangchini tanla", sub: "Kompyuterga qarshi · 2 g'alabagacha" },
    en: { title: "Pick your fighter", sub: "Vs computer · first to 2 wins" },
  })[LANG] || { title: "Выбери бойца", sub: "Бой против компьютера · до 2 побед" };
  render(`
    ${langBar()}
    <h1>🥊 ${L.title}</h1>
    <p class="muted small" style="margin:-6px 0 14px">${L.sub}</p>
    <div class="fg-grid">
      ${FIGHT_ORDER.map(id => `<button class="fg-card" data-id="${id}" style="--fc:${FIGHTERS[id].color}">
        <span class="fg-emoji">${FIGHTERS[id].emoji}</span><span class="fg-name">${fName(id)}</span></button>`).join("")}
    </div>
  `);
  showTabs("games");
  onAll(".fg-card", "click", el => { haptic("light"); go(fightArena, { char: el.dataset.id }); });
}

function fightArena({ char }) {
  const L = ({
    ru: { round: "РАУНД", fight: "БОЙ!", ko: "НОКАУТ!", win: "ПОБЕДА!", lose: "ПОРАЖЕНИЕ", draw: "НИЧЬЯ", again: "🔄 Ещё раз", exit: "Выход" },
    uz: { round: "RAUND", fight: "JANG!", ko: "NOKAUT!", win: "G'ALABA!", lose: "MAG'LUBIYAT", draw: "DURANG", again: "🔄 Yana", exit: "Chiqish" },
    en: { round: "ROUND", fight: "FIGHT!", ko: "K.O.!", win: "YOU WIN!", lose: "YOU LOSE", draw: "DRAW", again: "🔄 Rematch", exit: "Exit" },
  })[LANG] || { round: "РАУНД", fight: "БОЙ!", ko: "НОКАУТ!", win: "ПОБЕДА!", lose: "ПОРАЖЕНИЕ", draw: "НИЧЬЯ", again: "🔄 Ещё раз", exit: "Выход" };
  const foes = FIGHT_ORDER.filter(x => x !== char);
  const cpuChar = foes[(Math.random() * foes.length) | 0];
  render(`
    <div class="fa-hud">
      <div class="fa-side"><div class="fa-nm">${FIGHTERS[char].emoji} ${fName(char)}</div><div class="fa-bar"><span id="hp-p"></span></div></div>
      <div class="fa-mid"><div class="fa-timer" id="fa-timer">60</div><div class="fa-wins"><b id="w-p">0</b> : <b id="w-c">0</b></div></div>
      <div class="fa-side r"><div class="fa-nm">${fName(cpuChar)} ${FIGHTERS[cpuChar].emoji}</div><div class="fa-bar r"><span id="hp-c"></span></div></div>
    </div>
    <div class="fa-stage"><canvas id="fa"></canvas><div class="fa-anno" id="fa-anno"></div>
      <div class="fa-over" id="fa-over"><div class="fa-over-t" id="fa-res"></div>
        <div class="fa-over-b"><button class="btn" id="fa-again"></button><button class="btn secondary" id="fa-exit"></button></div></div>
    </div>
    <div class="fa-ctl">
      <div class="fa-move"><button class="fa-b" data-k="left">◀</button><button class="fa-b" data-k="jump">⤴</button><button class="fa-b" data-k="right">▶</button></div>
      <div class="fa-act"><button class="fa-b p" data-k="punch">👊</button><button class="fa-b k" data-k="kick">🦵</button><button class="fa-b bl" data-k="block">🛡</button><button class="fa-b sp" data-k="special">✦</button></div>
    </div>
  `);
  const cv = document.getElementById("fa"), ctx = cv.getContext("2d");
  const avail = Math.min((cv.parentElement && cv.parentElement.clientWidth) || 320, 560);
  const DPR = window.devicePixelRatio || 1;
  cv.style.width = avail + "px"; cv.style.height = Math.round(avail * 0.58) + "px";
  cv.width = Math.round(avail * DPR); cv.height = Math.round(avail * 0.58 * DPR);
  const W = cv.width, H = cv.height;
  const groundY = H * 0.9, fh = H * 0.62, hw = fh * 0.17;
  const grav = H * 0.004, jv = -H * 0.072, ms = W * 0.016, projSpd = W * 0.024;
  const ATK = {
    punch: { dur: 250, a0: 70, a1: 150, reach: hw * 2.3, dmg: 7, cd: 300, kb: W * 0.012 },
    kick: { dur: 380, a0: 120, a1: 240, reach: hw * 3.2, dmg: 11, cd: 560, kb: W * 0.028 },
    special: { dur: 430, a0: 130, a1: 200, reach: 0, dmg: 14, cd: 1700, kb: W * 0.034 },
  };
  const css = getComputedStyle(document.documentElement), CV = n => (css.getPropertyValue(n) || "").trim();
  const inkMuted = CV("--hint") || "#8a8a8e";

  function mk(ch, x, dir) {
    return { ch, x, y: groundY, vy: 0, dir, hp: 100, state: "idle", t: 0, dur: 0, didHit: false,
      blocking: false, blockT: 0, stun: 0, think: 0, moving: false, walkT: 0, cd: { punch: 0, kick: 0, special: 0 } };
  }
  let p, cpu, projs, sparks, phase, phaseT, round, winsP, winsC, timer, loop = null;
  const held = { left: false, right: false, block: false };

  function newRound(first) {
    p = mk(char, W * 0.28, 1); cpu = mk(cpuChar, W * 0.72, -1);
    projs = []; sparks = []; timer = 60000; phase = "intro"; phaseT = 0;
    if (first) { round = 1; winsP = 0; winsC = 0; }
  }
  function grounded(f) { return f.y >= groundY - 0.5; }
  function canAct(f) { return f.state === "idle" && f.stun <= 0 && grounded(f) && !f.blocking; }
  function trigger(f, type) {
    if (f.cd[type] > 0 || !canAct(f)) return;
    f.state = type; f.t = 0; f.dur = ATK[type].dur; f.didHit = false; f.cd[type] = ATK[type].cd;
    if (f === p) haptic("light");
  }
  function land(a, o, dmg, kb) {
    const guard = o.blocking && Math.sign(a.x - o.x) === o.dir;
    o.hp = Math.max(0, o.hp - (guard ? dmg * 0.25 : dmg));
    o.x = Math.max(W * 0.08, Math.min(W * 0.92, o.x + a.dir * (guard ? kb * 0.4 : kb)));
    o.stun = guard ? 130 : 240;
    sparks.push({ x: o.x - a.dir * hw, y: o.y - fh * 0.52, t: 0, big: !guard });
    haptic(o === p ? (guard ? "light" : "warning") : (guard ? "light" : "success"));
  }
  function physics(f, opp) {
    for (const k in f.cd) if (f.cd[k] > 0) f.cd[k] -= 33;
    if (f.stun > 0) f.stun -= 33;
    if (f.blockT > 0) { f.blockT -= 33; if (f.blockT <= 0) f.blocking = false; }
    f.vy += grav; f.y += f.vy;
    if (f.y >= groundY) { f.y = groundY; f.vy = 0; }
    if (f.state !== "idle") { f.t += 33; if (f.t >= f.dur) f.state = "idle"; }
    if (f.stun <= 0 && (f.state === "idle" || f.y < groundY)) f.dir = opp.x >= f.x ? 1 : -1;
  }
  function resolveHit(a, o) {
    if ((a.state === "punch" || a.state === "kick") && !a.didHit) {
      const A = ATK[a.state];
      if (a.t >= A.a0 && a.t <= A.a1) {
        const tip = a.x + a.dir * A.reach;
        if (Math.sign(o.x - a.x) === a.dir && Math.abs(tip - o.x) < hw * 1.8) { land(a, o, A.dmg, A.kb); a.didHit = true; }
      }
    }
    if (a.state === "special" && !a.didHit && a.t >= ATK.special.a0) {
      projs.push({ x: a.x + a.dir * hw * 1.4, y: a.y - fh * 0.52, dir: a.dir, owner: a, col: FIGHTERS[a.ch].color });
      a.didHit = true;
    }
  }
  function updateProjs() {
    for (let i = projs.length - 1; i >= 0; i--) {
      const pr = projs[i]; pr.x += pr.dir * projSpd;
      const tgt = pr.owner === p ? cpu : p;
      if (Math.abs(pr.x - tgt.x) < hw * 1.5) { land(pr.owner, tgt, ATK.special.dmg, ATK.special.kb); projs.splice(i, 1); }
      else if (pr.x < -hw || pr.x > W + hw) projs.splice(i, 1);
    }
  }
  function aiCPU() {
    cpu.moving = false;
    if (cpu.stun > 0) return;
    cpu.think -= 33;
    const dist = cpu.x - p.x, ad = Math.abs(dist);
    if (cpu.think <= 0 && canAct(cpu)) {
      cpu.think = 220 + Math.random() * 320; const r = Math.random();
      if (ad > ATK.kick.reach * 1.1) { if (cpu.cd.special <= 0 && r < 0.3) trigger(cpu, "special"); }
      else if (r < 0.2) { cpu.blocking = true; cpu.blockT = 240 + Math.random() * 220; }
      else if (r < 0.58) trigger(cpu, "kick"); else trigger(cpu, "punch");
    }
    if (!cpu.blocking && canAct(cpu) && ad > ATK.kick.reach * 0.9) { cpu.x -= Math.sign(dist) * ms * 0.72; cpu.moving = true; cpu.walkT += 33; }
  }
  function player() {
    p.moving = false;
    p.blocking = held.block && canAct(p) || (p.blocking && held.block && grounded(p) && p.stun <= 0 && p.state === "idle");
    if (p.blocking) return;
    if (canAct(p) || p.y < groundY) {
      const mv = (held.right ? 1 : 0) - (held.left ? 1 : 0);
      if (mv && p.stun <= 0 && p.state === "idle") { p.x = Math.max(W * 0.08, Math.min(W * 0.92, p.x + mv * ms)); p.moving = true; p.walkT += 33; }
    }
  }
  function anno(txt, big) { const el = document.getElementById("fa-anno"); if (!el) return;
    el.textContent = txt; el.className = "fa-anno" + (txt ? " show" : "") + (big ? " big" : ""); }
  function setHUD() {
    const sp = document.getElementById("hp-p"), sc = document.getElementById("hp-c");
    if (sp) sp.style.width = p.hp + "%"; if (sc) sc.style.width = cpu.hp + "%";
    const tm = document.getElementById("fa-timer"); if (tm) tm.textContent = Math.ceil(timer / 1000);
    const wp = document.getElementById("w-p"), wc = document.getElementById("w-c");
    if (wp) wp.textContent = winsP; if (wc) wc.textContent = winsC;
  }
  function endRound() {
    let res;
    if (p.hp <= 0 && cpu.hp <= 0) res = "draw";
    else if (cpu.hp <= 0) res = "p";
    else if (p.hp <= 0) res = "c";
    else res = p.hp > cpu.hp ? "p" : (cpu.hp > p.hp ? "c" : "draw");
    if (res === "p") winsP++; else if (res === "c") winsC++;
    setHUD();
    anno(res === "draw" ? L.draw : L.ko, true);
    phase = "roundend"; phaseT = 0;
  }
  function matchEnd() {
    phase = "matchend"; if (loop) { clearInterval(loop); loop = null; }
    const won = winsP > winsC;
    document.getElementById("fa-res").textContent = winsP === winsC ? L.draw : (won ? L.win : L.lose);
    document.getElementById("fa-res").className = "fa-over-t " + (won ? "win" : winsP === winsC ? "" : "lose");
    const ag = document.getElementById("fa-again"), ex = document.getElementById("fa-exit");
    ag.textContent = L.again; ex.textContent = L.exit;
    document.getElementById("fa-over").classList.add("on");
    ag.onclick = () => { document.getElementById("fa-over").classList.remove("on"); newRound(true); setHUD(); start(); };
    ex.onclick = () => back();
  }

  function shade(hex, f) {  // f<0 — темнее, f>0 — светлее
    const n = parseInt(hex.slice(1), 16); let r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
    const m = f < 0 ? 0 : 255, a = Math.abs(f);
    r = Math.round(r + (m - r) * a); g = Math.round(g + (m - g) * a); b = Math.round(b + (m - b) * a);
    return "rgb(" + r + "," + g + "," + b + ")";
  }
  function seg(ax, ay, bx, by, ex, ey, w1, w2, endR, col, endCol) {  // двусегментная конечность с суставом
    ctx.strokeStyle = col; ctx.lineCap = "round";
    ctx.lineWidth = w1; ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
    ctx.lineWidth = w2; ctx.beginPath(); ctx.moveTo(bx, by); ctx.lineTo(ex, ey); ctx.stroke();
    if (endR) { ctx.fillStyle = endCol || col; ctx.beginPath(); ctx.arc(ex, ey, endR, 0, 7); ctx.fill(); }
  }
  function drawFighter(f) {
    const F = FIGHTERS[f.ch], d = f.dir, act = f.state;
    const on = (a, b) => f.t >= a && f.t <= b;
    const feetY = f.y, cxp = f.x;
    const bob = Math.sin(Date.now() / 300 + (f === cpu ? 1.3 : 0)) * fh * 0.012;
    const crouch = (act === "block" || f.blocking) ? fh * 0.04 : 0;
    const topY = feetY - fh + crouch;
    const shY = topY + fh * 0.32 + bob, hipY = topY + fh * 0.62, waistY = shY + (hipY - shY) * 0.52;
    const shW = hw * 1.18, waistW = hw * 0.82, hipW = hw * 1.02;
    const bodyGrad = ctx.createLinearGradient(0, shY - fh * 0.06, 0, hipY);
    bodyGrad.addColorStop(0, shade(F.color, 0.16)); bodyGrad.addColorStop(1, shade(F.color, -0.1));
    const limbCol = shade(F.color, -0.08), fistCol = shade(F.color, -0.26), shortCol = shade(F.color, -0.32);
    const air = f.y < groundY - 0.5, wob = f.moving ? Math.sin(f.walkT / 90) : 0;
    const legW = hw * 0.9, backArmW = hw * 0.62, frontArmW = hw * 0.78;
    // тень
    ctx.fillStyle = "rgba(0,0,0,.16)"; ctx.beginPath();
    ctx.ellipse(cxp, groundY + hw * 0.2, hw * 1.7, hw * 0.42, 0, 0, 7); ctx.fill();
    // ЗАДНЯЯ рука
    seg(cxp - d * hw * 0.3, shY + fh * 0.03, cxp - d * hw * 0.6, shY + fh * 0.18, cxp - d * hw * 0.45, hipY - fh * 0.02,
      backArmW, backArmW * 0.85, hw * 0.4, limbCol, fistCol);
    // ЗАДНЯЯ нога (бедро + голень)
    { let fx = cxp - d * hw * 0.4, fy = feetY;
      if (air) { fx = cxp - d * hw * 0.55; fy = feetY - fh * 0.14; }
      else if (f.moving) fx = cxp - d * hw * 0.4 - wob * fh * 0.14;
      seg(cxp - d * hw * 0.32, hipY, (cxp - d * hw * 0.32 + fx) / 2, (hipY + fy) / 2 + fh * 0.03, fx, fy,
        legW, legW * 0.82, hw * 0.52, limbCol, shade(F.color, -0.16)); }
    // ТОРС (мускулистый силуэт: плечи → талия → бёдра)
    ctx.fillStyle = bodyGrad; ctx.beginPath();
    ctx.moveTo(cxp - shW, shY);
    ctx.quadraticCurveTo(cxp - (shW + waistW) / 2 * 1.06, (shY + waistY) / 2, cxp - waistW, waistY);
    ctx.quadraticCurveTo(cxp - hipW, (waistY + hipY) / 2 + fh * 0.02, cxp - hipW, hipY);
    ctx.lineTo(cxp + hipW, hipY);
    ctx.quadraticCurveTo(cxp + hipW, (waistY + hipY) / 2 + fh * 0.02, cxp + waistW, waistY);
    ctx.quadraticCurveTo(cxp + (shW + waistW) / 2 * 1.06, (shY + waistY) / 2, cxp + shW, shY);
    ctx.quadraticCurveTo(cxp, shY - fh * 0.07, cxp - shW, shY);
    ctx.closePath(); ctx.fill();
    // плечи-дельты
    ctx.fillStyle = shade(F.color, 0.05);
    [-1, 1].forEach(s => { ctx.beginPath(); ctx.arc(cxp + s * shW * 0.82, shY + fh * 0.02, hw * 0.5, 0, 7); ctx.fill(); });
    // грудь (блик) + линия пресса
    ctx.globalAlpha = 0.45; ctx.fillStyle = shade(F.color, 0.24);
    ctx.beginPath(); ctx.ellipse(cxp, shY + fh * 0.07, hw * 0.72, fh * 0.05, 0, 0, 7); ctx.fill();
    ctx.globalAlpha = 0.33; ctx.strokeStyle = shade(F.color, -0.22); ctx.lineCap = "round"; ctx.lineWidth = hw * 0.12;
    ctx.beginPath(); ctx.moveTo(cxp, shY + fh * 0.13); ctx.lineTo(cxp, waistY + fh * 0.02); ctx.stroke();
    ctx.globalAlpha = 1;
    // ПЕРЕДНЯЯ нога
    { let kx = cxp + d * hw * 0.45, ky = hipY + fh * 0.2, fx = cxp + d * hw * 0.45, fy = feetY;
      if (act === "kick" && on(ATK.kick.a0, ATK.kick.a1)) { kx = cxp + d * fh * 0.3; ky = hipY - fh * 0.02; fx = cxp + d * fh * 0.56; fy = hipY - fh * 0.08; }
      else if (air) { kx = cxp + d * hw * 0.25; ky = hipY + fh * 0.12; fx = cxp + d * hw * 0.55; fy = feetY - fh * 0.14; }
      else if (f.moving) { fx = cxp + d * hw * 0.45 + wob * fh * 0.14; ky = hipY + fh * 0.18; }
      seg(cxp + d * hw * 0.32, hipY, kx, ky, fx, fy, legW, legW * 0.82, hw * 0.52, F.color, shade(F.color, -0.16)); }
    // ШОРТЫ (поверх бёдер) + пояс — «настоящий» боец
    ctx.fillStyle = shortCol; ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(cxp - hipW * 1.06, hipY - fh * 0.05, hipW * 2.12, fh * 0.14, hw * 0.35);
    else ctx.rect(cxp - hipW * 1.06, hipY - fh * 0.05, hipW * 2.12, fh * 0.14);
    ctx.fill();
    ctx.fillStyle = shade(F.color, 0.12); ctx.fillRect(cxp - hipW * 1.06, hipY - fh * 0.055, hipW * 2.12, fh * 0.025);
    // ПЕРЕДНЯЯ рука
    { let ex = cxp + d * hw * 0.6, ey = shY + fh * 0.18, wx = cxp + d * hw * 0.46, wy = hipY - fh * 0.02;
      if (act === "punch" && on(ATK.punch.a0, ATK.punch.a1)) { ex = cxp + d * fh * 0.25; ey = shY; wx = cxp + d * fh * 0.49; wy = shY; }
      else if (act === "block" || f.blocking) { ex = cxp + d * hw * 0.5; ey = shY + fh * 0.04; wx = cxp + d * hw * 0.3; wy = shY - fh * 0.1; }
      else if (f.moving) wx = cxp + d * hw * 0.46 - wob * fh * 0.1;
      seg(cxp + d * hw * 0.28, shY + fh * 0.03, ex, ey, wx, wy, frontArmW, frontArmW * 0.85, hw * 0.5, F.color, fistCol); }
    // ГОЛОВА = орган-фигурка (без лица), сидит на плечах
    const lean = f.stun > 0 ? -d * fh * 0.05 : 0;
    ctx.font = (fh * 0.46 | 0) + "px serif"; ctx.textAlign = "center"; ctx.textBaseline = "alphabetic";
    ctx.fillText(F.emoji, cxp + lean, shY - fh * 0.02 + bob);
    // щит при блоке
    if (f.blocking) { ctx.strokeStyle = "rgba(90,141,238,.7)"; ctx.lineWidth = hw * 0.4;
      ctx.beginPath(); ctx.arc(cxp + d * hw * 1.2, shY + fh * 0.1, fh * 0.26, -1, 1); ctx.stroke(); }
  }
  function draw() {
    const sky = ctx.createLinearGradient(0, 0, 0, H);
    sky.addColorStop(0, "#1b2a4a"); sky.addColorStop(1, "#38507e");
    ctx.fillStyle = sky; ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = "rgba(0,0,0,.25)"; ctx.fillRect(0, groundY + hw * 0.2, W, H - groundY);
    drawFighter(p.x <= cpu.x ? cpu : p); drawFighter(p.x <= cpu.x ? p : cpu);  // ближний поверх
    projs.forEach(pr => { ctx.fillStyle = pr.col; ctx.globalAlpha = .9;
      ctx.beginPath(); ctx.arc(pr.x, pr.y, hw * 0.7, 0, 7); ctx.fill();
      ctx.globalAlpha = .35; ctx.beginPath(); ctx.arc(pr.x - pr.dir * hw * 0.5, pr.y, hw * 1.0, 0, 7); ctx.fill();
      ctx.globalAlpha = 1; });
    for (let i = sparks.length - 1; i >= 0; i--) { const s = sparks[i]; s.t += 33;
      const rr = (s.t / 180) * hw * (s.big ? 3 : 1.8);
      ctx.strokeStyle = s.big ? "#ffd23f" : "#fff"; ctx.globalAlpha = Math.max(0, 1 - s.t / 180); ctx.lineWidth = hw * 0.4;
      ctx.beginPath(); ctx.arc(s.x, s.y, rr, 0, 7); ctx.stroke(); ctx.globalAlpha = 1;
      if (s.t > 180) sparks.splice(i, 1); }
  }
  function step() {
    if (phase === "intro") {
      phaseT += 33;
      if (phaseT < 780) anno(L.round + " " + round, false);
      else if (phaseT < 1280) anno(L.fight, true);
      else { anno(""); phase = "fight"; }
    } else if (phase === "fight") {
      timer -= 33; if (timer < 0) timer = 0;
      player(); aiCPU();
      physics(p, cpu); physics(cpu, p);
      resolveHit(p, cpu); resolveHit(cpu, p); updateProjs();
      setHUD();
      if (p.hp <= 0 || cpu.hp <= 0 || timer <= 0) endRound();
    } else if (phase === "roundend") {
      phaseT += 33;
      if (phaseT > 1500) {
        if (winsP >= 2 || winsC >= 2) { matchEnd(); return; }
        round++; newRound(false); phase = "intro"; phaseT = 0;
      }
    }
    draw();
  }
  function start() { if (loop) clearInterval(loop); loop = setInterval(step, 33); timers.push(loop); }

  // ввод: удержание (влево/вправо/блок) + тапы (прыжок/удары)
  $app.querySelectorAll(".fa-b").forEach(btn => {
    const k = btn.dataset.k;
    const down = e => { e.preventDefault();
      if (k === "left" || k === "right" || k === "block") held[k] = true;
      else if (k === "jump") { if (canAct(p)) { p.vy = jv; } }
      else trigger(p, k);
    };
    const up = e => { e.preventDefault(); if (k === "left" || k === "right" || k === "block") held[k] = false; };
    btn.addEventListener("pointerdown", down);
    btn.addEventListener("pointerup", up);
    btn.addEventListener("pointerleave", up);
    btn.addEventListener("pointercancel", up);
  });
  newRound(true); setHUD(); start();
}

// ---- учитель: создание куиза
async function quizCreateScreen() {
  const Q = quizT();
  render(`
    ${langBar()}
    <h1>${Q.create_title}</h1>
    <div class="card">
      <input id="qtopic" class="field" placeholder="${esc(Q.topic_ph)}" autocomplete="off">
      <label class="muted small">${Q.lang_label}</label>
      <div class="langpick" id="qlang">
        ${["ru", "uz", "en"].map(l => `<button class="lbtn ${l === LANG ? "on" : ""}" data-l="${l}">${l === "ru" ? "🇷🇺 Рус" : l === "uz" ? "🇺🇿 Ўзб" : "🇬🇧 Eng"}</button>`).join("")}
      </div>
      <div class="row" style="gap:10px;margin-top:10px">
        <div class="grow"><label class="muted small">${Q.count_label}</label>
          <input id="qcount" class="field" type="number" min="3" max="20" value="8" inputmode="numeric"></div>
        <div class="grow"><label class="muted small">${Q.seconds_label}</label>
          <select id="qsec" class="field">
            <option value="10">10</option><option value="15">15</option>
            <option value="20" selected>20</option><option value="30">30</option></select></div>
      </div>
      <label class="muted small" style="margin-top:10px;display:block">${Q.mode_label}</label>
      <div class="langpick" id="qmode">
        <button class="lbtn on" data-a="1">⚡ ${Q.mode_auto}</button>
        <button class="lbtn" data-a="0">✋ ${Q.mode_manual}</button>
      </div>
      <button class="btn" id="qmake" style="margin-top:14px">${Q.create_btn}</button>
    </div>
  `);
  let lang = LANG, auto = 1;
  onAll("#qlang .lbtn", "click", el => { lang = el.dataset.l; $app.querySelectorAll("#qlang .lbtn").forEach(b => b.classList.toggle("on", b === el)); });
  onAll("#qmode .lbtn", "click", el => { auto = +el.dataset.a; $app.querySelectorAll("#qmode .lbtn").forEach(b => b.classList.toggle("on", b === el)); });
  on("#qmake", "click", async () => {
    const topic = (document.getElementById("qtopic").value || "").trim();
    if (!topic) { toast(Q.topic_ph); return; }
    const count = Math.max(3, Math.min(20, +document.getElementById("qcount").value || 8));
    const seconds = +document.getElementById("qsec").value || 20;
    render(`<div class="center"><div class="spin big"></div><p class="muted" style="margin-top:14px">${Q.generating}</p></div>`);
    try {
      const r = await api("/api/quiz/create", { json: { topic, lang, count, seconds, auto: !!auto } });
      go(quizHostScreen, { game_id: r.game_id }, true);
    } catch (e) { haptic("error"); toast(e.message); go(quizCreateScreen, {}, true); }
  });
}

// ---- учитель: экран ведущего
async function quizHostScreen({ game_id }) {
  const Q = quizT();
  let deadline = 0;
  const st = { key: "", revealAt: 0, fired: false };  // одноразовый авто-переход на каждую фазу
  async function autoNext() {
    try { await api(`/api/quiz/${game_id}/next`, { method: "POST" }); }
    catch (e) { st.fired = false; return; }  // не вышло — попробуем на следующем тике
    load();
  }
  async function load() {
    let d;
    try { d = await api(`/api/quiz/${game_id}/host`); } catch (e) { toast(e.message); return; }
    const scroll = window.scrollY;
    const key = d.phase + ":" + d.index;
    if (st.key !== key) { st.key = key; st.fired = false; st.revealAt = d.phase === "reveal" ? Date.now() : 0; }
    let html = "";
    if (d.phase === "lobby") {
      html = `
        <p class="muted small" style="text-align:center;margin:0">${esc(d.topic)}</p>
        <p class="muted small" style="text-align:center;margin:8px 0 0">${Q.pin_title}</p>
        <div class="big-code">${d.pin.slice(0, 3)} ${d.pin.slice(3)}</div>
        <div class="stats"><div class="stat"><span class="muted small">${Q.joined}</span><b>${d.players}</b></div>
          <div class="stat"><span class="muted small">${Q.count_label}</span><b>${d.total}</b></div></div>
        ${d.joined.length ? `<div class="chips">${d.joined.map(p => `<span class="chip">${p.emoji || ""} ${esc(p.name)}</span>`).join("")}</div>`
          : `<div class="card muted" style="text-align:center">${Q.nobody}</div>`}
        <button class="btn" id="next" ${d.can_start ? "" : "disabled"}>${Q.start_btn}</button>
        <button class="btn danger" id="end">${Q.finish_btn}</button>`;
    } else if (d.phase === "question") {
      deadline = Date.now() + (d.remaining_ms || 0);
      html = `
        <p class="muted small" style="text-align:center;margin:0">${Q.q_of.replace("{i}", d.index + 1).replace("{n}", d.total)}</p>
        <div class="cbar"><span id="cb"></span></div>
        <div class="qh"><b id="ctime"></b><span class="muted">${Q.answered_n}: <b>${d.answered}</b>/${d.players}</span></div>
        <div class="qbody">${esc(d.question.text)}</div>
        ${quizOptions(d.question.options)}
        <button class="btn" id="next">${Q.reveal_btn}</button>`;
    } else if (d.phase === "reveal") {
      const total = Math.max(1, d.counts.reduce((a, b) => a + b, 0));
      html = `
        <p class="muted small" style="text-align:center;margin:0">${Q.q_of.replace("{i}", d.index + 1).replace("{n}", d.total)}</p>
        <div class="qbody">${esc(d.question.text)}</div>
        ${quizOptions(d.question.options, { correct: d.correct, counts: d.counts })}
        <h2>${Q.leaderboard}</h2>
        ${d.leaderboard.map((p, i) => `<div class="lbrow"><span class="lbrank">${i + 1}</span>
          <span class="avm">${p.emoji || ""}</span><span class="grow ell">${esc(p.name)}</span>${p.delta ? `<span class="lbdelta">+${p.delta}</span>` : ""}
          <b>${p.score}</b></div>`).join("")}
        ${d.auto ? `<p class="muted small" style="text-align:center;margin-top:10px">${Q.next_in} <b id="rnext"></b></p>` : ""}
        <button class="btn" id="next">${d.is_last ? Q.finish_btn : Q.next_btn}</button>`;
    } else { // ended
      html = quizPodiumHtml(d.podium, Q) +
        (d.leaderboard || []).slice(3).map((p, i) => `<div class="lbrow"><span class="lbrank">${i + 4}</span>
          <span class="avm">${p.emoji || ""}</span><span class="grow ell">${esc(p.name)}</span><b>${p.score}</b></div>`).join("") +
        `<button class="btn" id="home">${Q.home_btn}</button>`;
    }
    $app.innerHTML = html;
    window.scrollTo(0, scroll);
    on("#next", "click", async () => {
      const b = $app.querySelector("#next"); if (b) b.disabled = true;
      try { await api(`/api/quiz/${game_id}/next`, { method: "POST" }); } catch (e) { toast(e.message); if (b) b.disabled = false; return; }
      load();
    });
    on("#end", "click", async () => {
      if (!confirm(Q.finish_btn + "?")) return;
      try { await api(`/api/quiz/${game_id}/end`, { method: "POST" }); } catch (e) { toast(e.message); }
      load();
    });
    on("#home", "click", home);
    clearInterval(quizHostScreen._tick);
    quizHostScreen._tick = setInterval(() => {
      if (d.phase === "question") {
        const left = Math.max(0, (deadline - Date.now()) / 1000);
        const el = document.getElementById("ctime"), cb = document.getElementById("cb");
        if (el) el.textContent = Math.ceil(left) + "s";
        if (cb) cb.style.width = Math.min(100, left * 100 / (d.seconds || 20)) + "%";
        // авто-показ ответа: время вышло или все ответили (ведущий мог уже нажать вручную)
        if (d.auto && !st.fired && (left <= 0 || (d.players > 0 && d.answered >= d.players))) { st.fired = true; autoNext(); }
      } else if (d.phase === "reveal" && d.auto) {
        const left = Math.max(0, (st.revealAt + QUIZ_REVEAL_MS - Date.now()) / 1000);
        const el = document.getElementById("rnext"); if (el) el.textContent = Math.ceil(left) + "s";
        if (!st.fired && left <= 0) { st.fired = true; autoNext(); }
      }
    }, 200);
    timers.push(quizHostScreen._tick);
  }
  render(`<div class="center muted">${t("loading")}</div>`);
  await load();
  timers.push(setInterval(load, 2000));
}

// ---- студент: вход по коду
async function quizJoinScreen() {
  const Q = quizT();
  let avatar = QUIZ_AVATARS[Math.floor(Math.random() * QUIZ_AVATARS.length)];
  render(`
    ${langBar()}
    <h1>${Q.join_title}</h1>
    <div class="card">
      <p class="muted small" style="margin:0 0 6px">${Q.join_hint}</p>
      <input id="qpin" class="code-input" inputmode="numeric" maxlength="6" placeholder="••••••" autocomplete="off">
      <p class="muted small" style="margin:12px 0 6px">${Q.pick_avatar}</p>
      <div class="avpick" id="avpick">
        ${QUIZ_AVATARS.map(a => `<button class="av ${a === avatar ? "on" : ""}" data-a="${a}">${a}</button>`).join("")}
      </div>
      <button class="btn" id="qjoin">${Q.join_btn}</button>
    </div>
  `);
  const pin = document.getElementById("qpin");
  pin.addEventListener("input", () => { pin.value = pin.value.replace(/\D/g, "").slice(0, 6); });
  pin.addEventListener("keydown", e => { if (e.key === "Enter") doJoin(); });
  onAll("#avpick .av", "click", el => {
    avatar = el.dataset.a;
    $app.querySelectorAll("#avpick .av").forEach(b => b.classList.toggle("on", b === el));
    haptic("success");
  });
  on("#qjoin", "click", doJoin);
  async function doJoin() {
    if (pin.value.length !== 6) { toast(t("code_6")); return; }
    try {
      const r = await api("/api/quiz/join", { json: { pin: pin.value, emoji: avatar } });
      go(quizPlayScreen, { game_id: r.game_id, player_id: r.player_id }, true);
    } catch (e) { haptic("error"); toast(e.message); }
  }
}

// ---- студент: игровой экран
async function quizPlayScreen({ game_id, player_id }) {
  const Q = quizT();
  let sig = "", deadline = 0, locking = false;
  async function load() {
    let d;
    try { d = await api(`/api/quiz/${game_id}/play?player_id=${player_id}`); } catch (e) { return; }
    const newSig = `${d.phase}:${d.index != null ? d.index : "-"}:${d.answered ? "a" : "n"}`;
    if (d.phase === "question") deadline = Date.now() + (d.remaining_ms || 0);
    if (newSig === sig && d.phase === "question") { return; } // не перерисовываем — таймер крутит отдельный интервал
    sig = newSig;
    let html = "";
    if (d.phase === "lobby") {
      html = `<div class="center"><div class="qbig">${d.emoji || "🎮"}</div><h1>${Q.you_in}</h1>
        <p class="muted">${esc(d.name)}</p><div class="spin big" style="margin:16px auto"></div>
        <p class="muted small">${Q.waiting_host} · ${d.players} ${Q.players_word}</p></div>`;
    } else if (d.phase === "question") {
      const answered = d.answered;
      html = `
        <p class="muted small" style="text-align:center;margin:0">${Q.q_of.replace("{i}", d.index + 1).replace("{n}", d.total)}</p>
        <div class="cbar"><span id="cb"></span></div>
        <div class="qbody">${esc(d.question.text)}</div>
        ${answered
          ? quizOptions(d.question.options, { chosen: d.chosen }) + `<div class="card ok-soft" style="text-align:center">${Q.answered_wait}</div>`
          : `<p class="muted small" id="pickhint" style="text-align:center">${Q.pick}</p>` + quizOptions(d.question.options, { tappable: true })}`;
    } else if (d.phase === "reveal") {
      const y = d.you;
      const verdict = !y.answered ? Q.no_answer : (y.correct ? Q.correct_word : Q.wrong_word);
      const vcls = y.correct ? "ok" : "bad";
      html = `
        <div class="verdict ${vcls}">${y.correct ? "✅" : (y.answered ? "❌" : "⏱")}<br>${verdict}${y.points ? ` · +${y.points}` : ""}</div>
        <div class="stats"><div class="stat"><span class="muted small">${Q.place}</span><b>${y.rank}</b></div>
          <div class="stat"><span class="muted small">${Q.score_word}</span><b>${y.score}</b></div></div>
        <h2>${Q.leaderboard}</h2>
        ${d.leaderboard.map((p, i) => `<div class="lbrow ${p.name === d.name ? "me" : ""}"><span class="lbrank">${i + 1}</span>
          <span class="avm">${p.emoji || ""}</span><span class="grow ell">${esc(p.name)}</span><b>${p.score}</b></div>`).join("")}
        <p class="muted small" style="text-align:center">${Q.waiting_host}</p>`;
    } else { // ended
      html = `<div class="verdict ${d.rank === 1 ? "gold" : "ok"}">${["🥇", "🥈", "🥉"][d.rank - 1] || "🎉"}<br>${Q.your_place}: ${d.rank} ${Q.of_n.replace("{n}", d.players)}</div>
        <p class="center"><b>${d.score}</b> ${Q.score_word}</p>
        ${quizPodiumHtml(d.podium, Q)}
        <button class="btn" id="home">${Q.home_btn}</button>`;
    }
    $app.innerHTML = html;
    on("#home", "click", home);
    onAll(".qopt[data-opt]", "click", async el => {
      if (locking) return; locking = true;
      const opt = +el.dataset.opt;
      $app.querySelectorAll(".qopt").forEach(b => { b.disabled = true; b.classList.toggle("chosen", b === el); });
      haptic("success");
      try { await api(`/api/quiz/${game_id}/answer?player_id=${player_id}`, { json: { q_index: d.index, option: opt } }); }
      catch (e) { toast(e.message); }
      locking = false; sig = ""; load();
    });
    clearInterval(quizPlayScreen._tick);
    quizPlayScreen._tick = setInterval(() => {
      const cb = document.getElementById("cb"); if (!cb) return;
      const left = Math.max(0, (deadline - Date.now()) / 1000);
      cb.style.width = Math.min(100, left * 100 / (d.seconds || 20)) + "%";
      if (left <= 0) $app.querySelectorAll(".qopt[data-opt]").forEach(b => { b.disabled = true; });
    }, 200);
    timers.push(quizPlayScreen._tick);
  }
  render(`<div class="center muted">${t("loading")}</div>`);
  await load();
  timers.push(setInterval(load, 1200));
}

function quizPodiumHtml(podium, Q) {
  if (!podium || !podium.length) return "";
  const order = [1, 0, 2]; // 2-й, 1-й, 3-й — визуальный подиум
  return `<div class="podium">` + order.map(i => {
    const p = podium[i]; if (!p) return "";
    return `<div class="pod p${i}"><div class="podav">${p.emoji || ""}</div><div class="podname ell">${esc(p.name)}</div>
      <div class="podbar"><span>${["🥇", "🥈", "🥉"][i]}</span><b>${p.score}</b></div></div>`;
  }).join("") + `</div>`;
}

/* ================================================================ игра «Мафия» (офлайн) */

const MAFIA = {
  ru: {
    menu_title: "Мафия", create_btn: "➕ Создать игру", join_label: "…или войти по коду",
    join_btn: "Войти", online_soon: "🌐 Онлайн-версия с чатом — скоро",
    pin_title: "Код игры", start_btn: "▶️ Начать", lobby_wait: "Ждём, пока организатор начнёт…",
    players_word: "игроков", need_more: "Нужно минимум {n} игрока",
    night_title: "Ночь", day_title: "День", vote_title: "Голосование",
    you_are: "Ваша роль", civ_sleep: "Город спит 😴 Ждите утра.",
    mafia_kill: "Выберите жертву", mates: "Ваши подельники", mafia_alone: "Вы — единственная мафия",
    doc_heal: "Кого лечить?", comm_check: "Кого проверить?",
    check_mafia: "🔴 Это МАФИЯ!", check_not: "🟢 Не мафия",
    killed_msg: "Ночью убили", nobody_killed: "Этой ночью все выжили! 🎉",
    discuss: "Обсуждайте вживую: кто мафия?", vote_pick: "Голосуйте: кто мафия? 🗳",
    voted: "Ваш голос", dead: "Вы выбыли из игры", spectating: "Наблюдаете",
    win_town: "🏆 Победил город!", win_mafia: "🔪 Победила мафия!", roles_reveal: "Кто кем был",
    end_btn: "Завершить игру", alive_word: "в игре", dead_word: "выбыл", waiting_next: "Ждём следующую фазу…",
    r_mafia: "Мафия", r_civilian: "Мирный житель", r_commissar: "Комиссар", r_doctor: "Доктор",
    day_time: "Время обсуждения (минут)", min_ph: "напр. 3", force_next: "⏭ Дальше",
  },
  uz: {
    menu_title: "Mafiya", create_btn: "➕ O'yin yaratish", join_label: "…yoki kod bilan kirish",
    join_btn: "Kirish", online_soon: "🌐 Chatli onlayn versiya — tez orada",
    pin_title: "O'yin kodi", start_btn: "▶️ Boshlash", lobby_wait: "Tashkilotchi boshlashini kutyapmiz…",
    players_word: "o'yinchi", need_more: "Kamida {n} o'yinchi kerak",
    night_title: "Tun", day_title: "Kun", vote_title: "Ovoz berish",
    you_are: "Sizning rolingiz", civ_sleep: "Shahar uxlayapti 😴 Tongni kuting.",
    mafia_kill: "Qurbonni tanlang", mates: "Sheriklaringiz", mafia_alone: "Siz yagona mafiyasiz",
    doc_heal: "Kimni davolaysiz?", comm_check: "Kimni tekshirasiz?",
    check_mafia: "🔴 Bu MAFIYA!", check_not: "🟢 Mafiya emas",
    killed_msg: "Kechasi o'ldirildi", nobody_killed: "Bu kecha hamma omon qoldi! 🎉",
    discuss: "Jonli muhokama qiling: kim mafiya?", vote_pick: "Ovoz bering: kim mafiya? 🗳",
    voted: "Sizning ovozingiz", dead: "O'yindan chiqdingiz", spectating: "Kuzatyapsiz",
    win_town: "🏆 Shahar g'olib!", win_mafia: "🔪 Mafiya g'olib!", roles_reveal: "Kim kim edi",
    end_btn: "O'yinni yakunlash", alive_word: "o'yinda", dead_word: "chiqdi", waiting_next: "Keyingi bosqichni kutyapmiz…",
    r_mafia: "Mafiya", r_civilian: "Tinch aholi", r_commissar: "Komissar", r_doctor: "Shifokor",
    day_time: "Muhokama vaqti (daqiqa)", min_ph: "masalan 3", force_next: "⏭ Keyingisi",
  },
  en: {
    menu_title: "Mafia", create_btn: "➕ Create game", join_label: "…or join by PIN",
    join_btn: "Join", online_soon: "🌐 Online version with chat — coming soon",
    pin_title: "Game PIN", start_btn: "▶️ Start", lobby_wait: "Waiting for the host to start…",
    players_word: "players", need_more: "Need at least {n} players",
    night_title: "Night", day_title: "Day", vote_title: "Voting",
    you_are: "Your role", civ_sleep: "The town is asleep 😴 Wait for morning.",
    mafia_kill: "Choose a victim", mates: "Your partners", mafia_alone: "You are the only mafia",
    doc_heal: "Who to heal?", comm_check: "Who to check?",
    check_mafia: "🔴 This is MAFIA!", check_not: "🟢 Not mafia",
    killed_msg: "Killed last night", nobody_killed: "Everyone survived the night! 🎉",
    discuss: "Discuss out loud: who's the mafia?", vote_pick: "Vote: who's the mafia? 🗳",
    voted: "Your vote", dead: "You're out of the game", spectating: "Spectating",
    win_town: "🏆 Town wins!", win_mafia: "🔪 Mafia wins!", roles_reveal: "Who was who",
    end_btn: "End game", alive_word: "in", dead_word: "out", waiting_next: "Waiting for the next phase…",
    r_mafia: "Mafia", r_civilian: "Civilian", r_commissar: "Detective", r_doctor: "Doctor",
    day_time: "Discussion time (minutes)", min_ph: "e.g. 3", force_next: "⏭ Next",
  },
};
function mafiaT() { return MAFIA[LANG] || MAFIA.ru; }
const MAFIA_ROLE_EMOJI = { mafia: "🔪", civilian: "👤", commissar: "🔎", doctor: "💉" };
function mafiaRoleName(role) { const M = mafiaT(); return { mafia: M.r_mafia, civilian: M.r_civilian, commissar: M.r_commissar, doctor: M.r_doctor }[role] || role; }

// ---- меню: создать или войти
function mafiaMenuScreen() {
  const M = mafiaT();
  let avatar = QUIZ_AVATARS[Math.floor(Math.random() * QUIZ_AVATARS.length)];
  render(`
    ${langBar()}
    <h1>🕵️ ${M.menu_title}</h1>
    <div class="card">
      <p class="muted small" style="margin:0 0 6px">${quizT().pick_avatar}</p>
      <div class="avpick" id="avpick">
        ${QUIZ_AVATARS.map(a => `<button class="av ${a === avatar ? "on" : ""}" data-a="${a}">${a}</button>`).join("")}
      </div>
      <button class="btn" id="mcreate">${M.create_btn}</button>
      <p class="muted small" style="text-align:center;margin:12px 0 6px">${M.join_label}</p>
      <input id="mpin" class="code-input" inputmode="numeric" maxlength="6" placeholder="••••••" autocomplete="off">
      <button class="btn secondary" id="mjoin">${M.join_btn}</button>
    </div>
    <p class="muted small" style="text-align:center">${M.online_soon}</p>
  `);
  onAll("#avpick .av", "click", el => { avatar = el.dataset.a; $app.querySelectorAll("#avpick .av").forEach(b => b.classList.toggle("on", b === el)); haptic("success"); });
  const pin = document.getElementById("mpin");
  pin.addEventListener("input", () => { pin.value = pin.value.replace(/\D/g, "").slice(0, 6); });
  on("#mcreate", "click", async () => {
    try { const r = await api("/api/mafia/create", { json: { emoji: avatar } });
      go(mafiaPlayScreen, { game_id: r.game_id, player_id: r.player_id }, true);
    } catch (e) { haptic("error"); toast(e.message); }
  });
  on("#mjoin", "click", async () => {
    if (pin.value.length !== 6) { toast(t("code_6")); return; }
    try { const r = await api("/api/mafia/join", { json: { pin: pin.value, emoji: avatar } });
      go(mafiaPlayScreen, { game_id: r.game_id, player_id: r.player_id }, true);
    } catch (e) { haptic("error"); toast(e.message); }
  });
}

// плитки живых игроков для выбора цели
function mafiaTargets(d, excludeSelf) {
  return `<div class="mtargets">` + d.players.filter(p => p.alive && (!excludeSelf || p.id !== d.me.id))
    .map(p => `<button class="mtile" data-t="${p.id}">${p.emoji} <span class="ell">${esc(p.name)}</span></button>`).join("") + `</div>`;
}
function mafiaRoster(d) {
  const M = mafiaT();
  return `<div class="mroster">` + d.players.map(p => `
    <div class="mrow ${p.alive ? "" : "out"}">${p.emoji} <span class="grow ell">${esc(p.name)}</span>
      ${p.role ? `<span class="muted small">${MAFIA_ROLE_EMOJI[p.role] || ""} ${mafiaRoleName(p.role)}</span>` : `<span class="muted small">${p.alive ? M.alive_word : M.dead_word}</span>`}
    </div>`).join("") + `</div>`;
}

// ---- игровой экран «Мафии»
async function mafiaPlayScreen({ game_id, player_id }) {
  const M = mafiaT();
  let deadline = 0, busy = false, lastSig = "", dayPick = "";  // dayPick — минуты (пусто = по умолчанию)
  async function post(path, target) {
    if (busy) return; busy = true; haptic("success");
    try { await api(`/api/mafia/${game_id}/${path}?player_id=${player_id}`, { json: { target_id: target } }); }
    catch (e) { toast(e.message); }
    busy = false; load();
  }
  async function load() {
    let d;
    try { d = await api(`/api/mafia/${game_id}/play?player_id=${player_id}`); } catch (e) { return; }
    const timed = d.phase === "night" || d.phase === "day" || d.phase === "vote";
    if (timed) deadline = Date.now() + (d.remaining_ms || 0);  // синхронизируем таймер каждый опрос
    // Перерисовываем ТОЛЬКО при реальном изменении состояния — иначе экран мигает (таймер крутит отдельный интервал).
    const sig = JSON.stringify({ ...d, remaining_ms: 0 });
    if (sig === lastSig) return;
    lastSig = sig;
    const scroll = window.scrollY;
    const timer = timed ? `<div class="mtimer"><span id="mt"></span></div>` : "";
    const forceBtn = (d.is_host && timed) ? `<button class="btn secondary" id="mforce">${M.force_next}</button>` : "";
    const endBtn = (d.is_host && d.phase !== "ended") ? `<button class="link danger" id="mend" style="margin-top:14px">${M.end_btn}</button>` : "";
    let html = "";
    if (d.phase === "lobby") {
      const daySel = d.is_host ? `
        <label class="muted small" style="display:block;margin-top:8px">${M.day_time}</label>
        <input id="mday" class="field" type="number" min="1" max="60" inputmode="numeric"
               placeholder="${M.min_ph}" value="${dayPick}">` : "";
      html = `
        <p class="muted small" style="text-align:center;margin:0">${mafiaT().pin_title}</p>
        <div class="big-code">${d.pin.slice(0, 3)} ${d.pin.slice(3)}</div>
        <p class="muted small" style="text-align:center">${d.players_count} ${M.players_word}</p>
        <div class="chips">${d.players.map(p => `<span class="chip">${p.emoji} ${esc(p.name)}</span>`).join("")}</div>
        ${d.is_host
          ? `${daySel}<button class="btn" id="mstart" ${d.can_start ? "" : "disabled"}>${M.start_btn}</button>
             ${d.can_start ? "" : `<p class="muted small" style="text-align:center">${M.need_more.replace("{n}", d.min_players)}</p>`}`
          : `<p class="muted" style="text-align:center">${M.lobby_wait}</p>`}`;
    } else if (d.phase === "ended") {
      const town = d.result.winner === "town";
      html = `<div class="verdict ${town ? "ok" : "bad"}">${town ? M.win_town : M.win_mafia}</div>
        <h2>${M.roles_reveal}</h2>${mafiaRoster({ players: d.result.roles.map(r => ({ ...r, id: 0 })) })}
        <button class="btn" id="mhome">${quizT().home_btn}</button>`;
    } else {
      // night / day / vote — общий каркас
      const head = { night: `🌙 ${M.night_title}`, day: `☀️ ${M.day_title}`, vote: `🗳 ${M.vote_title}` }[d.phase];
      let body = "";
      if (!d.me.alive) {
        body = `<div class="card" style="text-align:center">💀 ${M.dead} · ${M.spectating}</div>${mafiaRoster(d)}`;
      } else if (d.phase === "night") {
        const nt = d.night;
        if (!nt.can_act) body = `<div class="card" style="text-align:center">${M.civ_sleep}</div>`;
        else if (nt.kind === "kill") {
          const mates = (nt.mates || []);
          body = `<p class="tc" style="margin:4px 0">${M.mafia_kill}</p>
            <p class="muted small tc">${mates.length ? M.mates + ": " + mates.map(m => m.emoji + " " + esc(m.name)).join(", ") : M.mafia_alone}</p>
            ${mafiaTargets(d, true)}`;
        } else if (nt.kind === "heal") body = `<p class="tc" style="margin:4px 0">${M.doc_heal}</p>${mafiaTargets(d, false)}`;
        else if (nt.kind === "check") {
          body = `<p class="tc" style="margin:4px 0">${M.comm_check}</p>${mafiaTargets(d, true)}`;
          if (nt.check_result) body += `<div class="card" style="text-align:center">${nt.check_result === "mafia" ? M.check_mafia : M.check_not}</div>`;
        }
      } else if (d.phase === "day") {
        const k = d.day.killed;
        body = `<div class="card" style="text-align:center">${k ? `${M.killed_msg}: ${k.emoji} <b>${esc(k.name)}</b> <span class="muted">(${mafiaRoleName(k.role)})</span>` : M.nobody_killed}</div>
          <p class="tc muted">${M.discuss}</p>${mafiaRoster(d)}`;
      } else if (d.phase === "vote") {
        body = `<p class="tc" style="margin:4px 0">${M.vote_pick}</p>` +
          `<div class="mtargets">` + d.players.filter(p => p.alive).map(p =>
            `<button class="mtile ${d.vote.voted === p.id ? "sel" : ""}" data-t="${p.id}">${p.emoji} <span class="ell">${esc(p.name)}</span>${d.vote.tally[p.id] ? `<b class="mvotes">${d.vote.tally[p.id]}</b>` : ""}</button>`).join("") + `</div>`;
      }
      const myrole = `<div class="mrole r-${d.me.role}">${MAFIA_ROLE_EMOJI[d.me.role]} ${M.you_are}: <b>${mafiaRoleName(d.me.role)}</b></div>`;
      html = `<h2 class="tc" style="margin:4px 0">${head}</h2>${timer}${myrole}${body}${forceBtn}`;
    }
    $app.innerHTML = html + endBtn;
    window.scrollTo(0, scroll);
    const mday = document.getElementById("mday");
    if (mday) mday.addEventListener("input", () => { dayPick = mday.value; });  // сохраняем ввод между опросами
    on("#mstart", "click", async () => {
      const mins = mday ? parseInt(mday.value, 10) : NaN;
      const ds = mins > 0 ? Math.min(mins, 60) * 60 : undefined;  // минуты → секунды (пусто = по умолчанию)
      try { await api(`/api/mafia/${game_id}/start`, { json: ds ? { day_seconds: ds } : {} }); }
      catch (e) { toast(e.message); } load();
    });
    on("#mforce", "click", async () => { try { await api(`/api/mafia/${game_id}/force`, { method: "POST" }); } catch (e) { toast(e.message); } load(); });
    on("#mhome", "click", home);
    on("#mend", "click", async () => { if (!confirm(M.end_btn + "?")) return; try { await api(`/api/mafia/${game_id}/end`, { method: "POST" }); } catch (e) { toast(e.message); } load(); });
    onAll(".mtargets .mtile", "click", el => post(d.phase === "vote" ? "vote" : "action", +el.dataset.t));
    // подсветка своего ночного выбора
    if (d.phase === "night" && d.night && d.night.acted) {
      const b = $app.querySelector(`.mtile[data-t="${d.night.acted}"]`); if (b) b.classList.add("sel");
    }
    clearInterval(mafiaPlayScreen._tick);
    mafiaPlayScreen._tick = setInterval(() => {
      const el = document.getElementById("mt"); if (!el) return;
      el.textContent = Math.ceil(Math.max(0, (deadline - Date.now()) / 1000)) + "s";
    }, 250);
    timers.push(mafiaPlayScreen._tick);
  }
  render(`<div class="center muted">${t("loading")}</div>`);
  await load();
  timers.push(setInterval(load, 1500));
}

/* ================================================================ создание песни */

const SONG = {
  ru: {
    title: "🎵 Создать песню", topic_ph: "О чём песня? Напишите тему",
    style_label: "Стиль", lang_label: "Язык песни",
    styles: { pop: "Поп", rap: "Рэп", kids: "Детская", epic: "Эпичная", lyric: "Лирическая", folk: "Народная" },
    paid_note: "💰 Платно для всех: {p} сум — спишется с баланса при создании.",
    create: "🎵 Создать", need_topic: "Напишите тему песни.",
    queued: "🎵 Песня генерируется! Готовый файл придёт в чат с ботом (это займёт пару минут).",
  },
  uz: {
    title: "🎵 Qo'shiq yaratish", topic_ph: "Qo'shiq nima haqida? Mavzuni yozing",
    style_label: "Uslub", lang_label: "Qo'shiq tili",
    styles: { pop: "Pop", rap: "Rep", kids: "Bolalar", epic: "Epik", lyric: "Lirik", folk: "Xalq" },
    paid_note: "💰 Hamma uchun pullik: {p} so'm — yaratishda balansdan yechiladi.",
    create: "🎵 Yaratish", need_topic: "Qo'shiq mavzusini yozing.",
    queued: "🎵 Qo'shiq tayyorlanmoqda! Tayyor fayl bot chatiga keladi (bir necha daqiqa).",
  },
  en: {
    title: "🎵 Create a song", topic_ph: "What's the song about? Enter a topic",
    style_label: "Style", lang_label: "Song language",
    styles: { pop: "Pop", rap: "Rap", kids: "Kids", epic: "Epic", lyric: "Lyrical", folk: "Folk" },
    paid_note: "💰 Paid for everyone: {p} so'm — charged from your balance on create.",
    create: "🎵 Create", need_topic: "Enter a song topic.",
    queued: "🎵 Your song is being generated! The file will arrive in the bot chat (a couple of minutes).",
  },
};
function songT() { return SONG[LANG] || SONG.ru; }

async function songScreen() {
  const S = songT();
  const price = (ME.prices && ME.prices.song) || 0;
  let style = "pop", lang = LANG;
  render(`
    ${langBar()}
    <h1>${S.title}</h1>
    <div class="card">
      <input id="stopic" class="field" placeholder="${esc(S.topic_ph)}" maxlength="200" autocomplete="off">
      <label class="muted small" style="display:block;margin-top:8px">${S.style_label}</label>
      <div class="chips" id="sstyle">
        ${Object.entries(S.styles).map(([k, v]) => `<span class="chip ${k === style ? "on" : ""}" data-s="${k}">${v}</span>`).join("")}
      </div>
      <label class="muted small" style="display:block;margin-top:6px">${S.lang_label}</label>
      <div class="langpick" id="slang">
        ${["ru", "uz", "en"].map(l => `<button class="lbtn ${l === lang ? "on" : ""}" data-l="${l}">${l === "ru" ? "🇷🇺 Рус" : l === "uz" ? "🇺🇿 Ўзб" : "🇬🇧 Eng"}</button>`).join("")}
      </div>
      <p class="muted small" style="margin:12px 0 4px">${S.paid_note.replace("{p}", fmtSum(price))}</p>
      <button class="btn" id="smake">${S.create}</button>
    </div>
  `);
  onAll("#sstyle .chip", "click", el => { style = el.dataset.s; $app.querySelectorAll("#sstyle .chip").forEach(c => c.classList.toggle("on", c === el)); });
  onAll("#slang .lbtn", "click", el => { lang = el.dataset.l; $app.querySelectorAll("#slang .lbtn").forEach(b => b.classList.toggle("on", b === el)); });
  on("#smake", "click", async () => {
    const topic = (document.getElementById("stopic").value || "").trim();
    if (!topic) { toast(S.need_topic); return; }
    const styleName = (songT().styles[style]) || style;
    const btn = document.getElementById("smake"); btn.disabled = true;
    try {
      await api("/api/ai/song", { json: { topic, style: styleName, lang } });
      haptic("success"); toast(S.queued);
      try { tg && tg.close(); } catch (e) {}  // уходим в чат бота, куда придёт файл
      home();
    } catch (e) { haptic("error"); toast(e.message); btn.disabled = false; }
  });
}

boot();
