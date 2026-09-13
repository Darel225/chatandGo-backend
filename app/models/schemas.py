from pydantic import BaseModel, EmailStr, Field
from typing import Optional


# ============================================================
# AUTHENTIFICATION
# ============================================================

class RequestOTPInput(BaseModel):
    email: EmailStr


class VerifyOTPInput(BaseModel):
    email: EmailStr
    code: str


# ============================================================
# PROFIL
# ============================================================

class UpdateProfileInput(BaseModel):
    email: EmailStr
    nom: Optional[str] = ""
    prenom: Optional[str] = ""
    quartier: Optional[str] = ""
    photo_url: Optional[str] = ""


# ============================================================
# CHAT / AGENT IA
# ============================================================

class ConvCommerceInput(BaseModel):
    session_id: str
    email: str
    message: str = Field(..., max_length=1000)
    user_location: Optional[str] = "Abidjan"


# ============================================================
# HISTORIQUE
# ============================================================

class HistoryInput(BaseModel):
    email: str


class SessionInput(BaseModel):
    session_id: str
    email: str


class ClearHistoryInput(BaseModel):
    email: str
