import logging
logger = logging.getLogger(__name__)
"""
CÅ“ur de l'agent IA ConvCommerce CI.
Gère le cycle complet : historique â†’ DeepSeek â†’ Function Calling â†’ SQL â†’ fallback â†’ réponse â†’ persistance.
Reproduit fidèlement le workflow n8n original avec le nÅ“ud "Code in JavaScript" intégré.
"""
import json
import re
from typing import Optional

import asyncio
import httpx
from openai import AsyncOpenAI
from serpapi import GoogleSearch

from app.core.config import settings
from app.core.database import get_pool
from app.services.db_service import (
    get_conversation_history,
    save_contacts_recents,
    save_demande_historique,
    save_conversation,
    search_prestataires_tool,
    search_prestataires_fallback,
)
from app.services.prompt_templates import SYSTEM_PROMPT

# ============================================================
# Client DeepSeek (SDK OpenAI compatible)
# ============================================================
client = AsyncOpenAI(
    api_key=settings.DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com",
    timeout=httpx.Timeout(25.0)
)

# ============================================================
# Définition de l'outil de recherche (Function Calling)
# Reproduit le nÅ“ud "Execute a SQL query in Postgres" n8n
# ============================================================
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "recherche_web_serpapi",
            "description": (
                "Effectue une recherche sur le web via Google (SerpApi). "
                "Utilise cet outil lorsque l'utilisateur pose une question générale, "
                "demande un conseil (cuisine, bricolage, devoirs, etc.), "
                "ou recherche une information/service qui ne figure pas dans notre catalogue d'artisans local. "
                "Fournis la requête de recherche la plus pertinente possible."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "La requête de recherche à envoyer à Google."
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_prestataires",
            "description": (
                "Recherche des prestataires de services dans la base de données. "
                "Utilise cet outil pour trouver des plombiers, électriciens, maçons, menuisiers, "
                "peintres, carreleurs, techniciens climatisation, serruriers, jardiniers, "
                "agents de nettoyage, déménageurs, informaticiens, couturiers, coiffeurs, "
                "mécaniciens, techniciens électroménager (frigo, lave-linge, TV) ou traiteurs en Côte d'Ivoire. "
                "Passe la catégorie et la ville comme paramètres. "
                "Appelle cet outil SYSTÃ‰MATIQUEMENT dès que l'utilisateur exprime un besoin de service."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "categorie": {
                        "type": "string",
                        "description": (
                            "La catégorie du service recherché, en minuscules "
                            "(ex: 'plombier', 'electricien', 'mecanicien', 'coiffeur', 'peintre', 'macon'). "
                            "Utilise le mot clé du métier exact tel qu'il apparaît dans le mapping."
                        ),
                    },
                    "ville": {
                        "type": "string",
                        "description": (
                            "La ville ou commune en Côte d'Ivoire "
                            "(ex: 'Abidjan', 'Cocody', 'Yopougon', 'Koumassi', 'Bouaké'). "
                            "Si l'utilisateur mentionne un quartier d'Abidjan, passe ce quartier directement. "
                            "Si non précisée, utilise '{user_location}'."
                        ),
                    },
                },
                "required": ["categorie", "ville"],
            },
        },
    }
]


# ============================================================
# PARSING JSON ROBUSTE
# Reproduit le nÅ“ud "Code in JavaScript" n8n
# ============================================================
def _parse_ai_response(content: str) -> dict:
    """
    Extrait et normalise le JSON de la réponse de l'IA de manière robuste.
    Reproduit la logique du nÅ“ud JavaScript n8n avec les mêmes fallbacks.
    """
    # Cas 1 : JSON pur (idéal avec response_format=json_object)
    try:
        return json.loads(content.strip())
    except (json.JSONDecodeError, ValueError):
        pass

    # Cas 2 : JSON dans un bloc markdown ```json ... ```
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    # Cas 3 : Premier objet JSON trouvé dans le texte libre
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            pass

    # Fallback total : structure minimale valide (comme n8n)
    return {
        "intention": "erreur",
        "categorie": None,
        "ville": "Abidjan",
        "quartier": None,
        "message_utilisateur": "",
        "reponse_texte": (
            "Je n'ai pas bien compris votre demande. "
            "Pouvez-vous préciser le service que vous recherchez ? "
            "Par exemple : plombier, électricien, maçon..."
        ),
        "prestataires": [],
    }


