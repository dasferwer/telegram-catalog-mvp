import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest

from shop.security import InvalidInitData, validate_init_data

TOKEN = "123456:TEST_ONLY_NOT_A_REAL_TOKEN"


def signed(now: int = 1000, user_id: object = 42) -> str:
    fields = {"auth_date": str(now), "user": json.dumps({"id": user_id, "first_name": "Test"})}
    secret = hmac.digest(b"WebAppData", TOKEN.encode(), "sha256")
    fields["hash"] = hmac.new(
        secret, "\n".join(f"{k}={v}" for k, v in sorted(fields.items())).encode(), hashlib.sha256
    ).hexdigest()
    return urlencode(fields)


def test_valid_signature() -> None:
    assert validate_init_data(signed(), TOKEN, now=1001) == 42


@pytest.mark.parametrize(
    "value",
    [
        "",
        "hash=bad",
        signed(-3000),
        signed(2000),
        signed(user_id="42"),
        signed(user_id=True),
        signed() + "&auth_date=1000",
        signed().replace("Test", "Fake"),
    ],
)
def test_rejects_invalid_identity(value: str) -> None:
    with pytest.raises(InvalidInitData):
        validate_init_data(value, TOKEN, now=1001)
