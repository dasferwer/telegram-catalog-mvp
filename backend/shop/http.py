import socket
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse

from shop.body_limit import BodyLimit
from shop.cart import CartError


def configure_http(app: FastAPI) -> None:
    app.add_middleware(BodyLimit)

    @app.middleware("http")
    async def limits(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        length = request.headers.get("content-length", "0")
        if not length.isdigit() or int(length) > 65536:
            return JSONResponse({"detail": "Слишком большой запрос"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Instance-ID"] = socket.gethostname()
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(CartError)
    async def cart_error(request: Request, exc: CartError) -> JSONResponse:
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        # SQL-параметры и реквизиты подключения не должны попадать в ответы и логи.
        print(
            f"database_unavailable instance={socket.gethostname()} type={type(exc).__name__}",
            flush=True,
        )
        return JSONResponse({"detail": "База данных временно недоступна"}, status_code=503)
