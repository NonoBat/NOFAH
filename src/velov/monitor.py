"""Surveillance du modèle en exploitation (S6).

Mesure :
1. La dérive des features avec Evidently (DataDriftPreset) entre la semaine de
   référence (première semaine de test) et la période surveillée (courant).
2. L'erreur réelle du modèle (MAE) face à la baseline de persistance sur les
   prédictions dont la vérité terrain (H+1) est arrivée.

Usage :
    python -m velov.monitor --period normal
    python -m velov.monitor --period froid
    python -m velov.monitor --period demenagement
    python -m velov.monitor --period db
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from evidently import DataDefinition, Dataset, Report
from evidently.presets import DataDriftPreset
from sqlalchemy import create_engine

from velov.features import FEATURES, add_features
from velov.replay import apply_scenario, last_days, shift_to_this_week
from velov.train import METADATA_FILENAME, load_table, sha256_of, temporal_split

NUMERICAL_COLS = ["temperature", "bikes_available", "occupancy_rate", "predicted_bikes"]
CATEGORICAL_COLS = ["is_raining"]
ALL_MONITORED = NUMERICAL_COLS + CATEGORICAL_COLS


def load_model(model_dir: Path) -> tuple[object, dict]:
    """Charge le modèle et vérifie son empreinte SHA-256."""
    metadata_path = model_dir / METADATA_FILENAME
    if not metadata_path.exists():
        raise FileNotFoundError(f"{metadata_path} introuvable")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    model_path = model_dir / metadata["artifact"]["file"]
    actual = sha256_of(model_path)
    if actual != metadata["artifact"]["sha256"]:
        raise RuntimeError(f"Empreinte invalide pour {model_path} : artefact corrompu")
    return joblib.load(model_path), metadata


def get_reference_dataset(data_path: Path, model_dir: Path) -> tuple[pd.DataFrame, str]:
    """Extrait la 1re semaine de la fenêtre de test et calcule ses prédictions."""
    df = load_table(data_path)
    _, test = temporal_split(df, test_days=14)
    ref = test.sort_values(["timestamp", "station_id"]).head(3360).copy()
    ref = add_features(ref)

    model, metadata = load_model(model_dir)
    ref["predicted_bikes"] = np.clip(
        model.predict(ref[FEATURES]), 0, ref["capacity"].to_numpy()
    )
    ref["occupancy_rate"] = (ref["bikes_available"] / ref["capacity"]).round(4)
    return ref, metadata.get("model_version", "0.1.0")


def load_current_from_db(database_url: str) -> pd.DataFrame:
    """Charge les 3 360 dernières prédictions journalisées en base."""
    engine = create_engine(database_url)
    query = """
        SELECT station_id, observed_at AS timestamp, capacity, bikes_available,
               temperature, is_raining, predicted_bikes, model_version
        FROM predictions
        ORDER BY observed_at DESC
        LIMIT 3360
    """
    df = pd.read_sql(query, engine)
    if df.empty:
        raise ValueError("Aucune prédiction trouvée en base de données.")
    df = df.sort_values(["timestamp", "station_id"]).reset_index(drop=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["occupancy_rate"] = (df["bikes_available"] / df["capacity"]).round(4)
    return df


def generate_current_dataset(
    data_path: Path, model_dir: Path, scenario: str
) -> pd.DataFrame:
    """Simule la semaine rejouée selon le scénario (normal, froid, demenagement)."""
    raw = load_table(data_path)
    week = last_days(raw, days=7)
    week = apply_scenario(week, scenario)
    week = shift_to_this_week(week)
    week = add_features(week)

    model, _ = load_model(model_dir)
    week["predicted_bikes"] = np.clip(
        model.predict(week[FEATURES]), 0, week["capacity"].to_numpy()
    )
    week["occupancy_rate"] = (week["bikes_available"] / week["capacity"]).round(4)
    return week.sort_values(["timestamp", "station_id"]).reset_index(drop=True)


def compute_drift(
    current: pd.DataFrame, reference: pd.DataFrame, output_html: Path | None = None
) -> dict[str, float]:
    """Calcule le rapport de dérive Evidently (S6 · 20)."""
    data_def = DataDefinition(
        numerical_columns=NUMERICAL_COLS,
        categorical_columns=CATEGORICAL_COLS,
    )
    snap = Report([DataDriftPreset()]).run(
        Dataset.from_pandas(current[ALL_MONITORED], data_definition=data_def),
        Dataset.from_pandas(reference[ALL_MONITORED], data_definition=data_def),
    )

    if output_html:
        output_html.parent.mkdir(parents=True, exist_ok=True)
        snap.save_html(str(output_html))

    # Extraction des scores de dérive depuis snap.dict()
    res = snap.dict()
    metrics = res.get("metrics", [])
    drift_scores = {}
    for m in metrics:
        if isinstance(m, dict) and "drift_by_columns" in m:
            for col, details in m["drift_by_columns"].items():
                if isinstance(details, dict):
                    score = details.get("drift_score", 0.0)
                else:
                    score = getattr(details, "drift_score", 0.0)
                drift_scores[col] = round(float(score), 3)
    return drift_scores


def evaluate_performance(df: pd.DataFrame) -> tuple[int, float, float, float, dict]:
    """Évalue la MAE modèle et persistance par jointure à t + 1 h."""
    ordered = df.sort_values(["station_id", "timestamp"]).copy()
    ordered["next_ts"] = ordered["timestamp"] + pd.Timedelta(hours=1)

    # Vérité terrain : disponibilité observée à t + 1 h
    truth = ordered[["station_id", "timestamp", "bikes_available"]].rename(
        columns={"timestamp": "next_ts", "bikes_available": "y_true"}
    )
    merged = pd.merge(ordered, truth, on=["station_id", "next_ts"], how="inner")

    n_eval = len(merged)
    y_true = merged["y_true"].to_numpy()
    y_pred = merged["predicted_bikes"].to_numpy()
    y_persist = merged["bikes_available"].to_numpy()

    mae_model = round(float(np.mean(np.abs(y_pred - y_true))), 3)
    mae_persist = round(float(np.mean(np.abs(y_persist - y_true))), 3)
    ratio = round(mae_model / mae_persist, 2) if mae_persist > 0 else 1.0

    # Analyse par station
    merged["err_model"] = np.abs(y_pred - y_true)
    merged["err_persist"] = np.abs(y_persist - y_true)
    by_station = (
        merged.groupby("station_id")[["err_model", "err_persist"]]
        .mean()
        .assign(ratio=lambda x: (x["err_model"] / x["err_persist"]).round(2))
    )
    underperforming = by_station[by_station["ratio"] > 1.0].to_dict(orient="index")

    return n_eval, mae_model, mae_persist, ratio, underperforming


def main() -> None:
    parser = argparse.ArgumentParser(description="Surveillance du modèle Vélo'v (S6).")
    parser.add_argument(
        "--period",
        choices=["normal", "froid", "demenagement", "db"],
        default="normal",
        help="scénario à surveiller ou 'db' pour lire la table PostgreSQL",
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=Path("data/velov_history.csv"),
        help="chemin du CSV historique",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path("models"),
        help="dossier du modèle",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=os.getenv("DATABASE_URL"),
        help="URL PostgreSQL (si --period db)",
    )
    parser.add_argument(
        "--output-html",
        type=Path,
        default=Path("reports/drift.html"),
        help="fichier où sauvegarder le rapport HTML Evidently",
    )
    parser.add_argument(
        "--alert-threshold",
        type=float,
        default=0.90,
        help="seuil de ratio MAE_modèle / MAE_persistance déclenchant une alerte",
    )
    args = parser.parse_args()

    ref_df, model_version = get_reference_dataset(args.data, args.model_dir)

    if args.period == "db":
        db_url = args.database_url or "postgresql://postgres:PwdDb@127.0.0.1:5432/velov"
        print(f"Chargement des données courantes depuis la base : {db_url}...")
        cur_df = load_current_from_db(db_url)
    else:
        cur_df = generate_current_dataset(args.data, args.model_dir, args.period)

    # 1. Calcul de la dérive
    drift_scores = compute_drift(cur_df, ref_df, args.output_html)

    # 2. Performance
    n_eval, mae_model, mae_persist, ratio, underperforming = evaluate_performance(cur_df)

    # 3. Affichage du rapport (format S6 · 07)
    print()
    print("=" * 60)
    print(f"Rapport de surveillance · Scénario : {args.period}")
    print(f"Modèle {model_version} · référence {len(ref_df)} · courant {len(cur_df)}")
    print("=" * 60)
    print("Dérive (score par colonne, seuil > 0.1) :")
    for col, score in sorted(drift_scores.items()):
        drifted = " [DÉRIVE DÉTECTÉE]" if score > 0.1 else ""
        print(f"  {col:<18} : {score:.3f}{drifted}")

    print()
    print(f"Performance sur {n_eval} prédictions :")
    print(f"  MAE modèle       : {mae_model:.3f}")
    print(f"  MAE persistance  : {mae_persist:.3f} (ratio {ratio:.2f})")

    if ratio >= args.alert_threshold:
        print(f"\n⚠️  ALERTE PERFORMANCE : Le ratio ({ratio:.2f}) dépasse le seuil critique ({args.alert_threshold:.2f}) !")
        print("    Conduite à tenir : Analyser les segments et planifier un réentraînement (voir runbook).")
    else:
        print("\n✅  Pas d'alerte de performance (le modèle bat nettement la persistance).")

    if underperforming:
        print("\nStations décrochant par rapport à la persistance (ratio > 1.0) :")
        for st_id, stats in underperforming.items():
            print(f"  Station {st_id:<3} : MAE modèle {stats['err_model']:.2f} vs persist {stats['err_persist']:.2f} (ratio {stats['ratio']:.2f})")

    if args.output_html and args.output_html.exists():
        print(f"\nRapport HTML Evidently généré dans : {args.output_html}")
    print("=" * 60)


if __name__ == "__main__":
    main()
