from fastapi import APIRouter

from app.api.routes import auth
from app.api.routes import chats
from app.api.routes import hf
from app.api.routes import models


api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(models.router, prefix="/models", tags=["models"])
api_router.include_router(chats.router, prefix="/chats", tags=["chats"])
api_router.include_router(hf.router, prefix="/hf", tags=["huggingface"])

