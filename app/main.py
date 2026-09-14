import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router
from app.core.database import close_pool, get_pool


# ============================================================
# Logging
# ============================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================
# Cycle de vie de l'application (démarrage / arrêt)
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # DÉMARRAGE : Initialisation du pool de connexions DB
    logger.info("🚀 Démarrage de Chat&Go Backend — connexion à la base de données...")
    await get_pool()
    logger.info("✅ Pool de connexions PostgreSQL initialisé.")
    yield
    # ARRÊT : Fermeture propre du pool
    logger.info("🛑 Arrêt du serveur — fermeture du pool de connexions...")
    await close_pool()


# ============================================================
# Initialisation de l'application FastAPI
# ============================================================
# Désactive Swagger/ReDoc en production
is_prod = os.getenv("ENV") == "production"

app = FastAPI(
    title="Chat&Go API",
    description="Backend natif FastAPI pour l'application mobile Chat&Go — Commerce & Prestataires en Côte d'Ivoire",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if is_prod else "/docs",
    redoc_url=None if is_prod else "/redoc",
)

# ============================================================
# Middleware CORS (nécessaire pour l'app React Native)
# ============================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # En production, restreindre à votre domaine si web
    allow_credentials=False,  # FIX C-3 : Invalide avec allow_origins=["*"]
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# Inclusion des routes API
# ============================================================
app.include_router(api_router, prefix="/api/v1")


# ============================================================
# Endpoints de base
# ============================================================
@app.get("/health", tags=["🏥 Health Check"])
async def health_check():
    """Endpoint utilisé par Render pour vérifier que le service est opérationnel."""
    return {"status": "ok"}

@app.head("/")
@app.get("/", tags=["🏥 Health Check"])
async def root():
    """Endpoint racine pour confirmation rapide que l'API tourne."""
    return {
        "app": "Chat&Go API",
        "version": "1.0.0",
        "status": "running 🚀",
        "docs": "/docs",
    }
