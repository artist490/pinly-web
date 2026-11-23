# Авто-модерация публикуемых пинов через heygen/heygen-decision-1-turbo
# (routerai.ru, тот же ключ EMBED_API_KEY, что у векторного поиска).
#
# Модель — «решающая»: принимает текст и картинку (base64), возвращает
# вероятности «да» по набору вопросов (noul). Вердикт не финален: пин
# мягко скрывается (pins.is_hidden) и падает в существующую очередь жалоб
# /api/admin/reports с reason='offensive' и пометкой auto_review=1 для
# финального решения человеком. Без ключа — интеграция отключена, сайт
# работает как прежде.
#
# Картинка обложки читается с диска (локальные загрузки) либо тянется по
# source_url (внешние пины). Модель не принимает ссылки — только данные,
# поэтому внешняя картинка скачивается и кодируется в base64.

import base64
import os
import time
import uuid

import httpx

from . import embeddings, imgproxy, moderation, pins, uploads
from .db import connection

MODEL = "heygen/heygen-decision-1-turbo"
ENDPOINT = "/decisions"
TIMEOUT_S = 30.0

# Порог вероятности, после которого пин скрывается автоматом. Модель
# оценочная, поэтому порог высокий (0.7): лучше пропустить спам, чем
# скрыть доброкачественный пин. Человек в панели принимает финальное
# решение в любом случае — авто-скрытие обратимо.
THRESHOLD = float(os.environ.get("AUTOREVIEW_THRESHOLD", "0.7"))

# Карта вопросов -> причина жалобы в очереди. Запрос один, вопросов может
# быть сколько угодно — они оцениваются параллельно. Берём три сигнала:
# спам/реклама, неуместный контент, нарушение авторских прав (водяной знак
# или чужая работа).
QUESTIONS = {
    "is_spam": {
        "type": "noul",
        "instructions": (
            "Является ли этот пин спамом, навязчивой рекламой или"
            " попыткой обмана (объявление без отношения к сайту про"
            " интерьер и дизайн, заголовок-кликбейт, чужая реклама)?"
        ),
    },
    "is_offensive": {
        "type": "noul",
        "instructions": (
            "Содержит ли пин неуместный контент: насилие, порнографическое"
            " изображение, разжигание ненависти, оскорбления?"
        ),
    },
    "is_copyright": {
        "type": "noul",
        "instructions": (
            "Нарушает ли пин авторские права: изображение с явными водяными"
            " знаками чужого фотографа/студии, скриншот чужого пина"
            " без переработки?"
        ),
    },
}

# какой вопрос -> какая причина жалобы; приоритет при срабатывании
# нескольких — у самого весомого сигнала
REASON_BY_QUESTION = {
    "is_spam": "spam",
    "is_offensive": "offensive",
    "is_copyright": "copyright",
}


def autoreview_enabled() -> bool:
    # тот же ключ, что у векторного поиска — отдельный флаг/autoload не нужен:
    # ключ один, роутер один. Отключить можно только убрав ключ.
    return bool(embeddings.embed_api_key())


def _base_url() -> str:
    # совпадает с embeddings: один ключ/роутер на все AI-вызовы
    return embeddings.embed_base_url()


# --- чтение картинки для модели ---


def _local_image_b64(conn, pin_id: str) -> tuple[str, bytes] | None:
    """Обложка локального пина как (mime, bytes). Внешние пины (ov-…)
    сюда не попадают — у них нет файла на диске."""
    row = pins.row_by_id(conn, pin_id)
    if row is None or not row["file"]:
        return None
    path = uploads.location(row["file"])
    if not path.exists():
        return None
    mime = uploads.media_type(row["file"])
    # модель берёт jpeg/png/webp; видео-постер — обычно jpeg
    data = path.read_bytes()
    if not data:
        return None
    return mime, data


async def _remote_image_b64(url: str) -> tuple[str, bytes] | None:
    """Внешняя картинка (source_url): модель не принимает ссылки, поэтому
    скачиваем и кодируем. Тонкая обработка ошибок здесь не нужна — на сбое
    вернём None и пропустим картинку, оставив текстовую часть вердикта."""
    try:
        file = await imgproxy.fetch_to_cache(url)
    except Exception:
        return None
    if not file.exists():
        return None
    kind = imgproxy.kind(file)
    mime = imgproxy.media_type(kind)
    data = file.read_bytes()
    if not data:
        return None
    return mime, data


