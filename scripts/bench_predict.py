from __future__ import annotations

import argparse
import time
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from velov.api.main import load_model
from velov.api.schemas import PredictionRequest, PredictionResponse
from velov.features import FEATURES, add_features


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=500, help="Nombre d'itérations mesurées (défaut 500)")
    parser.add_argument("--warmup", type=int, default=50, help="Nombre d'itérations d'échauffement (défaut 50)")
    parser.add_argument(
        "--batch",
        type=int,
        nargs="+",
        default=[1, 10, 100, 1000],
        help="Tailles de lots à tester pour model.predict (défaut : 1 10 100 1000)",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path("models"),
        help="Dossier contenant le modèle et ses métadonnées (défaut : models)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    print(f"Chargement du modèle depuis {args.model_dir} (hors mesure)...")
    model, metadata = load_model(args.model_dir)
    version = metadata.get("model_version", "0.1.0")

    raw_dict = {
        "station_id": 2,
        "timestamp": "2026-10-06T08:00:00+02:00",
        "capacity": 20,
        "bikes_available": 12,
        "temperature": 14.5,
        "is_raining": False,
    }

    print(f"\n1. Mesure des 4 étapes de _predict() ({args.n} itérations, {args.warmup} échauffements)...")

    # Échauffement
    for _ in range(args.warmup):
        req = PredictionRequest.model_validate(raw_dict)
        raw_df = pd.DataFrame([req.model_dump()])
        feat_df = add_features(raw_df)[FEATURES]
        preds = model.predict(feat_df)
        clipped = np.clip(preds, 0, raw_df["capacity"].to_numpy())
        _ = [
            PredictionResponse(
                station_id=req.station_id,
                target_timestamp=req.timestamp + timedelta(hours=1),
                predicted_bikes=round(float(clipped[0]), 2),
                model_version=version,
            )
        ]

    # Mesures individuelles
    times_pydantic = []
    times_features = []
    times_predict = []
    times_response = []

    for _ in range(args.n):
        # Étape 1 : Validation Pydantic
        t0 = time.perf_counter()
        req = PredictionRequest.model_validate(raw_dict)
        t1 = time.perf_counter()
        times_pydantic.append((t1 - t0) * 1000)

        # Étape 2 : DataFrame + add_features
        t0 = time.perf_counter()
        raw_df = pd.DataFrame([req.model_dump()])
        feat_df = add_features(raw_df)[FEATURES]
        t1 = time.perf_counter()
        times_features.append((t1 - t0) * 1000)

        # Étape 3 : model.predict, 1 ligne
        t0 = time.perf_counter()
        preds = model.predict(feat_df)
        t1 = time.perf_counter()
        times_predict.append((t1 - t0) * 1000)

        # Étape 4 : Bornage et réponse
        t0 = time.perf_counter()
        clipped = np.clip(preds, 0, raw_df["capacity"].to_numpy())
        _ = [
            PredictionResponse(
                station_id=req.station_id,
                target_timestamp=req.timestamp + timedelta(hours=1),
                predicted_bikes=round(float(clipped[0]), 2),
                model_version=version,
            )
        ]
        t1 = time.perf_counter()
        times_response.append((t1 - t0) * 1000)

    # Calcul percentiles
    steps = [
        ("Validation Pydantic", times_pydantic),
        ("DataFrame + add_features", times_features),
        ("model.predict, 1 ligne", times_predict),
        ("Bornage et réponse", times_response),
    ]

    p50_total = sum(float(np.percentile(t, 50)) for _, t in steps)

    print("\n| Étape | p50 (ms) | p95 (ms) | Part du temps |")
    print("| :--- | :--- | :--- | :--- |")
    for name, t in steps:
        p50 = float(np.percentile(t, 50))
        p95 = float(np.percentile(t, 95))
        part = 100 * p50 / p50_total if p50_total > 0 else 0
        print(f"| {name} | {p50:.3f} ms | {p95:.3f} ms | {part:.1f} % |")
    print(f"| **Total calcul interne** | **{p50_total:.3f} ms** | **-** | **100 %** |")

    # 2. Mesure de model.predict selon la taille du lot
    print(f"\n2. Mesure de model.predict sur des lots de taille croissante ({args.n} itérations par lot)...")
    base_req = PredictionRequest.model_validate(raw_dict)
    base_feat = add_features(pd.DataFrame([base_req.model_dump()]))[FEATURES]

    print("\n| Taille du lot | Temps du lot p50 (ms) | Temps du lot p95 (ms) | Temps par prédiction |")
    print("| :--- | :--- | :--- | :--- |")

    for b in args.batch:
        batch_df = pd.concat([base_feat] * b, ignore_index=True)
        # Warmup
        for _ in range(10):
            _ = model.predict(batch_df)

        times_batch = []
        for _ in range(args.n):
            t0 = time.perf_counter()
            _ = model.predict(batch_df)
            t1 = time.perf_counter()
            times_batch.append((t1 - t0) * 1000)

        p50_b = float(np.percentile(times_batch, 50))
        p95_b = float(np.percentile(times_batch, 95))
        per_item = p50_b / b
        if per_item < 0.001:
            per_item_str = f"{per_item * 1_000_000:.1f} ns"
        elif per_item < 1.0:
            per_item_str = f"{per_item * 1000:.1f} µs"
        else:
            per_item_str = f"{per_item:.2f} ms"

        print(f"| {b} | {p50_b:.2f} ms | {p95_b:.2f} ms | {per_item_str} |")


if __name__ == "__main__":
    main()
