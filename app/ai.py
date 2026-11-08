"""Генерация содержания (презентации и тесты) по теме через Claude (Anthropic)."""
from __future__ import annotations

import random

import anthropic

from .config import settings

# Разные «углы подачи» — чтобы у студентов одной группы с одинаковой темой
# получались РАЗНЫЕ презентации (не копии). Температуру API больше не принимает,
# поэтому разнообразие создаём вариацией самого запроса.
_ANGLES = [
    "Сделай акцент на практических примерах и клинических случаях.",
    "Построй структуру иначе обычного: начни с проблемы, затем переходи к решениям.",
    "Добавь конкретные факты, цифры, сравнения и классификации.",
    "Сделай упор на причинно-следственные связи и механизмы процессов.",
    "Используй другие примеры и формулировки, избегай шаблонных фраз.",
    "Сгруппируй материал по этапам/видам/категориям, где это уместно.",
    "Больше внимания удели ошибкам, осложнениям и способам их избежать.",
    "Подай тему через сравнение разных методов/подходов.",
]

SYSTEM_SLIDES = (
    "Ты помощник преподавателя вуза: составляешь ГЛУБОКИЕ, содержательные учебные презентации. "
    "Отвечай СТРОГО в следующем текстовом формате и ничего лишнего (без пояснений, без markdown-ограждений):\n"
    "- первая строка — краткий заголовок презентации;\n"
    "- вторая строка — короткий подзаголовок;\n"
    "- далее для КАЖДОГО слайда: строка «# Заголовок слайда», затем 4–6 пунктов, "
    "каждый с новой строки и начинается с «- »;\n"
    "- ОБЯЗАТЕЛЬНО после пунктов КАЖДОГО слайда (без пропусков) добавь строку "
    "«IMG: <2–4 слова на английском>» — это поисковый запрос фотографии;\n"
    "- в IMG опиши КОНКРЕТНЫЙ видимый объект/сцену по теме этого слайда, который реально "
    "найдётся на фото (термины бери на английском/латыни). Примеры: «IMG: human heart anatomy», "
    "«IMG: dental crown tooth», «IMG: bacteria microscope». НЕ абстракции (не «history», «process»).\n\n"
    "ГЛУБИНА (это главное — преподаватели жалуются на поверхностность):\n"
    "- каждый пункт несёт КОНКРЕТИКУ: термин с определением, цифру, дату, классификацию, "
    "механизм «как/почему это работает», причину-следствие или конкретный пример/случай — "
    "а НЕ общую фразу вроде «играет важную роль» или «имеет большое значение»;\n"
    "- раскрывай суть так, чтобы студент понял пункт БЕЗ преподавателя; избегай воды, "
    "банальностей и повторов между слайдами;\n"
    "- пункт — это одно ёмкое утверждение по существу, КОРОТКО (ориентир — одна строка, до ~110 "
    "символов); если мысль большая, РАЗБЕЙ её на два коротких пункта, а не пиши длинное предложение;\n"
    "- используй корректную профессиональную терминологию предмета;\n"
    "- весь текст (кроме строки IMG) — на том языке, который укажут."
)

SYSTEM_TEST = (
    "Ты составляешь учебные тесты с одним правильным ответом. "
    "Отвечай СТРОГО в формате и ничего лишнего (без пояснений, без markdown):\n"
    "- сделай РОВНО столько вопросов, сколько просят, и пронумеруй их подряд 1, 2, 3, …;\n"
    "- каждый вопрос: номер, точка, пробел, текст вопроса;\n"
    "- ровно 4 варианта, каждый с новой строки: «A) текст», «B) текст», «C) текст», «D) текст»;\n"
    "- перед буквой ПРАВИЛЬНОГО варианта поставь звёздочку, например «*B) текст»; правильный ровно один;\n"
    "- между вопросами одна пустая строка;\n"
    "- вопросы по существу темы, на том языке, который укажут.\n\n"
    "Пример ОДНОГО вопроса (только для демонстрации ФОРМАТА; язык бери из задания):\n"
    "1. Что является основной причиной кариеса?\n"
    "A) Вирусы\n"
    "*B) Кислотообразующие бактерии зубного налёта\n"
    "C) Грибковая инфекция\n"
    "D) Недостаток витамина C"
)

