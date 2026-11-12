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
  document.body.classList.remove("testing");  // по умолчанию подпись-ссылка видна
  $app.innerHTML = html; window.scrollTo(0, 0); bindLang();
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
  if (!tg) return;
  if (navStack.length > 1 && !attemptCtx) tg.BackButton.show(); else tg.BackButton.hide();
}
if (tg) tg.BackButton.onClick(back);

/* ---------------------------------------------------------------- старт */

async function boot() {
  if (tg) { tg.ready(); tg.expand(); try { tg.disableVerticalSwipes(); } catch (e) {} }
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
  if (!ME.full_name) go(nameScreen); else home();
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
    </div>` : ""}
  `);
  on("#editname", "click", () => go(nameScreen));
  on("#editwork", "click", () => go(universityPickerScreen, { edit: true }));
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

async function studentHome() {
  try { ME = await api("/api/me"); } catch (e) {}
  const extra = ME.is_teacher ? "" : `
    <div class="item" id="library"><span class="ico">📚</span><div class="grow">${libT().lib}</div><span class="muted">›</span></div>
    <div class="item" id="mytests"><span class="ico">📖</span><div class="grow">${t("my_tests_training")}</div><span class="muted">›</span></div>
    <div class="item" id="upload"><span class="ico">📤</span><div class="grow">${t("upload_my_test")}</div></div>
    ${ME.teacher_pending
      ? `<p class="muted small">${t("pending_teacher")}</p>`
      : `<div class="item" id="torole"><span class="ico">👨‍🏫</span><div class="grow">${t("become_teacher")}</div></div>`}`;
  const PAYT = {
    ru: { bal: "Баланс", pres: "Презентация", test: "Тест", top: "💳 Пополнить баланс",
          hint: "Создание презентаций и тестов — платно. Пополнить баланс можно в чате бота." },
    uz: { bal: "Balans", pres: "Taqdimot", test: "Test", top: "💳 Balansni to'ldirish",
          hint: "Taqdimot va test yaratish — pullik. Balansni bot chatida to'ldirasiz." },
    en: { bal: "Balance", pres: "Presentation", test: "Test", top: "💳 Top up balance",
          hint: "Creating presentations and tests is paid. Top up your balance in the bot chat." },
  }[LANG] || null;
  const pr = ME.prices || { presentation: 0, test: 0 };
  const payCard = (!ME.is_teacher && ME.pays && PAYT) ? `
    <div class="card">
      <div class="row"><b>${PAYT.bal}</b><b>${fmtSum(ME.balance || 0)} сум</b></div>
      <p class="muted small" style="margin:6px 0">${PAYT.pres} — ${fmtSum(pr.presentation)} · ${PAYT.test} — ${fmtSum(pr.test)}</p>
      <button class="btn secondary" id="topup">${PAYT.top}</button>
      <p class="muted small" style="margin:6px 0 0">${PAYT.hint}</p>
    </div>` : "";
  render(`
    ${langBar()}
    <h1>${esc(ME.full_name)}</h1>
    <div class="card">
      <p class="muted small" style="margin:0 0 6px">${t("enter_code")}</p>
      <input id="code" class="code-input" inputmode="numeric" maxlength="6" placeholder="••••••" autocomplete="off">
      <button class="btn" id="join">${t("start_test")}</button>
    </div>
    ${payCard}
    <div class="item" id="presstudio"><span class="ico">🖥</span><div class="grow">${(PRESF[LANG] || PRESF.ru).title} (ИИ)</div><span class="muted">›</span></div>
    ${extra}
    <h2>${t("my_results")}</h2>
    <div id="hist" class="muted small">${t("loading")}</div>
    <button class="link" id="profile">${t("profile")}</button>
  `);
  const code = document.getElementById("code");
  code.addEventListener("input", () => { code.value = code.value.replace(/\D/g, "").slice(0, 6); });
  code.addEventListener("keydown", e => { if (e.key === "Enter") join(); });
  on("#join", "click", join);
  on("#presstudio", "click", () => go(presentationStudioScreen));
  on("#topup", "click", () => {
    toast("Откройте чат бота и нажмите «💳 Пополнить баланс»");
    try { tg && tg.close(); } catch (e) {}
  });
  on("#profile", "click", () => go(profileScreen));
  if (!ME.is_teacher) {
    on("#library", "click", () => go(libraryScreen));
    on("#mytests", "click", () => go(testsScreen));
    on("#upload", "click", () => go(uploadScreen));
    on("#torole", "click", () => go(universityPickerScreen));
  }
  async function join() {
    if (code.value.length !== 6) { toast(t("code_6")); return; }
    try {
      const st = await api("/api/student/join", { json: { code: code.value } });
      go(attemptScreen, { state: st });
    } catch (e) { haptic("error"); toast(e.message); }
  }
  try {
    const h = await api("/api/student/history");
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
  } catch (e) {}
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
  render(`
    <div class="row small"><span class="muted">${esc(state.subject)} · ${esc(state.test_title)}</span></div>
    <div class="row" style="margin-top:6px">
      <span>${t("question")} ${q.number} ${t("of")} ${state.total}</span>
      <span class="timer" id="timer">⏱ ${fmtTime(state.seconds_left)}</span>
    </div>
    <div class="bar"><span style="width:${Math.round(state.answered * 100 / state.total)}%"></span></div>
    ${rules}${warn}
    <div class="question">${esc(q.text)}</div>
    ${q.options.map((o, i) => `<div class="option" data-i="${i}">${String.fromCharCode(65 + i)}) ${esc(o)}</div>`).join("")}
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
    <h1>${esc(ME.full_name)}</h1>
    <div class="row" style="margin:-6px 0 12px"><span class="muted small">${t("teacher")}</span>
      <span class="badge ${ME.is_pro_plus || ME.plan === "pro" ? "pro" : ""}">${ME.is_pro_plus ? "💎 Pro+ " + new Date(ME.proplus_until).toLocaleDateString("ru-RU") : (ME.plan === "pro" ? t("plan_pro") + " " + new Date(ME.pro_until).toLocaleDateString("ru-RU") : t("plan_free"))}</span></div>
    ${a ? `<div class="banner" id="active"><b>${t("test_running")} · ${esc(a.group)}</b><br>
      <span class="small">${esc(a.test_title)} · ${t("code")} <b>${a.code}</b> · ${t("time_left")} <span id="aleft">${fmtTime(a.seconds_left)}</span></span></div>` : ""}
    <div class="item" id="tests"><span class="ico">📚</span><div class="grow">${t("my_tests")}</div></div>
    <div class="item" id="upload"><span class="ico">📤</span><div class="grow">${t("upload_test")}</div></div>
    <div class="item" id="history"><span class="ico">🕘</span><div class="grow">${t("history")}</div></div>
    <div class="item" id="presstudio"><span class="ico">🖥</span><div class="grow">${(PRESF[LANG] || PRESF.ru).title} (ИИ)</div><span class="muted">›</span></div>
    <div class="item" id="aichat"><span class="ico">💬</span><div class="grow">${t("ai_assistant")}</div>${ME.is_pro_plus || ME.is_admin ? "" : `<span class="badge pro">Pro+</span>`}<span class="muted">›</span></div>
    <div class="item" id="library"><span class="ico">📚</span><div class="grow">${libT().lib}</div><span class="muted">›</span></div>
    <div class="item" id="libupload"><span class="ico">⬆️</span><div class="grow">${libT().upload}</div></div>
    <div class="item" id="profile"><span class="ico">👤</span><div class="grow">${t("profile")}</div><span class="muted">›</span></div>
    ${ME.acting_as ? "" : `<div class="item" id="student"><span class="ico">🎓</span><div class="grow">${t("take_by_code")}</div></div>`}
    ${ME.is_admin && !ME.acting_as ? `<div class="item" id="admin"><span class="ico">🛠</span><div class="grow">${t("admin_panel")}</div><span class="muted">›</span></div>` : ""}
    ${ME.is_admin || ME.acting_as ? "" : `<div class="item" id="torole"><span class="ico">🎓</span><div class="grow">${t("become_student")}</div></div>`}
    <p class="muted small">${t("upload_via_bot")}</p>
  `);
  if (a) {
    on("#active", "click", () => go(liveScreen, { id: a.id }));
    const end = Date.now() + a.seconds_left * 1000;
    timers.push(setInterval(() => { const el = document.getElementById("aleft"); if (el) el.textContent = fmtTime((end - Date.now()) / 1000); }, 1000));
  }
  on("#tests", "click", () => go(testsScreen));
  on("#upload", "click", () => go(uploadScreen));
  on("#history", "click", () => go(historyScreen));
  on("#presstudio", "click", () => go(presentationStudioScreen));
  on("#aichat", "click", () => go(aiChatScreen));
  on("#library", "click", () => go(libraryScreen));
  on("#libupload", "click", () => go(libraryUploadScreen));
  on("#profile", "click", () => go(profileScreen));
  on("#student", "click", () => go(studentHome));
  on("#admin", "click", () => go(adminScreen));
  on("#torole", "click", switchToStudent);
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
    <button class="btn" id="upload">📤 ${t("upload_test")}</button>
  `);
  on("#t-act", "click", () => go(testsScreen, {}, true));
  on("#t-arc", "click", () => go(testsScreen, { archive: true }, true));
  on("#upload", "click", () => go(uploadScreen));
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
    <button class="btn" id="upload">📤 ${t("upload_to_subject")}</button>
    ${showArchive ? "" : `<button class="btn danger delsubj" data-id="${s.id}" data-n="${esc(s.name)}">🗑 ${t("del_subject")}</button>`}
  `);
  onAll(".ttoggle", "click", (el, e) => { e.stopPropagation(); el.classList.toggle("ell"); });
  onAll(".open", "click", el => go(testScreen, { id: +el.dataset.id }));
  on("#upload", "click", () => go(uploadScreen, { subject_id: s.id }));
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
    <div id="list">${test.questions.map((q, i) => `
      <div class="card" data-qi="${i}">
        <div class="row"><b>№${i + 1}</b><span><button class="link ed" data-qi="${i}">${t("edit_word")}</button></span></div>
        <div style="white-space:pre-wrap">${esc(q.text)}</div>
        <div class="small right">✓ ${esc(q.options[q.correct])}</div>
        <div class="muted small">${q.options.length} ${t("options_word")}</div>
      </div>`).join("")}</div>
    <button class="btn" id="add">${t("add_question")}</button>
  `);
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
      <button class="${tab === "cast" ? "on" : ""}" id="t4">📢 Рассылка</button>
      <button class="${tab === "log" ? "on" : ""}" id="t2">Журнал</button></div>
    <div id="body"></div>
  `);
  on("#t1", "click", () => go(adminScreen, { tab: "teachers" }, true));
  on("#t2", "click", () => go(adminScreen, { tab: "log" }, true));
  on("#t3", "click", () => go(adminScreen, { tab: "pay" }, true));
  on("#t4", "click", () => go(adminScreen, { tab: "cast" }, true));
  on("#t5", "click", () => go(adminScreen, { tab: "lib" }, true));
  on("#m-users", "click", () => go(adminMetricScreen, { metric: "users" }));
  on("#m-tests", "click", () => go(adminMetricScreen, { metric: "tests" }));
  on("#m-pres", "click", () => go(adminMetricScreen, { metric: "presentations" }));
  on("#m-rev", "click", () => go(adminMetricScreen, { metric: "revenue" }));
  on("#m-sess", "click", () => go(adminMetricScreen, { metric: "sessions" }));
  const body = document.getElementById("body");
  if (tab === "pay") { await paymentsTab(body); return; }
  if (tab === "lib") { await libraryTab(body); return; }
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
  renderPending(pending);
  renderSubs(subjects);
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

boot();
