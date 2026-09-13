import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# Schema complet pour Chat&Go Backend
# Tables ajoutées par rapport à init_db.py originel :
#   - users (authentification & profil)
#   - verification_codes (OTPs temporaires)
#   - contacts_recents (historique prestataires contactés)
#   - demandes_historique (log des sessions IA)
#   - conversations (messages avec l'agent IA)
# ============================================================
SCHEMA_SQL = """
-- Extension UUID (nécessaire pour gen_random_uuid)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- AUTHENTIFICATION & PROFILS
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email               VARCHAR(255) UNIQUE NOT NULL,
    nom                 VARCHAR(100) DEFAULT '',
    prenom              VARCHAR(100) DEFAULT '',
    ville_par_defaut    VARCHAR(100) DEFAULT 'Abidjan',
    quartier_par_defaut VARCHAR(100) DEFAULT '',
    photo_url           TEXT DEFAULT '',
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS verification_codes (
    id          SERIAL PRIMARY KEY,
    email       VARCHAR(255) NOT NULL,
    code_otp    VARCHAR(6) NOT NULL,
    expires_at  TIMESTAMP WITH TIME ZONE NOT NULL
);

-- ============================================================
-- PRESTATAIRES & MÉTIERS
-- ============================================================
CREATE TABLE IF NOT EXISTS prestataires (
    id                  SERIAL PRIMARY KEY,
    nom                 VARCHAR(255) NOT NULL,
    prenom              VARCHAR(255),
    categorie           VARCHAR(100) NOT NULL,
    sous_categorie      VARCHAR(100),
    ville               VARCHAR(100) NOT NULL,
    quartier            VARCHAR(100),
    telephone           VARCHAR(20) NOT NULL,
    whatsapp            VARCHAR(20),
    description         TEXT,
    experience_annees   INTEGER,
    tarif_min           INTEGER,
    tarif_max           INTEGER,
    unite_tarif         VARCHAR(50) DEFAULT 'par intervention',
    note_moyenne        DECIMAL(2,1) DEFAULT 0.0,
    nb_avis             INTEGER DEFAULT 0,
    disponible          BOOLEAN DEFAULT TRUE,
    zone_intervention   TEXT[],
    langues             TEXT[] DEFAULT ARRAY['Français'],
    photo_url           TEXT,
    verified            BOOLEAN DEFAULT FALSE,
    date_inscription    TIMESTAMP DEFAULT NOW(),
    actif               BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS avis (
    id              SERIAL PRIMARY KEY,
    prestataire_id  INTEGER REFERENCES prestataires(id) ON DELETE CASCADE,
    note            SMALLINT CHECK (note BETWEEN 1 AND 5),
    commentaire     TEXT,
    date_avis       TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- CONVERSATIONS & HISTORIQUE IA
-- ============================================================
CREATE TABLE IF NOT EXISTS conversations (
    id          SERIAL PRIMARY KEY,
    session_id  VARCHAR(100) NOT NULL,
    user_email  VARCHAR(255),
    role        VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content     TEXT NOT NULL,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS contacts_recents (
    id                  SERIAL PRIMARY KEY,
    user_email          VARCHAR(255) NOT NULL,
    prestataire_id      INT REFERENCES prestataires(id) ON DELETE SET NULL,
    last_contacted_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS demandes_historique (
    id                      SERIAL PRIMARY KEY,
    user_email              VARCHAR(255) NOT NULL,
    session_id              VARCHAR(100),
    requete_initiale        TEXT,
    categorie_identifiee    VARCHAR(100),
    commune                 VARCHAR(100),
    created_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================
-- INDEX POUR LES PERFORMANCES
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_prestataires_categorie  ON prestataires(categorie);
CREATE INDEX IF NOT EXISTS idx_prestataires_ville       ON prestataires(ville);
CREATE INDEX IF NOT EXISTS idx_prestataires_disponible  ON prestataires(disponible);
CREATE INDEX IF NOT EXISTS idx_prestataires_actif       ON prestataires(actif);
CREATE INDEX IF NOT EXISTS idx_conversations_session    ON conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_conversations_email      ON conversations(user_email);
CREATE INDEX IF NOT EXISTS idx_demandes_email           ON demandes_historique(user_email);
CREATE INDEX IF NOT EXISTS idx_contacts_email           ON contacts_recents(user_email);
CREATE INDEX IF NOT EXISTS idx_verification_email       ON verification_codes(email);
"""


async def main():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("❌ La variable d'environnement DATABASE_URL est manquante.")

    print("🔌 Connexion à la base de données...")
    conn = await asyncpg.connect(database_url)

    try:
        print("🏗️  Création des tables en cours...")
        await conn.execute(SCHEMA_SQL)
        print("✅ Toutes les tables ont été créées avec succès !")
        print("\n📋 Tables créées :")
        tables = ["users", "verification_codes", "prestataires", "avis",
                  "conversations", "contacts_recents", "demandes_historique"]
        for t in tables:
            print(f"   ✓ {t}")
    except Exception as e:
        print(f"❌ Erreur lors de la création des tables : {e}")
        raise
    finally:
        await conn.close()
        print("\n🔌 Connexion fermée.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
