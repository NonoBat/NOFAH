"""Benchmark de quantification DistilBERT : float32 vs int8 (TP5a, S5).

Mesure le triplet classique de l'optimisation :
1. Taille du state_dict sérialisé (Mo)
2. Latence d'une phrase de 128 tokens sur un seul thread (p50 et p95 en ms)
3. Précision sur les 872 phrases de validation SST-2 et accord avec float32.

Trois variantes mesurées :
- float32 (référence non quantifiée)
- int8 torch.ao (quantize_dynamic, historique / déprécié)
- int8 torchao (Int8DynamicActivationInt8WeightConfig)

Usage :
    python scripts/bench_quantization.py [--n-latence 100]
"""

from __future__ import annotations

import argparse
import copy
import io
import time
import warnings

import numpy as np
import torch
from datasets import load_dataset
from torchao.quantization import Int8DynamicActivationInt8WeightConfig, quantize_
from transformers import AutoModelForSequenceClassification, AutoTokenizer

MODEL_ID = "distilbert-base-uncased-finetuned-sst-2-english"


def get_model_size_mb(model: torch.nn.Module) -> float:
    """Calcule la taille du state_dict sérialisé en Mo."""
    buffer = io.BytesIO()
    torch.save(model.state_dict(), buffer)
    return buffer.tell() / (1024 * 1024)


def measure_latency_128_tokens(
    model: torch.nn.Module, tokenizer: AutoTokenizer, n_iterations: int = 100, warmup: int = 15
) -> tuple[float, float]:
    """Mesure la latence d'une phrase de 128 tokens sur 1 thread CPU."""
    torch.set_num_threads(1)
    text = "The acting in this film is remarkably compelling and deeply moving. " * 15
    inputs = tokenizer(
        text,
        max_length=128,
        padding="max_length",
        truncation=True,
        return_tensors="pt",
    )

    # Échauffement
    for _ in range(warmup):
        with torch.inference_mode():
            _ = model(**inputs)

    # Mesure
    latencies = []
    for _ in range(n_iterations):
        t0 = time.perf_counter()
        with torch.inference_mode():
            _ = model(**inputs)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000)

    p50 = float(np.percentile(latencies, 50))
    p95 = float(np.percentile(latencies, 95))
    return p50, p95


def evaluate_sst2(
    model: torch.nn.Module, tokenizer: AutoTokenizer, dataset, batch_size: int = 32
) -> tuple[float, np.ndarray, np.ndarray]:
    """Évalue la précision sur le jeu de validation SST-2 et renvoie les prédictions et logits."""
    torch.set_num_threads(1)
    all_preds = []
    all_logits = []
    all_labels = []

    sentences = [item["sentence"] for item in dataset]
    labels = [item["label"] for item in dataset]

    for i in range(0, len(sentences), batch_size):
        batch_sentences = sentences[i : i + batch_size]
        batch_labels = labels[i : i + batch_size]

        inputs = tokenizer(batch_sentences, padding=True, truncation=True, return_tensors="pt")
        with torch.inference_mode():
            outputs = model(**inputs)
            logits = outputs.logits

        preds = torch.argmax(logits, dim=-1).cpu().numpy()
        all_preds.extend(preds)
        all_logits.append(logits.cpu().numpy())
        all_labels.extend(batch_labels)

    all_preds = np.array(all_preds)
    all_logits = np.concatenate(all_logits, axis=0)
    all_labels = np.array(all_labels)

    accuracy = 100.0 * np.mean(all_preds == all_labels)
    return accuracy, all_preds, all_logits


def main():
    parser = argparse.ArgumentParser(description="Benchmark de quantification TP5a")
    parser.add_argument("--n-latence", type=int, default=100, help="Nombre de mesures de latence (défaut: 100)")
    args = parser.parse_args()

    print(f"Chargement du tokenizer et du modèle {MODEL_ID} en float32...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    model_fp32 = AutoModelForSequenceClassification.from_pretrained(MODEL_ID)
    model_fp32.eval()

    print("Quantification int8 avec torch.ao (quantize_dynamic)...")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model_torch_ao = torch.ao.quantization.quantize_dynamic(
            copy.deepcopy(model_fp32), {torch.nn.Linear}, dtype=torch.qint8
        )
    model_torch_ao.eval()

    print("Quantification int8 avec torchao (Int8DynamicActivationInt8WeightConfig)...")
    model_torchao = copy.deepcopy(model_fp32)
    quantize_(model_torchao, Int8DynamicActivationInt8WeightConfig())
    model_torchao.eval()

    print("Chargement des 872 phrases de validation SST-2...")
    dataset = load_dataset("nyu-mll/glue", "sst2", split="validation")
    print(f"Dataset chargé : {len(dataset)} phrases.")

    variants = [
        ("float32", model_fp32),
        ("int8 torch.ao (quantize_dynamic)", model_torch_ao),
        ("int8 torchao", model_torchao),
    ]

    results = []
    fp32_preds = None
    fp32_logits = None

    for name, model in variants:
        print(f"\n--- Mesure de la variante : {name} ---")
        size_mb = get_model_size_mb(model)
        print(f"  Taille du state_dict : {size_mb:.1f} Mo")

        print("  Mesure de la latence (phrase 128 tokens, 1 thread)...")
        p50, p95 = measure_latency_128_tokens(model, tokenizer, n_iterations=args.n_latence)
        print(f"  Latence : p50 = {p50:.1f} ms, p95 = {p95:.1f} ms")

        print("  Évaluation sur SST-2 (872 phrases)...")
        acc, preds, logits = evaluate_sst2(model, tokenizer, dataset)
        print(f"  Précision SST-2 : {acc:.2f} %")

        if name == "float32":
            fp32_preds = preds
            fp32_logits = logits
            accord = 100.0
            ecart_max_logits = 0.0
        else:
            accord = 100.0 * np.mean(preds == fp32_preds)
            ecart_max_logits = float(np.max(np.abs(logits - fp32_logits)))
            print(f"  Accord avec float32 : {accord:.2f} %")
            print(f"  Écart max logits : {ecart_max_logits:.4f}")

        results.append(
            {
                "variante": name,
                "taille_mo": size_mb,
                "p50_ms": p50,
                "p95_ms": p95,
                "precision": acc,
                "accord": accord,
                "ecart_max_logits": ecart_max_logits,
            }
        )

    print("\n" + "=" * 90)
    print("TABLEAU RÉCAPITULATIF DU TRIPLET (TP5a)")
    print("=" * 90)
    head = ["Variante", "Taille (Mo)", "p50 (ms)", "p95 (ms)", "Précision SST-2", "Accord float32", "Écart max logits"]
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    for r in results:
        row = [
            r["variante"],
            f"{r['taille_mo']:.1f} Mo",
            f"{r['p50_ms']:.1f} ms",
            f"{r['p95_ms']:.1f} ms",
            f"{r['precision']:.2f} %",
            f"{r['accord']:.2f} %",
            f"{r['ecart_max_logits']:.4f}",
        ]
        print("| " + " | ".join(row) + " |")


if __name__ == "__main__":
    main()
