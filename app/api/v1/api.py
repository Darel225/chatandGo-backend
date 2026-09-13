from fastapi import APIRouter
from app.api.v1.endpoints import auth, profile, chat, history

api_router = APIRouter()

api_router.include_router(auth.router,    prefix="/auth",    tags=["🔐 Authentification"])
api_router.include_router(profile.router, prefix="/profile", tags=["👤 Profil"])
api_router.include_router(chat.router,    prefix="/chat",    tags=["🤖 Agent IA"])
api_router.include_router(history.router, prefix="/history", tags=["📜 Historique"])

