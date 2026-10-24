"""Isolated Telegram Bot API adapter. Never enabled by the production Compose file."""

import asyncio
import io
from typing import Any

from aiohttp import web
from PIL import Image

image = io.BytesIO()
Image.new("RGB", (32, 24), "#167540").save(image, format="JPEG")
PHOTO = image.getvalue()
messages: list[dict[str, Any]] = []
control: dict[str, Any] = {"fail_send": 0, "send_delay": 0, "file_delay": 0}


async def api(request: web.Request) -> web.Response:
    method = request.match_info["method"].lower()
    data = dict(await request.post())
    if method == "answercallbackquery":
        return web.json_response({"ok": True, "result": True})
    if method == "getfile":
        file_id = str(data.get("file_id", "photo"))
        return web.json_response(
            {
                "ok": True,
                "result": {
                    "file_id": file_id,
                    "file_unique_id": "unique",
                    "file_size": len(PHOTO),
                    "file_path": file_id + ".jpg",
                },
            }
        )
    if method == "sendmessage":
        if control["fail_send"]:
            control["fail_send"] -= 1
            return web.json_response(
                {"ok": False, "error_code": 500, "description": "Temporary test failure"},
                status=500,
            )
        messages.append(data)
        if control["send_delay"] and "Товар создан" in str(data.get("text", "")):
            await asyncio.sleep(float(control["send_delay"]))
        return web.json_response(
            {
                "ok": True,
                "result": {
                    "message_id": len(messages),
                    "date": 1000,
                    "chat": {"id": int(data["chat_id"]), "type": "private"},
                    "text": data["text"],
                },
            }
        )
    return web.json_response(
        {"ok": False, "error_code": 400, "description": "Unsupported test method"}, status=400
    )


async def file(request: web.Request) -> web.Response:
    if control["file_delay"]:
        await asyncio.sleep(float(control["file_delay"]))
    name = request.match_info["path"]
    data = b"not-a-photo" if name.startswith("invalid") else PHOTO
    if name.startswith("oversized"):
        data = PHOTO + b"0" * (5 * 1024 * 1024)
    return web.Response(body=data, content_type="image/jpeg")


async def configure(request: web.Request) -> web.Response:
    control.update(await request.json())
    return web.json_response(control)


async def history(request: web.Request) -> web.Response:
    return web.json_response(messages)


async def health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


app = web.Application(client_max_size=65536)
app.router.add_post("/bot{token}/{method}", api)
app.router.add_get("/file/bot{token}/{path:.*}", file)
app.router.add_post("/control", configure)
app.router.add_get("/messages", history)
app.router.add_get("/health", health)
web.run_app(app, port=8081, access_log=None)
