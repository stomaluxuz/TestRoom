"""Локализация интерфейса бота (uz / ru / en). Этап 1: вход, меню, кнопки, регистрация.

t(key, lang) — строка на нужном языке; detect_lang — язык по коду Telegram;
BTN — тексты главных кнопок по языку; BTN_ALL — множества всех переводов кнопки
(для фильтров aiogram, чтобы кнопка ловилась на любом языке)."""
from __future__ import annotations

LANGS = ("uz", "ru", "en")
DEFAULT_LANG = "ru"


def detect_lang(code: str | None) -> str:
    """Язык по Telegram language_code ('uz', 'ru', 'en-US' …). По умолчанию — русский."""
    c = (code or "").lower()
    if c.startswith("uz"):
        return "uz"
    if c.startswith("en"):
        return "en"
    if c.startswith("ru"):
        return "ru"
    return DEFAULT_LANG


# Тексты главных кнопок (reply-клавиатура).
BTN = {
    "pres": {
        "ru": "🖥 Создать презентацию", "uz": "🖥 Taqdimot yaratish", "en": "🖥 Create presentation",
    },
    "test": {
        "ru": "📝 Создать тест", "uz": "📝 Test yaratish", "en": "📝 Create test",
    },
    "balance": {
        "ru": "💰 Мой баланс", "uz": "💰 Balansim", "en": "💰 My balance",
    },
    "topup": {
        "ru": "💳 Пополнить баланс", "uz": "💳 Balansni to'ldirish", "en": "💳 Top up balance",
    },
}
# Множества всех переводов каждой кнопки — для F.text.in_(...), чтобы ловить на любом языке.
BTN_ALL = {name: frozenset(v.values()) for name, v in BTN.items()}


def btn(name: str, lang: str) -> str:
    return BTN.get(name, {}).get(lang) or BTN.get(name, {}).get(DEFAULT_LANG, "")


