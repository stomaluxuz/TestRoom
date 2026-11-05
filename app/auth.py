"""Проверка, что запрос к Mini App действительно пришёл из Telegram.

Telegram подписывает данные пользователя (initData) токеном бота.
Подделать подпись без токена невозможно.
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl, urlencode

MAX_AGE_SECONDS = 24 * 3600


class AuthError(Exception):
    pass


def _secret(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def validate_init_data(init_data: str, bot_token: str, max_age: int = MAX_AGE_SECONDS) -> dict:
    if not init_data or not bot_token:
        raise AuthError("нет данных авторизации")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise AuthError("нет подписи")
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    expected = hmac.new(_secret(bot_token), check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise AuthError("неверная подпись")
    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        raise AuthError("неверная дата")
    if max_age and time.time() - auth_date > max_age:
        raise AuthError("сессия устарела, откройте приложение заново")
    try:
        user = json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError:
        raise AuthError("неверные данные пользователя")
    if not isinstance(user, dict) or "id" not in user:
        raise AuthError("нет пользователя")
    return user


def make_init_data(bot_token: str, user: dict, auth_date: int | None = None) -> str:
    """Создать корректно подписанный initData (для тестов и нагрузочной проверки)."""
    pairs = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "AAtest",
        "user": json.dumps(user, ensure_ascii=False, separators=(",", ":")),
    }
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    pairs["hash"] = hmac.new(_secret(bot_token), check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)
