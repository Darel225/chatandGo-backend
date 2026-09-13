"""
Fonctions utilitaires pour l'interaction avec la base de données.
Utilisées comme "outils" (tools) par l'agent DeepSeek via le Function Calling.
"""
from decimal import Decimal
from urllib.parse import quote
from typing import Optional

import asyncpg


def _record_to_dict(record: asyncpg.Record) -> dict:
    """
    Convertit un Record asyncpg en dictionnaire JSON-sérialisable.
    Gère les types Decimal (note_moyenne, tarifs) → float.
    """
    result = {}
    for key, value in dict(record).items():
        if isinstance(value, Decimal):
            result[key] = float(value)
        elif isinstance(value, list):
            result[key] = [str(v) for v in value]  # TEXT[] arrays
        else:
            result[key] = value
    return result


def _enrich_provider(p: dict, fallback_categorie: str = "") -> dict:
    """
    Reproduit exactement la logique du nœud 'Code in JavaScript' n8n :
    - Calcule whatsapp_url et tel_url
    - Construit nom_complet
    - Formate tarif_affiche et note_affichee
    - Garantit qu'aucun champ obligatoire n'est null/vide
    - Génère maps_url pour l'itinéraire Google Maps
    """
    phone_to_use = p.get("whatsapp") or p.get("telephone") or ""
    clean_phone = "".join(c for c in str(phone_to_use) if c.isdigit())

    tarif_min = p.get("tarif_min") or 0
    tarif_max = p.get("tarif_max") or 0
    note = float(p.get("note_moyenne") or 0)
    nb = p.get("nb_avis") or 0

    return {
        "id": p.get("id"),
        "nom": p.get("nom", ""),
        "prenom": p.get("prenom", ""),
        "nom_complet": f"{p.get('prenom', '')} {p.get('nom', '')}".strip(),
        "categorie": p.get("categorie") or fallback_categorie,
        "sous_categorie": p.get("sous_categorie") or "",
        "ville": p.get("ville") or "",
        "quartier": p.get("quartier") or "",
        "telephone": p.get("telephone") or "",
        "whatsapp": p.get("whatsapp") or p.get("telephone") or "",
        "whatsapp_url": f"https://wa.me/{clean_phone}" if clean_phone else "",
        "tel_url": f"tel:{p.get('telephone') or ''}",
        "maps_url": (
            "https://www.google.com/maps/dir/?api=1&destination="
            + quote(
                ", ".join(filter(None, [
                    f"{p.get('prenom', '')} {p.get('nom', '')}".strip(),
                    p.get("quartier") or "",
                    p.get("ville") or "",
                ])),
                safe="",
            )
        ),
        "description": p.get("description") or "",
        "experience_annees": p.get("experience_annees") or 0,
        "tarif_min": tarif_min,
        "tarif_max": tarif_max,
        "unite_tarif": p.get("unite_tarif") or "",
        "tarif_affiche": (
            f"{tarif_min:,} - {tarif_max:,} FCFA {p.get('unite_tarif') or ''}".strip()
            if tarif_min and tarif_max
            else "Tarif sur devis"
        ),
        "note_moyenne": note,
        "nb_avis": nb,
        "note_affichee": f"⭐ {note:.1f} ({nb} avis)",
        "disponible": p.get("disponible", True),
        "verified": p.get("verified", False),
        "langues": p.get("langues") or ["Français"],
        "zone_intervention": p.get("zone_intervention") or [],
    }


# ============================================================
# OUTIL PRINCIPAL : Recherche de prestataires (Function Calling)
# Reproduit EXACTEMENT la requête SQL du nœud n8n d'origine
# ============================================================
async def search_prestataires_tool(
    pool: asyncpg.Pool,
    categorie: str,
    ville: str,
    limit: int = 3,
) -> list[dict]:
    """
    Recherche des prestataires selon catégorie et ville/quartier.
    - Cherche dans categorie, sous_categorie ET description (comme n8n)
    - Vérifie aussi zone_intervention (comme n8n)
    - Retourne les résultats enrichis prêts pour le frontend
    """
    async with pool.acquire() as conn:
        records = await conn.fetch(
            """
            SELECT
                id, nom, prenom, categorie, sous_categorie,
                ville, quartier, telephone, whatsapp,
                description, experience_annees,
                tarif_min, tarif_max, unite_tarif,
                note_moyenne, nb_avis, disponible,
                zone_intervention, langues, verified
            FROM prestataires
            WHERE
                actif = TRUE
                AND disponible = TRUE
                AND (
                    categorie    ILIKE $1
                    OR sous_categorie ILIKE $1
                    OR description   ILIKE $1
                )
                AND (
                    ville    ILIKE $2
                    OR quartier ILIKE $2
                    OR $2 ILIKE ANY(zone_intervention)
                )
            ORDER BY
                verified DESC,
                note_moyenne DESC,
                nb_avis DESC
            LIMIT $3
            """,
            f"%{categorie}%",
            f"%{ville}%",
            limit,
        )

    raw = [_record_to_dict(r) for r in records]
    return [_enrich_provider(p, fallback_categorie=categorie) for p in raw]


