# Chat&Go Backend API 🇨🇮

Backend FastAPI natif pour l'application mobile **Chat&Go** — La plateforme de mise en relation entre clients et prestataires de services en Côte d'Ivoire.

Ce projet remplace l'ancienne architecture n8n hébergée sur Render, qui souffrait des limitations des disques éphémères (perte de configuration SQLite à chaque redémarrage). Le nouveau backend Python est **100% stateless** : toute la persistance est assurée par **PostgreSQL sur Neon**.

---

## Sommaire
1. [Architecture du projet](#1-architecture-du-projet)
2. [Prérequis](#2-prérequis)
3. [Configuration locale (`.env`)](#3-configuration-locale-env)
4. [Initialisation de la base de données Neon](#4-initialisation-de-la-base-de-données-neon)
5. [Lancement en local & tests Swagger](#5-lancement-en-local--tests-swagger)
6. [Déploiement sur Render](#6-déploiement-sur-render)
7. [Référence des endpoints API](#7-référence-des-endpoints-api)
8. [Variables d'environnement](#8-variables-denvironnement)
9. [Dépannage (Troubleshooting)](#9-dépannage-troubleshooting)

---

## 1. Architecture du projet

```plaintext
chatgo-backend/
├── app/
│   ├── main.py                          # Point d'entrée FastAPI (CORS, lifespan, /health)
│   ├── api/v1/
│   │   ├── api.py                       # Routeur principal — agrège tous les sous-routeurs
│   │   └── endpoints/
│   │       ├── auth.py                  # POST /auth-request-otp, /auth-verify-otp
│   │       ├── profile.py               # POST /update-profile
│   │       ├── chat.py                  # POST /convcommerce (Agent IA)
│   │       └── history.py               # POST /get-recent-contacts, /get-history, etc.
│   ├── core/
│   │   ├── config.py                    # Variables d'environnement via pydantic-settings
│   │   ├── database.py                  # Pool de connexions asyncpg (partagé)
│   │   └── mail.py                      # Envoi d'emails OTP via aiosmtplib (Gmail)
│   ├── models/
│   │   └── schemas.py                   # Modèles Pydantic (validation entrées/sorties)
│   └── services/
│       ├── prompt_templates.py          # System Prompt de l'agent (anti-injection, Nouchi)
│       ├── deepseek_service.py          # Logique IA : Function Calling, parsing JSON, WhatsApp
│       └── db_service.py               # Outils SQL pour l'agent (search_prestataires, historique)
├── init_db.py                           # Script one-shot de création des tables sur Neon
├── .env.example                         # Modèle de fichier de configuration
├── render.yaml                          # Blueprint de déploiement Render
└── requirements.txt                     # Dépendances Python
```

**Stack technique :**
- **Framework :** FastAPI + Uvicorn (ASGI)
- **Base de données :** PostgreSQL via `asyncpg` (requêtes SQL brutes, sans ORM)
- **IA :** DeepSeek `deepseek-chat` via le SDK OpenAI (Function Calling)
- **Email :** `aiosmtplib` (envoi SMTP asynchrone non-bloquant)
- **Validation :** Pydantic v2 + pydantic-settings
- **Hébergement :** Render (stateless) + Neon (PostgreSQL persistant)

---

## 2. Prérequis

Avant de commencer, assurez-vous d'avoir :

| Outil | Version | Vérification |
|---|---|---|
| Python | ≥ 3.11 | `python --version` |
| pip | Dernière version | `pip --version` |
| Git | Toute version récente | `git --version` |
| Compte Neon | [neon.tech](https://neon.tech) | Base de données créée |
| Compte DeepSeek | [platform.deepseek.com](https://platform.deepseek.com) | Clé API disponible |
| Compte Gmail | — | Mot de passe d'application généré |
| Compte Render | [render.com](https://render.com) | — |
| Compte GitHub | — | Repo créé et accessible |

> **Gmail — Mot de passe d'application :**
> Il ne faut **pas** utiliser votre vrai mot de passe Gmail.
> Générez un mot de passe d'application dédié ici :
> → [https://myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
> (Sélectionnez : Application = "Mail", Appareil = "Autre (nom personnalisé)" → "ChatAndGo")

---

## 3. Configuration locale (`.env`)

### Étape 1 — Copier le modèle
```bash
cp .env.example .env
```

### Étape 2 — Remplir toutes les valeurs

Ouvrez `.env` et remplissez **chaque variable** :

```env
# Récupérable dans le dashboard Neon → votre projet → Connection string
DATABASE_URL=postgresql://user:password@ep-xxx-yyy.eu-west-2.aws.neon.tech/neondb?sslmode=require

# Récupérable sur platform.deepseek.com → API Keys
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Laissez ces valeurs en dur (Gmail SMTP)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587

# Votre adresse Gmail
SMTP_USER=votre_email@gmail.com

# Le mot de passe d'application généré (16 caractères, sans espaces)
SMTP_PASSWORD=xxxxxxxxxxxx

# L'adresse affichée dans le champ "De:" des emails
EMAIL_FROM=noreply@chatandgo.ci
```

> ⚠️ **Ne committez jamais votre fichier `.env` sur GitHub.**
> Le `.gitignore` doit inclure `.env` (il est déjà présent dans le template).

---

## 4. Initialisation de la base de données Neon

> ✅ Cette étape ne s'exécute **qu'une seule fois**.

Le script `init_db.py` crée toutes les tables nécessaires sur votre base Neon.

### Étape 1 — Installer les dépendances
```bash
pip install -r requirements.txt
```

### Étape 2 — Exécuter le script de migration
```bash
python init_db.py
```

**Sortie attendue :**
```
🔌 Connexion à la base de données...
🏗️  Création des tables en cours...
✅ Toutes les tables ont été créées avec succès !

📋 Tables créées :
   ✓ users
   ✓ verification_codes
   ✓ prestataires
   ✓ avis
   ✓ conversations
   ✓ contacts_recents
   ✓ demandes_historique

🔌 Connexion fermée.
```

> Si vous avez déjà les tables `prestataires` et `avis` de l'ancien `init_db.py`,
> pas d'inquiétude : toutes les requêtes utilisent `CREATE TABLE IF NOT EXISTS`,
> donc aucune donnée ne sera perdue.

---

## 5. Lancement en local & tests Swagger

### Étape 1 — Démarrer le serveur de développement
```bash
uvicorn app.main:app --reload
```

**Sortie attendue :**
```
🚀 Démarrage de Chat&Go Backend — connexion à la base de données...
✅ Pool de connexions PostgreSQL initialisé.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
```

### Étape 2 — Ouvrir l'interface Swagger
Ouvrez votre navigateur sur : **[http://localhost:8000/docs](http://localhost:8000/docs)**

Vous verrez tous les endpoints organisés en 4 catégories :
- 🔐 Authentification
- 👤 Profil
- 🤖 Agent IA
- 📜 Historique

---

### 🧪 Scénario de test complet (dans l'ordre)

#### Test 1 — Demande d'OTP
```
POST /api/v1/auth/auth-request-otp
Body: { "email": "votre@email.com" }
```
✅ Attendu : Réception d'un email avec le code à 4 chiffres + `"dev_code"` dans la réponse.

#### Test 2 — Vérification OTP
```
POST /api/v1/auth/auth-verify-otp
Body: { "email": "votre@email.com", "code": "XXXX" }
```
✅ Attendu : `"isNewUser": true` + données utilisateur retournées.

#### Test 3 — Mise à jour du profil
```
POST /api/v1/profile/update-profile
Body: { "email": "votre@email.com", "nom": "Koné", "prenom": "Aya", "quartier": "Cocody" }
```
✅ Attendu : Profil mis à jour avec les nouvelles valeurs.

#### Test 4 — Agent IA (le plus important)
```
POST /api/v1/chat/convcommerce
Body: {
  "session_id": "test-session-001",
  "email": "votre@email.com",
  "message": "J'ai besoin d'un plombier à Cocody, l'eau est gâtée",
  "user_location": "Cocody"
}
```
✅ Attendu : Réponse JSON avec `"response"`, `"providers"` (liste de prestataires), `"categorie_detectee": "plombier"`.

#### Test 5 — Historique
```
POST /api/v1/history/get-history
Body: { "email": "votre@email.com" }
```
✅ Attendu : La demande du Test 4 apparaît dans l'historique.

---

## 6. Déploiement sur Render

### Étape 1 — Pousser le projet sur GitHub

```bash
git init
git add .
git commit -m "feat: Initial FastAPI backend for Chat&Go"
git remote add origin https://github.com/VOTRE_USERNAME/chatgo-backend.git
git push -u origin main
```

> ⚠️ Assurez-vous que `.env` est bien dans votre `.gitignore` avant de pusher !

---

### Étape 2 — Créer le Web Service sur Render

1. Connectez-vous sur [render.com](https://render.com)
2. Cliquez sur **"New +"** → **"Web Service"**
3. Connectez votre compte GitHub et sélectionnez le repo `chatgo-backend`
4. Remplissez les champs :

| Champ | Valeur |
|---|---|
| **Name** | `chatgo-backend` |
| **Runtime** | `Python 3` |
| **Build Command** | `pip install --upgrade pip && pip install -r requirements.txt` |
| **Start Command** | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| **Plan** | Free |

---

### Étape 3 — Configurer les variables d'environnement sur Render

Dans l'onglet **"Environment"** de votre service Render, ajoutez **chacune** de ces variables :

| Clé | Valeur |
|---|---|
| `DATABASE_URL` | Votre connection string Neon (avec `?sslmode=require`) |
| `DEEPSEEK_API_KEY` | Votre clé API DeepSeek |
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | Votre adresse Gmail |
| `SMTP_PASSWORD` | Votre mot de passe d'application Gmail (16 caractères) |
| `EMAIL_FROM` | `noreply@chatandgo.ci` (ou votre email) |

> 💡 **Astuce Render :** Pour les valeurs sensibles (`DATABASE_URL`, `DEEPSEEK_API_KEY`, `SMTP_PASSWORD`),
> cliquez sur l'icône "🔒 Secret" pour les masquer dans les logs.

---

### Étape 4 — Déployer

Cliquez sur **"Create Web Service"**. Render va :
1. Cloner votre repo GitHub
2. Exécuter `pip install -r requirements.txt`
3. Démarrer `uvicorn` sur le port assigné dynamiquement via `$PORT`
4. Effectuer un Health Check sur `/health` → doit retourner `{"status": "ok"}`

**Temps de déploiement estimé :** 2 à 4 minutes.

---

### Étape 5 — Vérifier le déploiement

Une fois déployé, votre API sera accessible sur :
```
https://chatgo-backend.onrender.com
```

Vérifications rapides :
```bash
# Health check
curl https://chatgo-backend.onrender.com/health
# → {"status":"ok"}

# Documentation Swagger
# Ouvrir dans le navigateur :
https://chatgo-backend.onrender.com/docs
```

---

### Étape 6 — Mettre à jour l'app React Native

Dans votre fichier de configuration des services (ex: `services/authService.js`, `services/aiService.js`),
remplacez les anciennes URLs n8n par les nouvelles URLs FastAPI :

```javascript
// AVANT (n8n)
const BASE_URL = "https://votre-n8n.onrender.com/webhook/...";

// APRÈS (FastAPI)
const BASE_URL = "https://chatgo-backend.onrender.com/api/v1";

// Exemples de nouveaux endpoints :
// Auth    : POST ${BASE_URL}/auth/auth-request-otp
// Chat    : POST ${BASE_URL}/chat/convcommerce
// Profil  : POST ${BASE_URL}/profile/update-profile
// Historique : POST ${BASE_URL}/history/get-history
```

---

## 7. Référence des endpoints API

### 🔐 Authentification (`/api/v1/auth`)

| Méthode | Endpoint | Body | Description |
|---|---|---|---|
| `POST` | `/auth-request-otp` | `{"email": "..."}` | Génère et envoie un OTP par email |
| `POST` | `/auth-verify-otp` | `{"email": "...", "code": "XXXX"}` | Vérifie l'OTP et connecte l'utilisateur |

### 👤 Profil (`/api/v1/profile`)

| Méthode | Endpoint | Body | Description |
|---|---|---|---|
| `POST` | `/update-profile` | `{"email", "nom", "prenom", "quartier", "photo_url"}` | Met à jour le profil |

### 🤖 Agent IA (`/api/v1/chat`)

| Méthode | Endpoint | Body | Description |
|---|---|---|---|
| `POST` | `/convcommerce` | `{"session_id", "email", "message", "user_location"}` | Envoie un message à l'agent IA |

### 📜 Historique (`/api/v1/history`)

| Méthode | Endpoint | Body | Description |
|---|---|---|---|
| `POST` | `/get-recent-contacts` | `{"email": "..."}` | 2 derniers prestataires contactés |
| `POST` | `/get-history` | `{"email": "..."}` | Historique des sessions |
| `POST` | `/get-conversation` | `{"session_id": "...", "email": "..."}` | Messages d'une session |
| `POST` | `/clear-history` | `{"email": "..."}` | Supprime tout l'historique |

### 🏥 Santé

| Méthode | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check pour Render |
| `GET` | `/` | Infos de base de l'API |

---

## 8. Variables d'environnement

| Variable | Obligatoire | Exemple | Description |
|---|---|---|---|
| `DATABASE_URL` | ✅ Oui | `postgresql://user:pass@host/db?sslmode=require` | Connection string Neon |
| `DEEPSEEK_API_KEY` | ✅ Oui | `sk-xxxx` | Clé API DeepSeek |
| `SMTP_HOST` | ✅ Oui | `smtp.gmail.com` | Serveur SMTP |
| `SMTP_PORT` | ✅ Oui | `587` | Port SMTP (TLS) |
| `SMTP_USER` | ✅ Oui | `you@gmail.com` | Adresse Gmail expéditrice |
| `SMTP_PASSWORD` | ✅ Oui | `xxxx xxxx xxxx xxxx` | Mot de passe d'application Gmail |
| `EMAIL_FROM` | ✅ Oui | `noreply@chatandgo.ci` | Adresse affichée dans le champ "De:" |

---

## 9. Dépannage (Troubleshooting)

### ❌ `pydantic_settings.main.SettingsError` au démarrage
**Cause :** Une variable d'environnement obligatoire est manquante.
**Solution :** Vérifiez que votre fichier `.env` existe et contient toutes les variables listées dans la section 8.

### ❌ `asyncpg.exceptions.ConnectionDoesNotExistError`
**Cause :** La `DATABASE_URL` est incorrecte ou Neon est injoignable.
**Solution :**
1. Vérifiez la connection string dans le dashboard Neon.
2. Assurez-vous que `?sslmode=require` est bien présent à la fin de l'URL.

### ❌ L'email OTP n'arrive pas
**Cause :** Mauvais mot de passe ou Gmail bloque la connexion.
**Solution :**
1. Vérifiez que vous utilisez un **mot de passe d'application** (pas votre vrai mot de passe).
2. Activez la validation en 2 étapes sur votre compte Google (obligatoire pour les mots de passe d'application).
3. Vérifiez le `dev_code` dans la réponse API pour tester sans email.

### ❌ L'agent IA retourne une erreur 500
**Cause :** Clé DeepSeek invalide, quota épuisé, ou timeout.
**Solution :**
1. Vérifiez votre `DEEPSEEK_API_KEY` sur [platform.deepseek.com](https://platform.deepseek.com).
2. Consultez les logs dans l'onglet "Logs" de votre service Render.

### ❌ Sur Render : le service se met en veille après inactivité (plan gratuit)
**Comportement attendu sur le plan Free :** Render met les services en veille après 15 minutes d'inactivité.
Le premier appel après la mise en veille peut prendre 30 à 60 secondes (cold start).
**Solution :** Utiliser un service externe de ping (ex: [UptimeRobot](https://uptimerobot.com)) pour envoyer une requête `GET /health` toutes les 10 minutes.

### ❌ `AttributeError: 'NoneType' object has no attribute 'tool_calls'`
**Cause :** DeepSeek a retourné une réponse vide ou nulle.
**Solution :** Vérifiez les logs Render. Si le quota DeepSeek est épuisé, la réponse peut être vide.

---

## Licence

Projet privé — Chat&Go © 2026. Tous droits réservés.
