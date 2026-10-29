from __future__ import annotations

import argparse
import logging
import os
from datetime import UTC, datetime

import mlflow
from mlflow.exceptions import RestException

logger = logging.getLogger("velov.promote")
MODEL_NAME = "velov-availability"


def decide(c: dict, champion: dict | None, min_gain: float = 0.02) -> tuple[bool, str]:
    if c["mae_model"] >= c["mae_baseline_persistence"]:
        return False, "ne bat pas la persistance"
    if champion is None:
        return True, "premier champion"
    target = champion["mae_model"] * (1.0 - min_gain)
    if c["mae_model"] <= target:
        return True, f"gain sur le champion (MAE {c['mae_model']:.3f} <= {target:.3f})"
    return False, f"gain insuffisant face au champion (MAE {c['mae_model']:.3f} > {target:.3f})"


def get_version_by_alias(client: mlflow.MlflowClient, model_name: str, alias: str):
    """Récupère une version par son alias, ou None si non trouvée."""
    try:
        return client.get_model_version_by_alias(model_name, alias)
    except RestException:
        return None


def promote(
    model_name: str = MODEL_NAME,
    min_gain: float = 0.02,
    apply: bool = False,
) -> bool:
    """Évalue le challenger face au champion et applique la promotion si demandée."""
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")
    client = mlflow.MlflowClient(tracking_uri=tracking_uri)

    challenger_mv = get_version_by_alias(client, model_name, "challenger")
    if challenger_mv is None:
        print(f"Aucun modèle avec l'alias @challenger trouvé dans '{model_name}'.")
        return False

    champion_mv = get_version_by_alias(client, model_name, "champion")

    challenger_run = client.get_run(challenger_mv.run_id)
    c_metrics = challenger_run.data.metrics

    champ_metrics = None
    if champion_mv is not None:
        champion_run = client.get_run(champion_mv.run_id)
        champ_metrics = champion_run.data.metrics

    print(f"--- Évaluation pour promotion : {model_name} ---")
    print(f"Challenger : version {challenger_mv.version} (run {challenger_mv.run_id[:8]})")
    print(f"  MAE modèle      : {c_metrics.get('mae_model')}")
    print(f"  MAE persistance : {c_metrics.get('mae_baseline_persistence')}")

    if champion_mv is not None and champ_metrics:
        print(f"Champion actuel : version {champion_mv.version} (run {champion_mv.run_id[:8]})")
        print(f"  MAE modèle      : {champ_metrics.get('mae_model')}")
        target = champ_metrics.get("mae_model", 0.0) * (1.0 - min_gain)
        print(f"  Cible à battre (-{min_gain * 100:.0f}%) : <= {target:.3f}")
    else:
        print("Champion actuel : aucun (premier déploiement)")

    should_promote, reason = decide(c_metrics, champ_metrics, min_gain=min_gain)

    print()
    if should_promote:
        print(f"DÉCISION : PROMOUVOIR ({reason})")
        if apply:
            # 1. L'ancien champion devient previous-champion
            if champion_mv is not None:
                client.set_registered_model_alias(model_name, "previous-champion", champion_mv.version)
                print(f"Alias @previous-champion -> version {champion_mv.version}")

            # 2. Le challenger devient le nouveau champion
            client.set_registered_model_alias(model_name, "champion", challenger_mv.version)
            now_iso = datetime.now(UTC).isoformat(timespec="seconds")
            client.set_model_version_tag(model_name, challenger_mv.version, "promotion", "promoted")
            client.set_model_version_tag(model_name, challenger_mv.version, "promoted_at", now_iso)
            print(f"Alias @champion -> version {challenger_mv.version}")
            print("Promotion appliquée avec succès dans le registre.")
        else:
            print("Mode simulation : aucune modification effectuée.")
            print("Pour appliquer la promotion : python -m velov.promote --apply")
    else:
        print(f"DÉCISION : REJETÉ ({reason})")
        print("Le champion actuel est conservé.")

    return should_promote


def main() -> None:
    parser = argparse.ArgumentParser(description="Promotion du modèle Vélo'v dans le registre MLflow.")
    parser.add_argument("--model", default=MODEL_NAME, help="Nom du modèle enregistré")
    parser.add_argument(
        "--min-gain", type=float, default=0.02, help="Gain minimal requis sur le champion (défaut 0.02)"
    )
    parser.add_argument("--apply", action="store_true", help="Appliquer la promotion dans le registre")
    args = parser.parse_args()

    promote(model_name=args.model, min_gain=args.min_gain, apply=args.apply)


if __name__ == "__main__":
    main()