SYSTEM_CHAT = (
    "Ты — умный учебный ИИ-ассистент для студентов и преподавателей (в т.ч. медицина и "
    "стоматология). Помогай учиться: объясняй темы, отвечай на вопросы, помогай с задачами.\n\n"
    "ПРАВИЛА ПРО ИСТОЧНИКИ (очень важно):\n"
    "— Ссылайся на книгу ТОЛЬКО если ответ действительно взят из приведённых ниже выдержек, и "
    "называй источник ТОЧНО так, как написано в поле «Источник». Можешь процитировать короткую "
    "фразу из выдержки, чтобы её можно было найти в книге.\n"
    "— НИКОГДА не придумывай названия книг, авторов, номера страниц, глав или листов. Если точной "
    "страницы нет в данных — не называй её.\n"
    "— Если среди выдержек НЕТ ответа на вопрос (они не по теме) — прямо скажи: «В библиотеке по этой "
    "теме материалов нет», и отвечай из общих знаний, НЕ ссылаясь на библиотеку.\n"
    "— Если твой ответ опирается на РЕАЛЬНУЮ выдержку, а пользователь говорит, что ты ошибаешься — "
    "НЕ соглашайся автоматически. Перечитай выдержку: если она подтверждает твой ответ, вежливо и "
    "твёрдо настаивай и укажи точный источник для проверки. Признавай ошибку только если действительно "
    "ошибся. Не поддакивай ради вежливости.\n\n"
    "Отвечай кратко, по делу и дружелюбно."
)


# Языки генерации
_LANGS = {
    "ru": "русском",
    "uz": "узбекском (строго на латинице, lotin alifbosida)",
    "en": "английском (English)",
}


def _lang_instr(lang: str) -> str:
    return f"ВАЖНО: весь текст пиши на {_LANGS.get(lang, _LANGS['ru'])} языке."


def _context_block(context: str) -> str:
    """Блок с выдержками из библиотеки, который подставляем в начало запроса (RAG)."""
    if not context:
        return ""
    return (
        "Ниже — выдержки из ПРОВЕРЕННЫХ материалов библиотеки по теме. "
        "ОПИРАЙСЯ на них как на основной источник фактов (определения, термины, цифры, "
        "классификации, последовательности). Чего в выдержках нет — дополни своими знаниями, "
        "но НЕ противоречь источнику и не выдумывай фактов сверх него там, где он есть.\n\n"
        "=== МАТЕРИАЛЫ БИБЛИОТЕКИ ===\n"
        f"{context}\n"
        "=== КОНЕЦ МАТЕРИАЛОВ ===\n\n"
    )


def _chat_context_block(context: str) -> str:
    """Контекст для ЧАТА: выдержки могут быть нерелевантны, нельзя выдумывать источники."""
    if not context:
        return ""
    return (
        "Ниже — выдержки, найденные автоматически по запросу. Они МОГУТ быть нерелевантны. "
        "Используй их ТОЛЬКО если они действительно отвечают на вопрос; если они не по теме — "
        "игнорируй их и прямо скажи, что в библиотеке материала по этой теме нет. Ссылайся только "
        "на ТОЧНЫЕ названия из поля «Источник». Ничего не придумывай.\n\n"
        "=== ВЫДЕРЖКИ ИЗ БИБЛИОТЕКИ ===\n"
        f"{context}\n"
        "=== КОНЕЦ ВЫДЕРЖЕК ===\n\n"
    )


def _err(msg: str, status: int = 400):
    from .services import ServiceError

    return ServiceError(msg, status)


async def _ask(system: str, prompt: str, max_tokens: int = 4000) -> str:
    if not settings.anthropic_api_key:
        raise _err(
            "ИИ пока не подключён. Добавьте ANTHROPIC_API_KEY в файл .env, чтобы пользоваться режимом «по теме».",
            403,
        )
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        msg = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=max_tokens,
            output_config={"effort": "low"},  # простая задача — экономим токены
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIStatusError as e:
        raise _err(f"ИИ недоступен ({e.status_code}). Попробуйте позже.", 502)
    except anthropic.APIConnectionError:
        raise _err("Нет связи с ИИ. Проверьте интернет и попробуйте ещё раз.", 502)
    return "".join(b.text for b in msg.content if b.type == "text").strip()


CHAT_TOOLS = [
    {
        "name": "create_presentation",
        "description": "Создать презентацию (.pptx) по теме и отправить пользователю в чат с ботом. "
        "Вызывай, когда пользователь просит сделать/создать презентацию.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Тема презентации"},
                "slides": {"type": "integer", "description": "Сколько слайдов (по умолчанию 8)"},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "create_test",
        "description": "Создать тест по теме и отправить файл (.docx) пользователю в чат с ботом. "
        "Вызывай, когда пользователь просит сделать/создать тест.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Тема теста"},
                "count": {"type": "integer", "description": "Сколько вопросов (по умолчанию 10)"},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "create_document",
        "description": "Оформить готовый текст (статья, реферат, конспект, план) в Word (.docx) и отправить "
        "пользователю в чат с ботом. Сам напиши содержание и передай его в поле content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Заголовок документа"},
                "content": {"type": "string", "description": "Полный текст документа"},
            },
            "required": ["title", "content"],
        },
    },
]

