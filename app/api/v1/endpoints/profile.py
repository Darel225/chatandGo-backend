from fastapi import APIRouter, HTTPException

from app.core.database import get_pool
from app.models.schemas import UpdateProfileInput

router = APIRouter()


# ============================================================
# POST /update-profile
# ============================================================
@router.post("/update-profile")
async def update_profile(data: UpdateProfileInput):
    """
    Met à jour le profil de l'utilisateur.
    Utilise COALESCE pour ne mettre à jour que les champs non-vides,
    préservant ainsi les valeurs existantes si un champ est omis.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            """
            UPDATE users
            SET
                nom               = COALESCE(NULLIF($2, ''), nom),
                prenom            = COALESCE(NULLIF($3, ''), prenom),
                quartier_par_defaut = COALESCE(NULLIF($4, ''), quartier_par_defaut),
                photo_url         = COALESCE(NULLIF($5, ''), photo_url)
            WHERE email = $1
            RETURNING id, email, nom, prenom, ville_par_defaut, quartier_par_defaut, photo_url
            """,
            data.email,
            data.nom,
            data.prenom,
            data.quartier,
            data.photo_url,
        )

    if not user:
        raise HTTPException(
            status_code=404,
            detail="Utilisateur non trouvé. Veuillez vous connecter d'abord.",
        )

    return {
        "success": True,
        "message": "Profil mis à jour avec succès.",
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