async def search_prestataires_fallback(
    pool: asyncpg.Pool,
    categorie: str,
    limit: int = 3,
) -> list[dict]:
    """
    Fallback : recherche sur TOUTE la Côte d'Ivoire si aucun résultat local.
    Reproduit le comportement de relance élargie du workflow n8n.
    """
    async with pool.acquire() as conn:
        records = await conn.fetch(
            """
            SELECT
                id, nom, prenom, categorie, sous_categorie,
                ville, quartier, telephone, whatsapp,
                description, experience_annees,
                tarif_min, tarif_max, unite_tarif,
                note_moyenne, nb_avis, disponible,
                zone_intervention, langues, verified
            FROM prestataires
            WHERE
                actif = TRUE
                AND disponible = TRUE
                AND (
                    categorie    ILIKE $1
                    OR sous_categorie ILIKE $1
                    OR description   ILIKE $1
                )
            ORDER BY
                verified DESC,
                note_moyenne DESC,
                nb_avis DESC
            LIMIT $2
            """,
            f"%{categorie}%",
            limit,
        )

    raw = [_record_to_dict(r) for r in records]
    return [_enrich_provider(p, fallback_categorie=categorie) for p in raw]


# ============================================================
# HISTORIQUE DES CONVERSATIONS
# ============================================================
async def get_conversation_history(
    pool: asyncpg.Pool,
    session_id: str,
    limit: int = 10,
) -> list[dict]:
    """
    Récupère les derniers messages d'une session pour construire
    le contexte envoyé à l'IA. Retourne dans l'ordre chronologique.
    """
    async with pool.acquire() as conn:
        records = await conn.fetch(
            """
            SELECT message_user, reponse_agent
            FROM conversations
            WHERE session_id = $1
            ORDER BY timestamp DESC
            LIMIT $2
            """,
            session_id,
            limit,
        )

    # Inversion pour avoir l'ordre chronologique (ancien -> récent)
    history = []
    for r in reversed(records):
        history.append({"role": "user", "content": r["message_user"]})
        history.append({"role": "assistant", "content": r["reponse_agent"]})
    return history


async def save_conversation(
    pool: asyncpg.Pool,
    session_id: str,
    message_user: str,
    reponse_agent: str,
    intention: Optional[str] = None,
    categorie_detectee: Optional[str] = None,
    ville_detectee: Optional[str] = None,
    prestataires_proposes: Optional[str] = None,
) -> None:
    """Sauvegarde l'interaction complète dans la table conversations avec le schéma n8n legacy."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO conversations (
                session_id, message_user, reponse_agent, 
                intention, categorie_detectee, ville_detectee, 
                prestataires_proposes, timestamp
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
            """,
            session_id,
            message_user,
            reponse_agent,
            intention,
            categorie_detectee,
            ville_detectee,
            prestataires_proposes,
        )


async def save_demande_historique(
    pool: asyncpg.Pool,
    user_email: str,
    session_id: str,
    titre: str,
    sous_titre: str,
) -> None:
    """Sauvegarde la demande dans l'historique pour consultation ultérieure."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO demandes_historique
                (user_email, session_id, titre, sous_titre, statut, created_at)
            VALUES ($1, $2, $3, $4, 'actif', NOW())
            """,
            user_email,
            session_id,
            titre,
            sous_titre,
        )


async def save_contacts_recents(
    pool: asyncpg.Pool,
    user_email: str,
    prestataires: list[dict],
) -> None:
    """Enregistre les prestataires retournés comme contacts récents (schéma dénormalisé).
    Compatible avec les prestataires SQL (champs: nom, prenom) et web SerpApi (champ: nom_complet).
    """
    async with pool.acquire() as conn:
        for p in prestataires[:2]:  # max 2 comme dans le workflow n8n
            # Formatage pour correspondre au sous-titre de la carte du Chat
            categorie = p.get("categorie", "").capitalize()
            sous_categorie = p.get("sous_categorie", "")
            metier_label = f"{categorie} - {sous_categorie}" if sous_categorie else categorie

            # Résolution du nom : prestataires SQL ont nom+prenom, web ont nom_complet
            nom_affiche = (
                p.get("nom_complet")
                or f"{p.get('prenom', '')} {p.get('nom', '')}".strip()
                or "Lieu inconnu"
            )

            # Résolution du téléphone : prestataires SQL ont telephone, web ont tel_url ou phone
            tel = p.get("telephone") or p.get("phone") or ""
            if not tel and p.get("tel_url"):
                # Extrait le numéro brut depuis "tel:+225..."
                tel = p.get("tel_url", "").replace("tel:", "")

            # Whatsapp : prestataires SQL ont whatsapp, web peuvent ne pas en avoir
            wa = p.get("whatsapp") or tel

            await conn.execute(
                """
                INSERT INTO contacts_recents 
                    (user_email, nom, metier, note, nombre_interventions, telephone, whatsapp, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                """,
                user_email,
                nom_affiche,
                metier_label,
                str(p.get("note_moyenne") or p.get("note_affichee") or "0.0"),
                str(p.get("nb_avis", "0")),
                tel,
                wa,
            )
