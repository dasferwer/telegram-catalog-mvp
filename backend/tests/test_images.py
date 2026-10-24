import io

import pytest
from PIL import Image

from shop.bot_logic import image_type


@pytest.mark.parametrize("kind", ["JPEG", "PNG"])
def test_valid_image_is_decodable(kind: str) -> None:
    with io.BytesIO() as buffer:
        Image.new("RGB", (64, 64)).save(buffer, kind)
        assert image_type(buffer.getvalue()) == "image/" + kind.lower().replace("jpg", "jpeg")


@pytest.mark.parametrize("removed", [2, 10, 30, 60])
def test_truncated_jpeg_is_rejected(removed: int) -> None:
    with io.BytesIO() as buffer:
        Image.new("RGB", (64, 64)).save(buffer, "JPEG")
        with pytest.raises(ValueError):
            image_type(buffer.getvalue()[:-removed])


def test_unsupported_parser_is_not_called(monkeypatch: pytest.MonkeyPatch) -> None:
    import PIL.XbmImagePlugin

    def unexpected(*args: object, **kwargs: object) -> None:
        pytest.fail("Unsupported format reached its parser")

    monkeypatch.setattr(PIL.XbmImagePlugin.XbmImageFile, "_open", unexpected)
    with pytest.raises(ValueError):
        image_type(b"#define x_width 1\n#define x_height 1\nstatic char x_bits[] = {0};")