def _normalize_response(parsed: dict, user_message: str) -> dict:
    """
    Garantit que tous les champs obligatoires existent dans la réponse.
    Reproduit les guards du nÅ“ud JavaScript n8n.
    """
    if not parsed.get("intention"):
        parsed["intention"] = "recherche_prestataire"
    if "categorie" not in parsed:
        parsed["categorie"] = None
    if not parsed.get("ville"):
        parsed["ville"] = "Abidjan"
    if "quartier" not in parsed:
        parsed["quartier"] = None
    if not parsed.get("reponse_texte"):
        parsed["reponse_texte"] = "Voici les prestataires disponibles."
    if not isinstance(parsed.get("prestataires"), list):
        parsed["prestataires"] = []
    if not parsed.get("message_utilisateur"):
        parsed["message_utilisateur"] = user_message
    return parsed


# ============================================================
# FONCTION PRINCIPALE DE L'AGENT
# ============================================================
async def process_convcommerce(
    session_id: str,
    email: str,
    user_message: str,
    user_location: str,
) -> dict:
    """
    Orchestre le cycle complet de l'agent ConvCommerce CI :
    1. Récupération du contexte (historique de session)
    2. Premier appel DeepSeek avec response_format=json_object (comme n8n)
    3. Exécution SQL si l'IA appelle l'outil search_prestataires
    4. Fallback automatique sur zone élargie si aucun résultat local
    5. Deuxième appel DeepSeek avec les résultats SQL pour la réponse finale
    6. Parsing + normalisation JSON (nÅ“ud JavaScript n8n)
    7. Persistance asynchrone (conversations, historique, contacts)
    """
    pool = await get_pool()

    # â”€â”€ Ã‰tape 1 : Récupération de l'historique (max 10 messages) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    history = await get_conversation_history(pool, session_id, limit=10)

    # â”€â”€ Ã‰tape 2 : Construction du contexte de l'IA â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # On injecte user_location dans le prompt système ET dans la description de l'outil
    formatted_system = SYSTEM_PROMPT.format(user_location=user_location)
    
    # Injection de user_location dans la description de l'outil ville
    tools_with_location = json.loads(json.dumps(TOOLS))
    for tool in tools_with_location:
        if tool["function"]["name"] == "search_prestataires":
            tool["function"]["parameters"]["properties"]["ville"]["description"] = (
                tool["function"]["parameters"]["properties"]["ville"]["description"]
                .replace("{user_location}", user_location)
            )
            break

    messages: list[dict] = [{"role": "system", "content": formatted_system}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    # â”€â”€ Ã‰tape 3 : Premier appel DeepSeek â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # IMPORTANT : response_format=json_object est INCOMPATIBLE avec tool_choice
    # sur le premier appel. Le modèle doit choisir librement entre appeler
    # l'outil ou répondre directement. On ne force le JSON que sur le 2e appel.
    first_response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        tools=tools_with_location,
        tool_choice="auto",
        temperature=0.2,  # Très bas â†’ détection d'intention précise
        max_tokens=2048,
    )

    first_msg = first_response.choices[0].message
    raw_providers: list[dict] = []
    categorie_detectee: Optional[str] = None
    ville_detectee: str = user_location or "Abidjan"
    fallback_used: bool = False
    final_content: str = ""

    # â”€â”€ Ã‰tape 4 : Traitement du Function Calling â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if first_msg.tool_calls:
        tool_call = first_msg.tool_calls[0]

        if tool_call.function.name == "search_prestataires":
            args = json.loads(tool_call.function.arguments)
            categorie_detectee = args.get("categorie", "")
            ville_detectee = args.get("ville", user_location or "Abidjan")

            # Exécution de la requête SQL principale (avec sous_categorie + description)
            raw_providers = await search_prestataires_tool(
                pool, categorie_detectee, ville_detectee
            )

            # â”€â”€ Fallback automatique (comme n8n) : si aucun résultat local,
            # on relance sur toute la Côte d'Ivoire â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            if not raw_providers:
                fallback_used = True
                raw_providers = await search_prestataires_fallback(
                    pool, categorie_detectee
                )

            # Sérialisation du résultat pour l'envoyer à l'IA
            tool_result_json = json.dumps(
                raw_providers, ensure_ascii=False, default=str
            )

            # Ajout dans la conversation : réponse de l'IA + résultat de l'outil
            messages.append(first_msg)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result_json,
                }
            )

            # â”€â”€ Ã‰tape 5 : Deuxième appel DeepSeek (réponse finale) â”€â”€â”€â”€â”€â”€â”€â”€
            second_response = await client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                temperature=0.2,
                max_tokens=2048,
                response_format={"type": "json_object"},
            )
            final_content = second_response.choices[0].message.content or ""
        
        elif tool_call.function.name == "recherche_web_serpapi":
            args = json.loads(tool_call.function.arguments)
            raw_query = args.get("query", "")

            # â”€â”€ Normalisation de la requête â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            _STOP_WORDS = re.compile(
                r"\b(réputé|réputée|bon|bonne|meilleur|meilleure|trouve[- ]moi|"
                r"cherche[- ]moi|je veux|je cherche|s'il te plaît|stp|svp|"
                r"côte d.ivoire|cote d.ivoire)\b",
                re.IGNORECASE,
            )
            query = _STOP_WORDS.sub("", raw_query).strip()
            query = re.sub(r"\s{2,}", " ", query)
            if len(query) > 60:
                query = " ".join(query[:60].split()[:-1])

            # â”€â”€ Extraction des mots-clés de pertinence depuis la requête â”€â”€â”€â”€â”€â”€
            # On prend les 1-3 premiers mots significatifs (ex: ["pharmacie"] ou
            # ["maquis", "alloco"]) pour filtrer les résultats hors-sujet.
            _FILLER = re.compile(
                r"\b(à|au|aux|les|des|un|une|de|du|le|la|vers|près|autour|près de|"
                r"abidjan|cocody|yopougon|palmeraie|plateau|marcory|koumassi|"
                r"adjamé|abobo|riviera|angré|williamsville|deux plateaux)\b",
                re.IGNORECASE,
            )
            keyword_tokens = [w for w in _FILLER.sub("", query).split() if len(w) > 2]
            relevance_keywords = keyword_tokens[:3]  # ex: ["pharmacie"], ["maquis", "alloco"]
            logger.info(f"\n[SerpApi] query='{query}' | mots-clés pertinence={relevance_keywords}")

            def _is_relevant(title: str) -> bool:
                """Vérifie qu'un résultat contient au moins un mot-clé de la requête."""
                if not relevance_keywords:
                    return True  # pas de filtre si aucun mot-clé extrait
                title_lower = title.lower()
                return any(kw.lower() in title_lower for kw in relevance_keywords)

            tool_result_json = "Aucun résultat trouvé sur le web."
            if not settings.SERPAPI_API_KEY or not str(settings.SERPAPI_API_KEY).strip():
                tool_result_json = (
                    "Le service de recherche web est temporairement indisponible car la clé API SerpApi n'est pas configurée. "
                    "Réponds poliment à l'utilisateur que tu ne peux pas chercher sur le web pour le moment, "
                    "et propose-lui ton aide sur les services de notre catalogue."
                )
            else:
                try:
                    # â”€â”€ Passe unique : recherche standard, num=3 â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                    search = GoogleSearch({
                        "q": query,
                        "api_key": settings.SERPAPI_API_KEY,
                        "hl": "fr",
                        "gl": "ci",
                        "num": 3,
                    })
                    results = await asyncio.to_thread(search.get_dict)

                    logger.info(f"[SerpApi] clés={list(results.keys())}")
                    if "error" in results:
                        logger.info(f"[SerpApi ERROR DETAILS] {results['error']}")

                    # â”€â”€ Résultats structurés (compact, sans texte superflu) â”€â”€â”€
                    # On envoie des dicts légers au lieu de strings jointes.
                    structured_results = []

                    # Priorité 1 : local_results (lieux physiques)
                    local_items = results.get("local_results") or results.get("places") or []
                    if isinstance(local_items, dict):
                        local_items = local_items.get("places", [])
                    logger.info(f"[SerpApi] {len(local_items)} lieu(x) local(aux) trouvé(s)")

                    for place in local_items:
                        title = place.get("title") or place.get("name") or ""
                        if not _is_relevant(title):
                            logger.info(f"[SerpApi FILTER] Rejeté (hors-sujet) : '{title}'")
                            continue
                        entry = {"nom": title}
                        if place.get("address") or place.get("formatted_address"):
                            entry["adresse"] = place.get("address") or place["formatted_address"]
                        if place.get("rating"):
                            entry["note"] = str(place["rating"])
                        if place.get("phone"):
                            entry["telephone"] = place["phone"]
                        if place.get("hours") or place.get("open_state"):
                            entry["horaires"] = place.get("hours") or place["open_state"]
                        structured_results.append(entry)
                        if len(structured_results) == 3:
                            break

                    # Priorité 2 : organic_results si local vide
                    if not structured_results:
                        for r in results.get("organic_results", []):
                            title = r.get("title") or ""
                            if not _is_relevant(title):
                                logger.info(f"[SerpApi FILTER] Rejeté (hors-sujet) : '{title}'")
                                continue
                            entry = {"nom": title}
                            if r.get("snippet"):
                                entry["description"] = r["snippet"][:120]  # tronqué pour la légèreté
                            # Téléphone dans rich_snippets
                            phone = r.get("phone") or (
                                r.get("rich_snippet", {}).get("top", {}).get("extensions", [None])[0]
                            )
                            if phone and isinstance(phone, str) and any(c.isdigit() for c in phone):
                                entry["telephone"] = phone
                            structured_results.append(entry)
                            if len(structured_results) == 3:
                                break

                    if structured_results:
                        tool_result_json = json.dumps(
                            {"lieux_trouves": structured_results, "requete": query},
                            ensure_ascii=False,
                        )
                        logger.info(f"[SerpApi] {len(structured_results)} résultat(s) validés transmis à l'IA")
                    else:
                        tool_result_json = (
                            "Aucun résultat pertinent trouvé. "
                            "Informe l'utilisateur et génère un lien Google Maps vers : "
                            f"'{raw_query}'."
                        )
                        logger.info("[SerpApi] Aucun résultat pertinent â€” fallback Maps")

                except Exception as e:
                    logger.info(f"[SerpApi ERROR] {type(e).__name__}: {e}")
                    tool_result_json = (
                        f"Une erreur technique est survenue lors de la recherche web. "
                        f"Réponds poliment que la recherche a échoué. Détail : {str(e)}"
                    )


            messages.append(first_msg)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result_json,
                }
            )

            second_response = await client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                temperature=0.3,
                max_tokens=700,  # JSON court = génération rapide (3-5 prestataires max)
                response_format={"type": "json_object"},
            )
            final_content = second_response.choices[0].message.content or ""

    else:
        # Pas de tool call : l'IA a répondu directement (salutation, hors sujet, anti-injection)
        raw_text = first_msg.content or ""

        # On tente d'abord un parsing rapide (si c'est déjà du JSON valide)
        quick_parse = _parse_ai_response(raw_text)
        if quick_parse.get("intention") not in ("erreur", None) or "reponse_texte" in quick_parse:
            # Le modèle a bien retourné du JSON structuré â†’ on l'utilise tel quel
            final_content = raw_text
        else:
            # Le modèle a répondu en texte libre â†’ on force un 2e appel avec response_format
            # pour obtenir le JSON structuré (accueil, hors_sujet, anti-injection)
            messages.append({"role": "assistant", "content": raw_text})
            messages.append({
                "role": "user",
                "content": (
                    "Reformule ta réponse précédente STRICTEMENT en JSON selon le format "
                    "obligatoire défini dans tes instructions système. "
                    "Ne rajoute aucun texte en dehors du JSON."
                )
            })
            cleanup_response = await client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                temperature=0.1,
                max_tokens=512,
                response_format={"type": "json_object"},
            )
            final_content = cleanup_response.choices[0].message.content or raw_text


    # â”€â”€ Ã‰tape 6 : Parsing + normalisation (nÅ“ud JS n8n) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    parsed = _parse_ai_response(final_content)
    parsed = _normalize_response(parsed, user_message)

    # Si l'IA n'a pas injecté les prestataires elle-même (improbable mais sécurisé),
    # on les injecte directement depuis les résultats SQL
    if raw_providers and not parsed.get("prestataires"):
        parsed["prestataires"] = raw_providers

    # Ajustement du message si fallback utilisé (remplacement total pour éviter la contradiction)
    if fallback_used and raw_providers:
        parsed["reponse_texte"] = (
            f"Désolé, je n'ai pas trouvé de prestataire disponible à {ville_detectee} pour le moment. "
            f"Cependant, voici des professionnels qualifiés à proximité qui peuvent se déplacer chez vous :"
        )

    # Extraction des métadonnées depuis le JSON de l'IA
    ai_response_text: str = parsed.get("reponse_texte", "")

    # â”€â”€ Source unique de vérité pour TOUS les prestataires (SQL + web) â”€â”€â”€â”€â”€â”€
    # parsed["prestataires"] contient : résultats SQL injectés par l'IA (prestataire locaux)
    #                                  OU résultats SerpApi structurés (recherche web)
    # raw_providers = résultats SQL bruts (peut être vide pour les recherches web)
    final_providers: list[dict] = parsed.get("prestataires") or raw_providers or []
    
    # Sécurisation stricte de l'extraction comme demandé
    categorie_ia = parsed.get("categorie")
    if not categorie_detectee:
        # Pour recherche_web : l'IA met la catégorie dans parsed["categorie"]
        # Fallback sur le premier prestataire trouvé si disponible
        if categorie_ia:
            categorie_detectee = categorie_ia
        elif final_providers:
            categorie_detectee = final_providers[0].get("categorie") or "général"
        else:
            categorie_detectee = "général"
        
    ville_ia = parsed.get("ville")
    if ville_ia:
        ville_detectee = ville_ia
    elif not ville_detectee:
        ville_detectee = user_location or "Abidjan"

    # â”€â”€ Ã‰tape 7 : Persistance asynchrone en base de données â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # FIX : On sauvegarde final_providers (pas raw_providers) pour que
    # les résultats SerpApi soient réhydratés lors du rechargement historique.
    await save_conversation(
        pool,
        session_id=session_id,
        message_user=user_message,
        reponse_agent=ai_response_text,
        intention=parsed.get("intention"),
        categorie_detectee=categorie_detectee,
        ville_detectee=ville_detectee,
        prestataires_proposes=json.dumps(final_providers, ensure_ascii=False, default=str) if final_providers else None,
    )

    # FIX : On inclut les recherches web dans l'historique des demandes.
    # Condition élargie : tout ce qui n'est pas accueil/hors_sujet/erreur.
    if parsed.get("intention") not in ("accueil", "hors_sujet", "erreur"):
        # Titre : utilise la catégorie détectée (valide pour SQL et web)
        titre_demande = f"Demande : {categorie_detectee.capitalize()}"
        # Sous-titre : 1er prestataire trouvé, sinon la ville
        premier = final_providers[0] if final_providers else {}
        sous_titre = premier.get("nom_complet") or premier.get("nom") or ville_detectee
        await save_demande_historique(
            pool,
            email,
            session_id,
            titre=titre_demande,
            sous_titre=sous_titre,
        )

    # FIX : On sauvegarde final_providers dans les contacts récents.
    # Cela inclut désormais les résultats SerpApi.
    if final_providers:
        await save_contacts_recents(pool, email, final_providers)

    # â”€â”€ Réponse finale â€” format identique au nÅ“ud n8n "Code in JavaScript" â”€â”€
    return {
        "reponse_texte": ai_response_text,
        "prestataires": final_providers,
        "intention": parsed.get("intention", "recherche_prestataire"),
        "categorie": categorie_detectee,
        "ville": ville_detectee,
        "quartier": parsed.get("quartier"),
        "message_utilisateur": user_message,
        "session_id": session_id,
        "nb_prestataires": len(final_providers),
        "success": parsed.get("intention") != "erreur",
    }

