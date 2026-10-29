from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
from pathlib import Path

import joblib
import mlflow
import mlflow.data
import pandas as pd
from mlflow.models import infer_signature
from sklearn.pipeline import Pipeline

from velov.features import FEATURES, make_training_frame

logger = logging.getLogger("velov.tracking")

MODEL_NAME = "velov-availability"
SKOPS_TRUSTED_TYPES = ["sklearn.ensemble._hist_gradient_boosting.predictor.TreePredictor"]


def git_state() -> dict[str, str]:
    """Récupère l'état du dépôt git (commit court et flag dirty)."""
    git_bin = shutil.which("git") or "git"
    try:
        commit = subprocess.check_output(  # noqa: S603
            [git_bin, "rev-parse", "--short", "HEAD"], text=True
        ).strip()
        status = subprocess.check_output(  # noqa: S603
            [git_bin, "status", "--porcelain"], text=True
        ).strip()
        dirty = "true" if bool(status) else "false"
        return {"git_commit": commit, "git_dirty": dirty}
    except Exception:
        logger.warning("Impossible de lire l'état git.")
        return {"git_commit": "unknown", "git_dirty": "unknown"}


def compute_data_fingerprint(df: pd.DataFrame) -> str:
    cols = [c for c in ["station_id", "timestamp", "capacity", "bikes_available"] if c in df.columns]
    if not cols:
        cols = list(df.columns)
    sorted_df = df.sort_values([c for c in ["station_id", "timestamp"] if c in cols])[cols]
    hashes = pd.util.hash_pandas_object(sorted_df, index=False)
    return hashlib.sha256(hashes.to_numpy().tobytes()).hexdigest()[:8]


def log_run(
    metadata: dict,
    out_dir: Path,
    raw_df: pd.DataFrame | None = None,
    register: bool = True,
) -> str:
    """Journalise le run, les métriques, paramètres, tags et artefacts dans MLflow."""
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(MODEL_NAME)

    model_path = out_dir / metadata["artifact"]["file"]
    pipeline: Pipeline = joblib.load(model_path)

    # Échantillon pour inférer la signature du modèle
    if raw_df is not None and not raw_df.empty:
        sample_raw = raw_df.head(5)
    else:
        sample_raw = pd.DataFrame(
            {
                "station_id": [1, 1],
                "timestamp": pd.to_datetime(["2026-06-01T06:00Z", "2026-06-01T07:00Z"]),
                "capacity": [20, 20],
                "bikes_available": [8, 5],
                "temperature": [21.0, 22.0],
                "is_raining": [False, False],
            }
        )
    sample = make_training_frame(sample_raw)[FEATURES]

    # Construction des tags (git, empreinte, période)
    tags = git_state()
    if raw_df is not None and not raw_df.empty:
        fingerprint = compute_data_fingerprint(raw_df)
        ts = pd.to_datetime(raw_df["timestamp"])
        tags.update(
            {
                "data_sha256": fingerprint,
                "data_table": "station_hourly",
                "data_period": f"du {ts.min().strftime('%Y-%m-%d')} au {ts.max().strftime('%Y-%m-%d')} (UTC)",
                "data_start": ts.min().strftime("%Y-%m-%d"),
                "data_end": ts.max().strftime("%Y-%m-%d"),
            }
        )
    else:
        tags["data_sha256"] = metadata.get("data_sha256", "unknown")

    run_name = f"v{metadata['model_version']}"
    with mlflow.start_run(run_name=run_name) as run:
        # 1. Paramètres : seed, learning_rate, max_iter, test_days
        params = metadata.get("params", {})
        if params:
            mlflow.log_params(params)

        # 2. Métriques de test : mae_model, mae_baseline_persistence, mae_model_peak_hours
        metrics = {k: v for k, v in metadata.get("metrics", {}).items() if k.startswith("mae_")}
        mlflow.log_metrics(metrics)

        # 3. Tags : commit git, git_dirty, empreinte et période des données
        mlflow.set_tags(tags)

        # 4. Données d'entraînement (log_input)
        if raw_df is not None and not raw_df.empty:
            try:
                dataset = mlflow.data.from_pandas(raw_df, name="station_hourly")
                mlflow.log_input(dataset, context="training")
            except Exception as e:
                logger.debug("Échec log_input dataset: %s", e)

        # 5. Modèle avec signature
        signature = infer_signature(sample, pipeline.predict(sample))
        model_info = mlflow.sklearn.log_model(
            pipeline,
            name="model",
            signature=signature,
            input_example=sample,
            serialization_format="skops",
            skops_trusted_types=SKOPS_TRUSTED_TYPES,
            registered_model_name=MODEL_NAME if register else None,
        )

        # 6. Artefacts : le paquet model.joblib + metadata.json
        mlflow.log_artifacts(str(out_dir), artifact_path="package")

        if register and model_info.registered_model_version is not None:
            try:
                client = mlflow.MlflowClient()
                client.set_registered_model_alias(MODEL_NAME, "challenger", str(model_info.registered_model_version))
            except Exception as e:
                logger.warning("Échec attribution alias challenger: %s", e)

        return run.info.run_id