_T = {
    "blocked": {
        "ru": "Доступ заблокирован.",
        "uz": "Kirish bloklangan.",
        "en": "Access is blocked.",
    },
    "welcome_name": {
        "ru": "Добро пожаловать! 👋\n\nНапишите ваши <b>Фамилию и Имя</b> полностью.\n"
              "Их увидит преподаватель в результатах тестов.\n\n<i>Например: Каримов Азиз</i>",
        "uz": "Xush kelibsiz! 👋\n\n<b>Familiya va Ismingizni</b> to'liq yozing.\n"
              "Ularni o'qituvchi test natijalarida ko'radi.\n\n<i>Masalan: Karimov Aziz</i>",
        "en": "Welcome! 👋\n\nPlease type your <b>full name</b>.\n"
              "Your teacher will see it in the test results.\n\n<i>Example: Karimov Aziz</i>",
    },
    "need_name": {
        "ru": "Сначала напишите ваши Фамилию и Имя: /start",
        "uz": "Avval Familiya va Ismingizni yozing: /start",
        "en": "First type your full name: /start",
    },
    "ai_off": {
        "ru": "🤖 ИИ пока не подключён. Обратитесь к администратору.",
        "uz": "🤖 AI hali ulanmagan. Administratorga murojaat qiling.",
        "en": "🤖 AI is not connected yet. Contact the administrator.",
    },
    "menu_hint_teacher": {
        "ru": "⬇️ Снизу закреплены кнопки: «📝 Создать тест» и «🖥 Создать презентацию».",
        "uz": "⬇️ Pastda tugmalar: «📝 Test yaratish» va «🖥 Taqdimot yaratish».",
        "en": "⬇️ Buttons below: “📝 Create test” and “🖥 Create presentation”.",
    },
    "menu_hint_student": {
        "ru": "⬇️ Снизу закреплены кнопки: «📝 Создать тест», «🖥 Создать презентацию», "
              "«💰 Мой баланс» и «💳 Пополнить баланс».",
        "uz": "⬇️ Pastda tugmalar: «📝 Test yaratish», «🖥 Taqdimot yaratish», "
              "«💰 Balansim» va «💳 Balansni to'ldirish».",
        "en": "⬇️ Buttons below: “📝 Create test”, “🖥 Create presentation”, "
              "“💰 My balance” and “💳 Top up balance”.",
    },
    "choose_language": {
        "ru": "🌐 Выберите язык интерфейса:",
        "uz": "🌐 Interfeys tilini tanlang:",
        "en": "🌐 Choose the interface language:",
    },
    # Первый экран для нового пользователя — одинаков на всех языках, он ещё не выбрал.
    "choose_language_first": {
        "ru": "🌐 Tilni tanlang / Выберите язык / Choose your language:",
        "uz": "🌐 Tilni tanlang / Выберите язык / Choose your language:",
        "en": "🌐 Tilni tanlang / Выберите язык / Choose your language:",
    },
    "lang_set": {
        "ru": "✅ Язык переключён на русский.",
        "uz": "✅ Til o'zbekchaga o'zgartirildi.",
        "en": "✅ Language switched to English.",
    },

    # ---- Главное меню (есть {name}) ----
    "menu_teacher": {
        "ru": "👨‍🏫 <b>{name}</b>, вы преподаватель.\n\n"
              "• Откройте приложение, чтобы запустить тест для группы по коду и смотреть результаты.\n"
              "• Чтобы добавить тест, просто отправьте сюда файл (.docx, .xlsx или .txt).",
        "uz": "👨‍🏫 <b>{name}</b>, siz o'qituvchisiz.\n\n"
              "• Guruh uchun testni kod orqali ishga tushirish va natijalarni ko'rish uchun ilovani oching.\n"
              "• Test qo'shish uchun shu yerga fayl yuboring (.docx, .xlsx yoki .txt).",
        "en": "👨‍🏫 <b>{name}</b>, you are a teacher.\n\n"
              "• Open the app to launch a test for your group by code and see the results.\n"
              "• To add a test, just send a file here (.docx, .xlsx or .txt).",
    },
    "menu_student": {
        "ru": "🎓 <b>{name}</b>, вы студент.\n\n"
              "• Когда преподаватель назовёт код — откройте приложение и введите его.\n"
              "• Можно загрузить свой тест файлом и прорешать его для тренировки.\n"
              "• Хотите проводить тесты для группы — нажмите «Стать преподавателем».",
        "uz": "🎓 <b>{name}</b>, siz talabasiz.\n\n"
              "• O'qituvchi kod aytganda — ilovani oching va kodni kiriting.\n"
              "• O'z testingizni fayl sifatida yuklab, mashq uchun yechishingiz mumkin.\n"
              "• Guruhga test o'tkazmoqchi bo'lsangiz — «O'qituvchi bo'lish» tugmasini bosing.",
        "en": "🎓 <b>{name}</b>, you are a student.\n\n"
              "• When the teacher gives a code — open the app and enter it.\n"
              "• You can upload your own test as a file and solve it for practice.\n"
              "• Want to run tests for a group — tap “Become a teacher”.",
    },

    # ---- Выбор роли при регистрации ----
    "role_choice": {
        "ru": "Кто вы? Роль можно сменить в любой момент.\n\n"
              "🎓 <b>Студент</b> — проходит тесты по коду и может прорешать свой тест для тренировки.\n"
              "👨‍🏫 <b>Преподаватель</b> — создаёт тесты и проводит их для группы по коду.",
        "uz": "Siz kimsiz? Rolni istalgan vaqtda o'zgartirish mumkin.\n\n"
              "🎓 <b>Talaba</b> — kod orqali testlar topshiradi va mashq uchun o'z testini yecha oladi.\n"
              "👨‍🏫 <b>O'qituvchi</b> — testlar yaratadi va guruh uchun kod orqali o'tkazadi.",
        "en": "Who are you? You can change the role anytime.\n\n"
              "🎓 <b>Student</b> — takes tests by code and can solve their own test for practice.\n"
              "👨‍🏫 <b>Teacher</b> — creates tests and runs them for a group by code.",
    },
    "role_btn_student": {"ru": "🎓 Я студент", "uz": "🎓 Men talabaman", "en": "🎓 I'm a student"},
    "role_btn_teacher": {"ru": "👨‍🏫 Я преподаватель", "uz": "👨‍🏫 Men o'qituvchiman", "en": "👨‍🏫 I'm a teacher"},
    "name_saved": {
        "ru": "Готово, <b>{name}</b> ✅",
        "uz": "Tayyor, <b>{name}</b> ✅",
        "en": "Done, <b>{name}</b> ✅",
    },
    "ask_new_name": {
        "ru": "Напишите новые Фамилию и Имя:",
        "uz": "Yangi Familiya va Ismingizni yozing:",
        "en": "Type your new full name:",
    },

    # ---- Общие ----
    "price_hint": {
        "ru": "\n\n💳 Стоимость: {amount} (спишется с баланса при создании).",
        "uz": "\n\n💳 Narxi: {amount} (yaratishda balansdan yechiladi).",
        "en": "\n\n💳 Price: {amount} (charged from your balance on creation).",
    },
    "num_prompt": {
        "ru": "Напишите число, например 10.",
        "uz": "Son yozing, masalan 10.",
        "en": "Type a number, e.g. 10.",
    },
    "queue_note": {
        "ru": " Много запросов — вы в очереди, подождите.",
        "uz": " So'rovlar ko'p — navbatdasiz, kuting.",
        "en": " Many requests — you're in the queue, please wait.",
    },
    "paid_note": {
        "ru": " Списано {amount}.",
        "uz": " {amount} yechildi.",
        "en": " {amount} charged.",
    },

    # ---- Создание теста ----
    "t_topic_prompt": {
        "ru": "📝 Напишите <b>тему теста</b> (например: «Кариес» или «Кости черепа»).\n"
              "Или пришлите <b>файл</b> (PDF, Word, PowerPoint, TXT) либо вставьте <b>текст</b> — "
              "тогда составлю вопросы <b>строго по вашему материалу</b>.",
        "uz": "📝 <b>Test mavzusini</b> yozing (masalan: «Karies» yoki «Bosh suyagi suyaklari»).\n"
              "Yoki <b>fayl</b> yuboring (PDF, Word, PowerPoint, TXT) yoxud <b>matn</b> joylang — "
              "shunda savollarni <b>faqat sizning materialingiz asosida</b> tuzaman.",
        "en": "📝 Type the <b>test topic</b> (e.g. “Caries” or “Skull bones”).\n"
              "Or send a <b>file</b> (PDF, Word, PowerPoint, TXT) or paste <b>text</b> — "
              "then I'll build questions <b>strictly from your material</b>.",
    },
    "t_material_note": {
        "ru": "📄 Принял текст как материал — составлю строго по нему. ",
        "uz": "📄 Matnni material sifatida qabul qildim — faqat shu asosda tuzaman. ",
        "en": "📄 Got the text as material — I'll build strictly from it. ",
    },
    "t_lang_q": {
        "ru": "На каком <b>языке</b> составить тест?",
        "uz": "Testni qaysi <b>tilda</b> tuzay?",
        "en": "In which <b>language</b> should I build the test?",
    },
    "t_file_wrong_ext": {
        "ru": "Пришлите файл <b>.pdf</b>, <b>.docx</b>, <b>.pptx</b> или <b>.txt</b> — "
              "или напишите тему текстом.",
        "uz": "<b>.pdf</b>, <b>.docx</b>, <b>.pptx</b> yoki <b>.txt</b> fayl yuboring — "
              "yoki mavzuni matn bilan yozing.",
        "en": "Send a <b>.pdf</b>, <b>.docx</b>, <b>.pptx</b> or <b>.txt</b> file — "
              "or type the topic as text.",
    },
    "file_too_big": {
        "ru": "Файл больше 10 МБ.",
        "uz": "Fayl 10 MB dan katta.",
        "en": "The file is larger than 10 MB.",
    },
    "reading_file": {
        "ru": "⏳ Читаю файл…",
        "uz": "⏳ Faylni o'qiyapman…",
        "en": "⏳ Reading the file…",
    },
    "file_read_fail": {
        "ru": "❌ Не удалось прочитать файл. Пришлите другой или напишите тему.",
        "uz": "❌ Faylni o'qib bo'lmadi. Boshqasini yuboring yoki mavzuni yozing.",
        "en": "❌ Couldn't read the file. Send another or type the topic.",
    },
    "file_no_text": {
        "ru": "В файле не нашлось текста (возможно, это скан-картинки). "
              "Пришлите текстовый файл или напишите тему вручную.",
        "uz": "Faylda matn topilmadi (ehtimol bu skan-rasmlar). "
              "Matnli fayl yuboring yoki mavzuni qo'lda yozing.",
        "en": "No text found in the file (it may be scanned images). "
              "Send a text file or type the topic manually.",
    },
    "t_material_accepted": {
        "ru": "📄 Принял материал ({n} символов) — составлю тест строго по нему. На каком <b>языке</b>?",
        "uz": "📄 Material qabul qilindi ({n} belgi) — testni faqat shu asosda tuzaman. Qaysi <b>tilda</b>?",
        "en": "📄 Got the material ({n} characters) — I'll build the test strictly from it. In which <b>language</b>?",
    },
    "t_count_q": {
        "ru": "Сколько вопросов сделать? Напишите число (например 10, максимум 40).",
        "uz": "Nechta savol tuzay? Son yozing (masalan 10, ko'pi bilan 40).",
        "en": "How many questions? Type a number (e.g. 10, max 40).",
    },
    "t_difficulty_q": {
        "ru": "Какая <b>сложность</b> теста?\n\n🟢 Лёгкий — базовые факты\n"
              "🟡 Средний — понимание темы\n🔴 Сложный — глубокие вопросы, похожие варианты",
        "uz": "Test <b>qiyinligi</b> qanday bo'lsin?\n\n🟢 Oson — asosiy faktlar\n"
              "🟡 O'rta — mavzuni tushunish\n🔴 Qiyin — chuqur savollar, o'xshash variantlar",
        "en": "What <b>difficulty</b> for the test?\n\n🟢 Easy — basic facts\n"
              "🟡 Medium — understanding\n🔴 Hard — deep questions, similar options",
    },
    "diff_easy": {"ru": "🟢 Лёгкий", "uz": "🟢 Oson", "en": "🟢 Easy"},
    "diff_medium": {"ru": "🟡 Средний", "uz": "🟡 O'rta", "en": "🟡 Medium"},
    "diff_hard": {"ru": "🔴 Сложный", "uz": "🔴 Qiyin", "en": "🔴 Hard"},
    "t_src_material": {
        "ru": " по вашему материалу",
        "uz": " sizning materialingiz asosida",
        "en": " from your material",
    },
    "t_generating": {
        "ru": "⏳ Генерирую тест {label} на {n} вопросов{src}…",
        "uz": "⏳ {label} testini {n} ta savolga tuzyapman{src}…",
        "en": "⏳ Generating a {label} test with {n} questions{src}…",
    },
    "t_build_fail": {
        "ru": "❌ Не получилось собрать тест, попробуйте другую тему.",
        "uz": "❌ Testni tuzib bo'lmadi, boshqa mavzuni sinab ko'ring.",
        "en": "❌ Couldn't build the test, try another topic.",
    },
    "t_count_note": {
        "ru": " (запрашивали {n}, собрано {count})",
        "uz": " (so'ralgan {n}, tuzilgan {count})",
        "en": " (requested {n}, built {count})",
    },
    "t_src_strict": {
        "ru": "\n📄 Строго по вашему материалу",
        "uz": "\n📄 Faqat sizning materialingiz asosida",
        "en": "\n📄 Strictly from your material",
    },
    "t_result_caption": {
        "ru": "📄 Готово — {count} вопросов{note}.{paid} Проверьте файл.{src}",
        "uz": "📄 Tayyor — {count} ta savol{note}.{paid} Faylni tekshiring.{src}",
        "en": "📄 Done — {count} questions{note}.{paid} Check the file.{src}",
    },
    "t_student_note": {
        "ru": "Это ваш файл для учёбы 📚 В приложении тест не сохраняется — "
              "запускать тесты для группы могут только преподаватели.",
        "uz": "Bu — o'qish uchun faylingiz 📚 Ilovada test saqlanmaydi — "
              "guruhga test o'tkazishni faqat o'qituvchilar qila oladi.",
        "en": "This is your study file 📚 The test isn't saved in the app — "
              "only teachers can run tests for a group.",
    },
    "t_subject_q": {
        "ru": "В какой <b>предмет</b> сохранить этот тест?",
        "uz": "Bu testni qaysi <b>fanga</b> saqlay?",
        "en": "Which <b>subject</b> should I save this test under?",
    },
    "btn_new_subject": {"ru": "➕ Новый предмет", "uz": "➕ Yangi fan", "en": "➕ New subject"},
    "t_new_subject_prompt": {
        "ru": "Напишите название нового предмета:",
        "uz": "Yangi fan nomini yozing:",
        "en": "Type the new subject name:",
    },
    "t_saved": {
        "ru": "✅ Сохранено ({count} вопросов). Можно запускать в приложении.\n<i>{title}</i>",
        "uz": "✅ Saqlandi ({count} ta savol). Ilovada ishga tushirish mumkin.\n<i>{title}</i>",
        "en": "✅ Saved ({count} questions). You can launch it in the app.\n<i>{title}</i>",
    },
    "t_stale": {
        "ru": "Данные теста устарели, создайте заново.",
        "uz": "Test ma'lumotlari eskirgan, qaytadan yarating.",
        "en": "The test data is out of date, create it again.",
    },
    "btn_open_in_app": {"ru": "▶️ Открыть в приложении", "uz": "▶️ Ilovada ochish", "en": "▶️ Open in the app"},

    # ---- Создание презентации ----
    "p_topic_prompt": {
        "ru": "🖥 Напишите <b>тему презентации</b> (например: «Анатомия сердца»).",
        "uz": "🖥 <b>Taqdimot mavzusini</b> yozing (masalan: «Yurak anatomiyasi»).",
        "en": "🖥 Type the <b>presentation topic</b> (e.g. “Heart anatomy”).",
    },
    "p_lang_q": {
        "ru": "На каком <b>языке</b> сделать презентацию?",
        "uz": "Taqdimotni qaysi <b>tilda</b> tayyorlay?",
        "en": "In which <b>language</b> should I make the presentation?",
    },
    "p_fio_q": {
        "ru": "Напишите <b>ФИО</b> (кто выполнил):",
        "uz": "<b>F.I.Sh.</b> yozing (kim bajardi):",
        "en": "Type the <b>full name</b> (who prepared it):",
    },
    "p_group_q": {
        "ru": "Напишите <b>номер группы</b>:",
        "uz": "<b>Guruh raqamini</b> yozing:",
        "en": "Type the <b>group number</b>:",
    },
    "p_count_q": {
        "ru": "Сколько слайдов? Напишите число (максимум 20).",
        "uz": "Nechta slayd? Son yozing (ko'pi bilan 20).",
        "en": "How many slides? Type a number (max 20).",
    },
    "p_generating": {
        "ru": "⏳ Генерирую презентацию и подбираю фото…",
        "uz": "⏳ Taqdimot tayyorlab, rasm tanlayapman…",
        "en": "⏳ Generating the presentation and picking photos…",
    },
    "p_result_caption": {
        "ru": "Готовая презентация ✅ Тема: {topic}.{paid} Откройте в PowerPoint / Google Slides.{src}",
        "uz": "Tayyor taqdimot ✅ Mavzu: {topic}.{paid} PowerPoint / Google Slides'da oching.{src}",
        "en": "Presentation ready ✅ Topic: {topic}.{paid} Open in PowerPoint / Google Slides.{src}",
    },

    # ---- Баланс и пополнение ----
    "b_teacher_free": {
        "ru": "Для преподавателей создание тестов и презентаций бесплатно ✅",
        "uz": "O'qituvchilar uchun test va taqdimot yaratish bepul ✅",
        "en": "Creating tests and presentations is free for teachers ✅",
    },
    "b_balance": {
        "ru": "💰 Ваш баланс: <b>{balance}</b>\n\n"
              "Цены:\n🖥 Презентация — {pres}\n📝 Тест — {test}\n\n"
              "Пополнить — кнопка ниже или «💳 Пополнить баланс».",
        "uz": "💰 Balansingiz: <b>{balance}</b>\n\n"
              "Narxlar:\n🖥 Taqdimot — {pres}\n📝 Test — {test}\n\n"
              "To'ldirish — pastdagi tugma yoki «💳 Balansni to'ldirish».",
        "en": "💰 Your balance: <b>{balance}</b>\n\n"
              "Prices:\n🖥 Presentation — {pres}\n📝 Test — {test}\n\n"
              "Top up — the button below or “💳 Top up balance”.",
    },
    "b_teacher_free_topup": {
        "ru": "Для преподавателей всё бесплатно — пополнять баланс не нужно ✅",
        "uz": "O'qituvchilar uchun hammasi bepul — balansni to'ldirish shart emas ✅",
        "en": "Everything is free for teachers — no need to top up ✅",
    },
    "b_topup_q": {
        "ru": "💳 На какую сумму пополнить баланс?",
        "uz": "💳 Balansni qancha summaga to'ldiramiz?",
        "en": "💳 How much would you like to top up?",
    },
    "b_pay_instructions": {
        "ru": "💳 Пополнение на <b>{amount}</b>\n\n"
              "Переведите эту сумму на карту (Humo/Uzcard):\n<code>{card}</code>\n{holder}\n\n"
              "После перевода нажмите «✅ Я оплатил» и <b>обязательно</b> пришлите скриншот чека.",
        "uz": "💳 <b>{amount}</b> to'ldirish\n\n"
              "Ushbu summani kartaga o'tkazing (Humo/Uzcard):\n<code>{card}</code>\n{holder}\n\n"
              "O'tkazgach «✅ To'ladim» tugmasini bosing va <b>albatta</b> chek skrinshotini yuboring.",
        "en": "💳 Top up of <b>{amount}</b>\n\n"
              "Transfer this amount to the card (Humo/Uzcard):\n<code>{card}</code>\n{holder}\n\n"
              "After the transfer tap “✅ I paid” and <b>be sure</b> to send a receipt screenshot.",
    },
    "btn_paid": {"ru": "✅ Я оплатил", "uz": "✅ To'ladim", "en": "✅ I paid"},
    "b_receipt_q": {
        "ru": "📸 Пришлите <b>скриншот чека</b> об оплате — это обязательно. "
              "Без чека заявку подтвердить нельзя.",
        "uz": "📸 To'lov <b>chek skrinshotini</b> yuboring — bu majburiy. "
              "Cheksiz arizani tasdiqlab bo'lmaydi.",
        "en": "📸 Send a <b>receipt screenshot</b> of the payment — it's required. "
              "Without a receipt the request can't be confirmed.",
    },
    "b_amount_lost": {
        "ru": "Сумма не распознана, начните заново: «💳 Пополнить баланс».",
        "uz": "Summa aniqlanmadi, qaytadan boshlang: «💳 Balansni to'ldirish».",
        "en": "Amount not recognized, start again: “💳 Top up balance”.",
    },
    "b_submitted": {
        "ru": "✅ Заявка отправлена! Админ проверит оплату и зачислит баланс — обычно это быстро. "
              "Баланс смотрите по кнопке «💰 Мой баланс».",
        "uz": "✅ Ariza yuborildi! Admin to'lovni tekshirib, balansni to'ldiradi — odatda tez. "
              "Balansni «💰 Balansim» tugmasi orqali ko'ring.",
        "en": "✅ Request sent! An admin will verify the payment and credit your balance — usually quickly. "
              "Check your balance via “💰 My balance”.",
    },
    "b_receipt_need_photo": {
        "ru": "📸 Нужен именно <b>фото-скриншот чека</b> об оплате — пришлите его. "
              "Без чека заявку подтвердить нельзя.",
        "uz": "📸 Aynan to'lov <b>chek foto-skrinshoti</b> kerak — yuboring. "
              "Cheksiz arizani tasdiqlab bo'lmaydi.",
        "en": "📸 A <b>photo screenshot of the receipt</b> is required — please send it. "
              "Without a receipt the request can't be confirmed.",
    },
}


def t(key: str, lang: str) -> str:
    row = _T.get(key, {})
    return row.get(lang) or row.get(DEFAULT_LANG) or key