SYSTEM_CHAT_TOOLS = (
    "\n\nУ тебя есть инструменты: создать презентацию, создать тест, оформить текст в Word — и все они "
    "ОТПРАВЛЯЮТ файл пользователю в чат с Telegram-ботом. Используй их ТОЛЬКО когда пользователь явно "
    "просит что-то создать/сделать/прислать файлом. Для обычных вопросов просто отвечай текстом, без "
    "инструментов. Если для создания не хватает данных (нет темы, числа слайдов/вопросов) — сначала "
    "переспроси, НЕ вызывай инструмент. После успешного вызова коротко подтверди, что файл отправлен в бот."
)


async def chat_with_tools(messages: list[dict], lang: str, context: str, execute) -> str:
    """Чат с инструментами: ИИ может создавать презентации/тесты/документы и слать их в бот.
    execute(name, input) -> str — выполняет инструмент (генерация + отправка) и возвращает краткий итог."""
    if not settings.anthropic_api_key:
        raise _err("ИИ пока не подключён. Обратитесь к администратору.", 403)
    system = SYSTEM_CHAT + SYSTEM_CHAT_TOOLS + "\n\n" + _lang_instr(lang)
    if context:
        system += "\n\n" + _chat_context_block(context)
    conv = [
        {"role": m["role"], "content": str(m["content"])[:4000]}
        for m in messages
        if m.get("content") and m.get("role") in ("user", "assistant")
    ][-10:]
    if not conv:
        raise _err("Пустой запрос.")
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    for _ in range(4):  # до 4 раундов инструментов
        try:
            resp = await client.messages.create(
                model=settings.anthropic_model, max_tokens=1500,
                system=system, messages=conv, tools=CHAT_TOOLS,
            )
        except anthropic.APIStatusError as e:
            raise _err(f"ИИ недоступен ({e.status_code}). Попробуйте позже.", 502)
        except anthropic.APIConnectionError:
            raise _err("Нет связи с ИИ. Проверьте интернет и попробуйте ещё раз.", 502)
        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        if not tool_uses:
            return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        conv.append({"role": "assistant", "content": resp.content})
        results = []
        for b in tool_uses:
            try:
                out = await execute(b.name, b.input or {})
            except Exception as e:  # ошибка инструмента не роняет диалог
                out = f"Не удалось выполнить: {e}"
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": str(out)})
        conv.append({"role": "user", "content": results})
    return "Готово."


async def chat_answer(messages: list[dict], lang: str = "ru", context: str = "") -> str:
    """Многоходовый ответ ИИ-ассистента (чат). messages — [{role: user/assistant, content}].
    context — выдержки из библиотеки (RAG), если нашлись."""
    if not settings.anthropic_api_key:
        raise _err("ИИ пока не подключён. Обратитесь к администратору.", 403)
    system = SYSTEM_CHAT + "\n\n" + _lang_instr(lang)
    if context:
        system += "\n\n" + _chat_context_block(context)
    msgs = [
        {"role": m["role"], "content": str(m["content"])[:4000]}
        for m in messages
        if m.get("content") and m.get("role") in ("user", "assistant")
    ][-10:]  # ограничиваем историю (цена/контекст)
    if not msgs:
        raise _err("Пустой запрос.")
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        resp = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=1200,
            output_config={"effort": "low"},
            system=system,
            messages=msgs,
        )
    except anthropic.APIStatusError as e:
        raise _err(f"ИИ недоступен ({e.status_code}). Попробуйте позже.", 502)
    except anthropic.APIConnectionError:
        raise _err("Нет связи с ИИ. Проверьте интернет и попробуйте ещё раз.", 502)
    return "".join(b.text for b in resp.content if b.type == "text").strip()


