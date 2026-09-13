from fastapi import APIRouter, HTTPException

from app.models.schemas import ConvCommerceInput
from app.services.deepseek_service import process_convcommerce

router = APIRouter()


# ============================================================
# POST /convcommerce
# ============================================================
@router.post("/convcommerce")
async def convcommerce(data: ConvCommerceInput):
    """
    Point d'entrée de l'agent conversationnel ConvCommerce CI.
    
    Orchestre :
    - La récupération du contexte de conversation
    - L'appel à DeepSeek avec Function Calling (outil SQL prestataires)
    - Le post-processing (liens WhatsApp)
    - La persistance des échanges en base
    
    Retourne la réponse de l'IA + la liste des prestataires enrichis.
    """
    try:
        result = await process_convcommerce(
            session_id=data.session_id,
            email=data.email,
            user_message=data.message,
            user_location=data.user_location or "Abidjan",
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur de l'agent IA : {str(e)}",
        )
