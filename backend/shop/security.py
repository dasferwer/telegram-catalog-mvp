import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


class InvalidInitData(ValueError):
    pass


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def validate_init_data(raw: str, token: str, *, now: int | None = None) -> int:
    try:
        if not token or not raw or len(raw) > 8192:
            raise ValueError
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, max_num_fields=30)
        data = dict(pairs)
        if len(data) != len(pairs):
            raise ValueError
        supplied = data.pop("hash")
        secret = hmac.digest(b"WebAppData", token.encode(), "sha256")
        expected = hmac.new(
            secret, "\n".join(f"{k}={v}" for k, v in sorted(data.items())).encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(supplied, expected):
            raise ValueError
        auth_date = int(data["auth_date"])
        age = (int(time.time()) if now is None else now) - auth_date
        if not 0 <= age <= 3600:
            raise ValueError
        user = json.loads(data["user"])
        user_id = user["id"]
        if type(user_id) is not int or not 0 < user_id < 2**63:
            raise ValueError
        return user_id
    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise InvalidInitData("Некорректная или просроченная авторизация Telegram") from exc