async def generate_slides(topic: str, slides: int = 8, lang: str = "ru", context: str = "") -> str:
    """Текст в формате app.present (заголовок + слайды через «#» + IMG).

    Если тема задана С ПОДПУНКТАМИ (несколько строк) — это ПЛАН: каждый подпункт раскрывается
    отдельным слайдом в том же порядке, глубоко. context — выдержки из библиотеки (RAG)."""
    lines = [ln.strip(" -•*–—\t").strip() for ln in (topic or "").splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        raise _err("Напишите тему презентации.")
    main = lines[0]
    subs = lines[1:]
    slides = max(1, min(int(slides or 8), 20))
    # есть план подпунктов → слайдов не меньше, чем подпунктов (+титульная идея), до 20
    if subs:
        slides = max(slides, min(len(subs) + 1, 20))
    angle = random.choice(_ANGLES)
    nonce = random.randint(1000, 9999)  # меняет ввод → модель выдаёт иной вариант
    if subs:
        plan = "\n".join(f"{i}. {s}" for i, s in enumerate(subs, 1))
        plan_instr = (
            "Ниже дан ПЛАН подпунктов. Раскрой ОБЯЗАТЕЛЬНО КАЖДЫЙ подпункт — в том же порядке, "
            "каждому выдели отдельный слайд (объёмному — несколько слайдов). Ничего не пропускай, "
            "не объединяй поверхностно, не подменяй общими словами. По каждому подпункту дай конкретику: "
            "определения, классификации, морфологию, отличия/дифференциацию, значение и последствия.\n"
            f"ПЛАН:\n{plan}\n\n"
        )
    else:
        plan_instr = ""
    prompt = (
        f"{_context_block(context)}"
        f"{plan_instr}"
        f"Составь учебную презентацию на тему: «{main}». Сделай {slides} содержательных слайдов. "
        f"У каждого слайда обязательно строка IMG с запросом фото. "
        f"{angle} Сделай этот вариант уникальным — свои формулировки, примеры и порядок подачи, "
        f"не как в типовой презентации. (служебная метка {nonce}, не выводи её в текст)\n"
        f"{_lang_instr(lang)}"
    )
    # больше токенов — чтобы на 15–20 слайдов ответ не обрезался и IMG-строки не терялись
    return await _ask(SYSTEM_SLIDES, prompt, max_tokens=8000)


async def choose_slide_images(
    title: str, bullets: list[str], candidates_b64: list[str], want: int = 1
) -> list[int]:
    """Зрением Claude выбирает самые релевантные картинки для слайда.

    candidates_b64 — уменьшенные JPEG в base64 (кандидаты 1..N).
    Возвращает 0-based индексы выбранных (0..want), нерелевантные отбрасывает.
    Без ключа ИИ или при ошибке — вернёт первый кандидат (как раньше, по релевантности источника)."""
    n = len(candidates_b64)
    if n == 0:
        return []
    if not settings.anthropic_api_key:
        return list(range(min(want, n)))
    pts = "; ".join(b.strip() for b in (bullets or []) if b.strip())[:400]
    prompt = (
        f"Тема слайда: «{title}». {pts or ''}\n"
        f"Ниже {n} изображений (1..{n}). Перечисли номера тех, что ПО ТЕМЕ слайда "
        f"(показывают его предмет), через запятую и по убыванию уместности (например «2,4,1»). "
        f"Пропусти явно чужое (другой объект, животное, пейзаж), графики, таблицы и коллажи. "
        f"Если по теме ничего нет — ответь «0»."
    )
    content: list[dict] = [{"type": "text", "text": prompt}]
    for i, b64 in enumerate(candidates_b64, 1):
        content.append({"type": "text", "text": f"Изображение {i}:"})
        content.append(
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}}
        )
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        msg = await client.messages.create(
            model=settings.anthropic_model,
            # МЫШЛЕНИЕ ВЫКЛЮЧЕНО. Раньше стоял effort:low (у Haiku 5.5 мышление по умолчанию ВКЛ),
            # и модель перед ответом тратила бюджет на «раздумья» — при малом лимите (50/200) до
            # текста ответа дело не доходило (пустота → фото пропадали), поэтому держали max_tokens=1024.
            # Но выбор фото — не задача на рассуждение («посмотри и назови номера»): отключаем мышление
            # (`thinking=disabled`, Haiku 5.5 это разрешает) — ответ выходит сразу, лимит хватает 96.
            # Замер на реальных темах: выбор тех же картинок, выходных токенов в ~30× меньше.
            max_tokens=96,
            thinking={"type": "disabled"},
            system="Ты отбираешь иллюстрации для учебных слайдов. Отвечай только номерами выбранных картинок.",
            messages=[{"role": "user", "content": content}],
        )
        raw = "".join(b.text for b in msg.content if b.type == "text").strip()
    except Exception:
        return list(range(min(want, n)))
    nums = []
    for tok in raw.replace(";", ",").replace(" ", ",").split(","):
        tok = "".join(ch for ch in tok if ch.isdigit())
        if tok:
            k = int(tok)
            if 1 <= k <= n and (k - 1) not in nums:
                nums.append(k - 1)
    return nums[:5]  # все подходящие по рангу (до 5) — распределяются по слайдам без повторов


