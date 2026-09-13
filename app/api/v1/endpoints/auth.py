import random
import string
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from app.core.database import get_pool
from app.core.mail import send_otp_email
from app.models.schemas import RequestOTPInput, VerifyOTPInput

router = APIRouter()


def _utcnow() -> datetime:
    """Retourne l'heure UTC actuelle SANS tzinfo (compatible asyncpg)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _generate_otp() -> str:
    """Génère un code OTP numérique à 6 chiffres (entropie : 1/1 000 000)."""
    return "".join(random.choices(string.digits, k=6))


# ── Protection brute-force (C-2) ────────────────────────────────────────────
# Stockage en mémoire : { email: {"count": int, "locked_until": datetime|None} }
# Suffisant pour un déploiement single-worker (Render free tier).
# Pour un déploiement multi-workers, migrer vers Redis.
_otp_attempts: dict = defaultdict(lambda: {"count": 0, "locked_until": None})

MAX_OTP_ATTEMPTS = 5          # Nombre de tentatives avant verrouillage
LOCKOUT_MINUTES   = 15        # Durée du verrouillage en minutes


def _check_brute_force(email: str) -> None:
    """
    Vérifie si l'email est actuellement verrouillé.
    Lève HTTPException 429 si c'est le cas.
    """
    state = _otp_attempts[email]
    if state["locked_until"] and _utcnow() < state["locked_until"]:
        remaining = int((state["locked_until"] - _utcnow()).total_seconds() / 60) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Trop de tentatives. Compte verrouillé pour {remaining} minute(s). Demandez un nouveau code.",
        )


def _record_failed_attempt(email: str) -> None:
    """
    Enregistre un échec de vérification.
    Verrouille le compte si MAX_OTP_ATTEMPTS est atteint.
    """
    state = _otp_attempts[email]
    state["count"] += 1
    if state["count"] >= MAX_OTP_ATTEMPTS:
        state["locked_until"] = _utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
        state["count"] = 0   # Remet à zéro pour le prochain cycle


def _reset_attempts(email: str) -> None:
    """Remet à zéro le compteur d'échecs après un succès."""
    _otp_attempts.pop(email, None)


# ============================================================
# POST /auth-request-otp
# ============================================================
@router.post("/auth-request-otp")
async def request_otp(data: RequestOTPInput):
    """
    Génère un OTP à 6 chiffres, le sauvegarde en base (expiration 5min),
    et l'envoie par email à l'utilisateur.
    Le code n'est PAS retourné dans la réponse (sécurité C-1).
    """
    otp = _generate_otp()
    expires_at = _utcnow() + timedelta(minutes=5)

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Suppression de tout OTP précédent pour cet email (évite les doublons)
        await conn.execute(
            "DELETE FROM verification_codes WHERE email = $1",
            data.email,
        )
        await conn.execute(
            """
            INSERT INTO verification_codes (email, code_otp, expires_at)
            VALUES ($1, $2, $3)
            """,
            data.email,
            otp,
            expires_at,
        )

    # Réinitialisation du compteur brute-force à chaque nouveau code demandé
    _reset_attempts(data.email)

    try:
        await send_otp_email(data.email, otp)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'envoi de l'email : {str(e)}",
        )

    # SÉCURITÉ C-1 : le champ "dev_code" est définitivement supprimé.
    # Le code OTP ne transite QUE par email.
    return {
        "success": True,
        "message": "Code OTP envoyé à votre adresse email.",
    }


# ============================================================
# POST /auth-verify-otp
# ============================================================
@router.post("/auth-verify-otp")
async def verify_otp(data: VerifyOTPInput):
    """
    Vérifie l'OTP. Si valide :
    - UPSERT de l'utilisateur dans la table `users`
    - Suppression de l'OTP
    - Retourne les infos utilisateur + flag `isNewUser`
    Protégé contre le brute-force : max 5 tentatives avant verrouillage 15 min.
    """
    # Vérification brute-force AVANT toute requête DB
    _check_brute_force(data.email)

    pool = await get_pool()
    async with pool.acquire() as conn:
        record = await conn.fetchrow(
            """
            SELECT id, expires_at
            FROM verification_codes
            WHERE email = $1 AND code_otp = $2
            ORDER BY id DESC
            LIMIT 1
            """,
            data.email,
            data.code,
        )

        if not record:
            # On enregistre l'échec et on retourne une erreur générique
            _record_failed_attempt(data.email)
            state = _otp_attempts[data.email]
            remaining = MAX_OTP_ATTEMPTS - state["count"]
            raise HTTPException(
                status_code=400,
                detail=f"Code OTP invalide. {remaining} tentative(s) restante(s) avant verrouillage.",
            )

        # Normalisation du datetime (asyncpg peut retourner avec ou sans tzinfo)
        expires_at_db = record["expires_at"]
        if expires_at_db.tzinfo is not None:
            expires_at_db = expires_at_db.replace(tzinfo=None)

        if expires_at_db < _utcnow():
            await conn.execute(
                "DELETE FROM verification_codes WHERE id = $1", record["id"]
            )
            _reset_attempts(data.email)
            raise HTTPException(
                status_code=400,
                detail="Code OTP expiré. Veuillez en demander un nouveau.",
            )

        # ── Succès : UPSERT utilisateur ──────────────────────────────────────
        user = await conn.fetchrow(
            """
            INSERT INTO users (email)
            VALUES ($1)
            ON CONFLICT (email) DO UPDATE
                SET email = EXCLUDED.email
            RETURNING id, email, nom, prenom, ville_par_defaut, quartier_par_defaut, photo_url, created_at
            """,
            data.email,
        )

        is_new_user = not bool(user["prenom"])

        await conn.execute(
            "DELETE FROM verification_codes WHERE id = $1", record["id"]
        )

    # Réinitialisation du compteur après succès
    _reset_attempts(data.email)

    return {
        "success": True,
        "isValid": True,
        "isNewUser": is_new_user,
        "user": {
            "id": str(user["id"]),
            "email": user["email"],
            "nom": user["nom"] or "",
            "prenom": user["prenom"] or "",
            "ville_par_defaut": user["ville_par_defaut"] or "Abidjan",
            "quartier_par_defaut": user["quartier_par_defaut"] or "",
            "photo_url": user["photo_url"] or "",
        },
    }

