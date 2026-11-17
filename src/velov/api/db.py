# Nous utilisons le fichier db.py afin de faire la création de la table qui enregistre les prédictions.
# Méthode utilisées :
# get_connection() qui permet de se connecter à la base de données
# init_db() qui permet de créer la table
# save_prediction() qui permet d'enregistrer une prédiction
# Pourquoi le choix de faire une requête SQL directement ? Simplicité et rapidité.

from __future__ import annotations

import logging
import os

import psycopg

logger = logging.getLogger("velov.api.db")

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS predictions (
    id              SERIAL PRIMARY KEY,
    station_id      INTEGER   NOT NULL,
    ts_input        TIMESTAMPTZ NOT NULL,
    capacity        INTEGER   NOT NULL,
    bikes_available INTEGER   NOT NULL,
    temperature     REAL      NOT NULL,
    is_raining      BOOLEAN   NOT NULL,
    predicted_bikes REAL      NOT NULL,
    model_version   TEXT      NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

INSERT_SQL = """
INSERT INTO predictions
    (station_id, ts_input, capacity, bikes_available,
     temperature, is_raining, predicted_bikes, model_version)
VALUES
    (%(station_id)s, %(ts_input)s, %(capacity)s, %(bikes_available)s,
     %(temperature)s, %(is_raining)s, %(predicted_bikes)s, %(model_version)s);
"""


def get_connection() -> psycopg.Connection:
    url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
    return psycopg.connect(url)


def init_db() -> None:
    if "DATABASE_URL" not in os.environ:
        logger.info("DATABASE_URL absent : journalisation désactivée.")
        return
    try:
        with get_connection() as conn:
            conn.execute(CREATE_TABLE_SQL)
            conn.commit()
        logger.info("Table predictions OK.")
    except Exception:
        logger.exception("Impossible d'initialiser la base de données.")
        raise


def save_prediction(
    *,
    station_id: int,
    ts_input,
    capacity: int,
    bikes_available: int,
    temperature: float,
    is_raining: bool,
    predicted_bikes: float,
    model_version: str,
) -> None:
    # Enregistrement de la prédiction.
    if "DATABASE_URL" not in os.environ:
        return
    try:
        with get_connection() as conn:
            conn.execute(
                INSERT_SQL,
                {
                    "station_id": station_id,
                    "ts_input": ts_input,
                    "capacity": capacity,
                    "bikes_available": bikes_available,
                    "temperature": temperature,
                    "is_raining": is_raining,
                    "predicted_bikes": predicted_bikes,
                    "model_version": model_version,
                },
            )
            conn.commit()
    except Exception:
        logger.exception("Échec de l'enregistrement de la prédiction en base.")