async def describe_image(b64: str) -> str:
    """Короткая русская подпись к иллюстрации (что изображено) — для поиска фигур книги по теме.
    Пусто при ошибке/без ключа."""
    if not settings.anthropic_api_key or not b64:
        return ""
    content = [
        {"type": "text", "text": "Одним коротким предложением по-русски опиши, ЧТО изображено на этой "
         "учебной/медицинской иллюстрации: орган или ткань, патология/процесс, тип препарата "
         "(гистология, макропрепарат, рентген, схема). Только описание, без вступлений."},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
    ]
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        msg = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=512,  # как и для выбора фото: модели нужен запас, иначе пустой ответ
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": content}],
        )
        return "".join(b.text for b in msg.content if b.type == "text").strip()[:400]
    except Exception:
        return ""


async def generate_test(topic: str, questions: int = 10) -> str:
    """Текст теста в «буквенном» формате (parse_text его разберёт)."""
    topic = " ".join((topic or "").split())
    if not topic:
        raise _err("Напишите тему теста.")
    questions = max(1, min(int(questions or 10), 40))
    prompt = (
        f"Составь тест из РОВНО {questions} вопросов по теме «{topic}». "
        f"Пронумеруй их 1..{questions}. У каждого ровно 4 варианта, правильный один."
    )
    return await _ask(SYSTEM_TEST, prompt, max_tokens=8000)


# Предел длины исходного материала, который отдаём модели (символов) — защита от перерасхода токенов.
MAX_MATERIAL_CHARS = 24000


def _material_block(material: str) -> str:
    """Блок со СТРОГИМ материалом пользователя: вопросы только по нему, без домыслов."""
    return (
        "Ниже — материал, который прислал пользователь (текст, презентация или книга). "
        "Составляй вопросы СТРОГО по этому материалу: бери только факты, определения, термины и "
        "данные, которые в нём есть. НЕ добавляй сведения извне и НЕ выдумывай. Если материала не "
        "хватает на нужное число вопросов — сделай меньше, это нормально.\n\n"
        "=== МАТЕРИАЛ ===\n"
        f"{material}\n"
        "=== КОНЕЦ МАТЕРИАЛА ===\n\n"
    )


async def generate_test_questions(
    topic: str, count: int = 10, lang: str = "ru", context: str = "", strict: bool = False
):
    """Надёжно набирает нужное число вопросов: при нехватке дозапрашивает недостающие.

    context — исходный материал: выдержки из библиотеки (RAG) или присланный пользователем текст.
    strict=True — составлять вопросы ТОЛЬКО по материалу (для файлов/текста от пользователя),
    не дополняя общими знаниями. Возвращает список ParsedQuestion."""
    from .parsers import parse_text

    topic = " ".join((topic or "").split())
    if not topic and not (strict and context):
        raise _err("Напишите тему теста.")
    if context and len(context) > MAX_MATERIAL_CHARS:
        context = context[:MAX_MATERIAL_CHARS]
    count = max(1, min(int(count or 10), 40))
    collected = []
    for attempt in range(3):
        need = count - len(collected)
        if need <= 0:
            break
        again = " Не повторяй уже заданные вопросы, придумай новые." if attempt else ""
        if strict and context:
            head = _material_block(context) if attempt == 0 else "Используй только присланный выше материал. "
            about = f"по теме «{topic}» " if topic else ""
            prompt = (
                f"{head}"
                f"Составь до {need} вопросов теста {about}СТРОГО по этому материалу. "
                f"У каждого ровно 4 варианта, правильный один — отмечен звёздочкой. "
                f"Если материала не хватает — сделай меньше, не выдумывай.{again}\n"
                f"{_lang_instr(lang)}"
            )
        else:
            prompt = (
                f"{_context_block(context) if attempt == 0 else ''}"
                f"Составь РОВНО {need} вопросов теста по теме «{topic}». "
                f"У каждого ровно 4 варианта, правильный один — отмечен звёздочкой.{again}\n"
                f"{_lang_instr(lang)}"
            )
        text = await _ask(SYSTEM_TEST, prompt, max_tokens=8000)
        collected += parse_text(text).questions
    return collected[:count]
