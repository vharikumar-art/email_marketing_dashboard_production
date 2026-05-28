from fastapi import APIRouter

from app.api.routes import router as api_routes

api_router = APIRouter()
api_router.include_router(api_routes)