def _state_text(pin: dict) -> str:
    """Текстовая часть пина: заголовок, описание, категория, теги — то же,
    что уходит в векторный поиск. Модель видит контент пина, а не метаданные."""
    tags = ", ".join(pin.get("tags") or [])
    return (
        f"Название: {pin['title']}\n"
        f"Категория: {pin['category']}\n"
        f"Описание: {pin['description']}\n"
        f"Теги: {tags}"
    )


def _build_state(text: str, image_data: tuple[str, bytes] | None) -> list[dict]:
    """state — массив узлов для модели. Текст идёт всегда, картина — если
    удалось прочитать. Без картинки вердикт всё равно возможен по тексту."""
    state: list[dict] = [{"type": "text", "text": text}]
    if image_data is not None:
        mime, data = image_data
        b64 = base64.b64encode(data).decode()
        state.append(
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
        )
    return state


# --- вызов модели ---


async def _decide(state: list[dict]) -> dict[str, float] | None:
    """Отправить пин в модель, вернуть карты вопрос -> вероятность 'да'.
    При сбое сети/сервиса — None: авто-модерация не критична, пин публикуется.
    """
    body = {
        "model": MODEL,
        "state": state,
        "questions": QUESTIONS,
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            res = await client.post(
                f"{_base_url()}{ENDPOINT}",
                headers={
                    "Authorization": f"Bearer {embeddings.embed_api_key()}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        if res.status_code >= 400:
            return None
        answers = res.json().get("answers", {})
    except Exception:
        return None
    # каждый ответ — {"noul": 0.xx}; тонкий пропуск битых элементов
    out: dict[str, float] = {}
    for name, ans in answers.items():
        if isinstance(ans, dict) and isinstance(ans.get("noul"), (int, float)):
            out[name] = float(ans["noul"])
    return out


# --- применение вердикта ---


def _apply(pin_id: str, verdicts: dict[str, float]) -> None:
    """Если хотя бы один вопрос перешёл порог — скрыть пин и положить жалобу
    в очередь с пометкой auto_review. Берём самый весомый сигнал как reason.
    """
    triggered = [(q, p) for q, p in verdicts.items() if p >= THRESHOLD]
    if not triggered:
        return
    triggered.sort(key=lambda kv: -kv[1])
    question = triggered[0][0]
    reason = dict(REASON_BY_QUESTION).get(question, "offensive")
    with connection() as conn:
        # мягкое скрытие — тот же механизм, что у ручной жалобы
        conn.execute("update pins set is_hidden = 1 where id = ?", (pin_id,))
        # жалоба от системы: reporter_id=NULL (свободное поле, не FK на users),
        # авто-пометка в detail отличает её от ручных в очереди
        conn.execute(
            "insert into reports (id, reporter_id, target_type, target_id, reason,"
            " status, created_at, auto_review, detail) values (?, NULL, 'pin', ?, ?,"
            " 'open', ?, 1, ?)",
            (
                str(uuid.uuid4()),
                pin_id,
                reason,
                time.time(),
                f"авто-модерация: {question}={triggered[0][1]:.2f}",
            ),
        )


# --- точка входа ---


async def review_pin(pin: dict) -> None:
    """Проверить свежеопубликованный пин. Вызывается из routers/pins после
    создания и векторизации. Ошибки проглатываются: публикация важнее и не
    должна падать из-за внешнего сервиса.
    """
    if not autoreview_enabled():
        return
    try:
        pin_id = pin["id"]
        # локальный файл или внешняя ссылка — обложка решает
        source = pin.get("sourceUrl") or ""
        image_data: tuple[str, bytes] | None = None
        if source.startswith("http"):
            image_data = await _remote_image_b64(source)
        else:
            # локальный пин: обложка лежит в uploads, имя файла — в базе
            with connection() as conn:
                image_data = _local_image_b64(conn, pin_id)
        state = _build_state(_state_text(pin), image_data)
        verdicts = await _decide(state)
        if verdicts:
            _apply(pin_id, verdicts)
    except Exception:
        pass  # авто-модерация не критична: публикация не падает из-за неё
