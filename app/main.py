import os
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.router import api_router
from app.config import ALLOWED_ORIGINS
from app.database import ensure_indexes


def create_app() -> FastAPI:
    app = FastAPI(title="Email Dashboard API")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
        "http://13.206.26.177",
        "http://localhost:5173",
    ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(PerformanceMiddleware)

    os.makedirs(os.path.join("static", "uploads", "users"), exist_ok=True)
    os.makedirs(os.path.join("static", "uploads", "clients"), exist_ok=True)
    os.makedirs(os.path.join("static", "uploads", "receipts"), exist_ok=True)
    app.mount("/static", StaticFiles(directory="static"), name="static")

    app.include_router(api_router)

    @app.on_event("startup")
    def startup_event():
        ensure_indexes()

    @app.exception_handler(HTTPException)
    async def custom_http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "status_code": exc.status_code,
                "status": "error",
                "message": exc.detail,
                "data": None,
            },
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={
                "status_code": 500,
                "status": "error",
                "message": "Internal Server Error",
                "data": str(exc) if "DEV" in str(request.headers) else None,
            },
        )

    return app


class PerformanceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time

        if process_time > 1.0:
            print(f"[SLOW] {request.method} {request.url.path} took {process_time:.2f}s")
        elif process_time > 0.5:
            print(f"[WARNING] {request.method} {request.url.path} took {process_time:.2f}s")

        return response


app = create_app()
