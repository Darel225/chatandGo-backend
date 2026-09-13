import asyncpg
from app.core.config import settings

# Pool de connexions global — créé une seule fois au démarrage de l'app
_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Retourne le pool de connexions, en le créant si nécessaire."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=settings.DATABASE_URL,
            min_size=2,       # 2 connexions maintenues chaudes en permanence
            max_size=10,      # Max 10 connexions simultanées
            command_timeout=15.0,  # Abandonne toute requête bloquée > 15 s
            # FIX WinError 10054 : on expire les connexions inactives après 60 s,
            # AVANT que Neon/PgBouncer ne les ferme côté serveur (~300 s).
            # Évite les "connection was closed in the middle of operation".
            max_inactive_connection_lifetime=60.0,
        )
    return _pool


async def close_pool():
    """Ferme proprement le pool à l'arrêt de l'application."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None

