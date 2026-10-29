import joblib
import pytest

from velov.data import simulate
from velov.train import MODEL_FILENAME, sha256_of, train


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("models")
    data_dir = tmp_path_factory.mktemp("data")
    data_file = data_dir / "velov_simulated.csv"

    # Données simulées : 30 jours, 5 stations
    df = simulate(days=30, n_stations=5, seed=42)
    df.to_csv(data_file, index=False)

    metadata = train(data_file, out_dir, test_days=7, seed=42)
    pipeline = joblib.load(out_dir / MODEL_FILENAME)
    return pipeline, metadata


def test_model_beats_persistence_baseline(trained):
    """Le modèle doit battre la baseline de persistance sur les données de test."""
    _, metadata = trained
    m = metadata["metrics"]
    assert m["mae_model"] < m["mae_baseline_persistence"], m


def test_reproducibility_same_seed(tmp_path):
    """Avec les mêmes données et la même seed, l'artefact produit doit avoir le même SHA-256."""
    data_file = tmp_path / "data.csv"
    df = simulate(days=15, n_stations=3, seed=42)
    df.to_csv(data_file, index=False)

    out1 = tmp_path / "run1"
    out2 = tmp_path / "run2"

    train(data_file, out1, test_days=3, seed=42)
    train(data_file, out2, test_days=3, seed=42)

    hash1 = sha256_of(out1 / MODEL_FILENAME)
    hash2 = sha256_of(out2 / MODEL_FILENAME)
    assert hash1 == hash2

