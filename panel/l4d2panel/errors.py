"""The one error shape the API speaks: {"error": message} with an HTTP status."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger('l4d2panel')


class ApiError(Exception):
    """A client-facing failure: the message is shown to the user as-is."""
    def __init__(self, status: int, message: str):
        super().__init__(message); self.status, self.message = status, message


class IntegrationError(Exception):
    """RCON / Steam / file access failed. Reported with its message (status 500) because the admin needs to see why."""


def error_response(status: int, message: str) -> JSONResponse:
    return JSONResponse({'error': message}, status_code=status, headers={'Cache-Control': 'no-store'})


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return error_response(exc.status, exc.message)

    @app.exception_handler(IntegrationError)
    async def _integration_error(request: Request, exc: IntegrationError):
        return error_response(500, str(exc))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        where = '.'.join(str(x) for x in first.get('loc', ()) if x not in ('body',))
        return error_response(400, f'参数无效: {where} {first.get("msg", "")}'.strip())

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        return error_response(exc.status_code, str(exc.detail) if exc.detail else 'error')

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        log.exception('unhandled error on %s %s', request.method, request.url.path)
        return error_response(500, f'内部错误: {type(exc).__name__}: {exc}')
