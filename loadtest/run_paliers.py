# ruff: noqa: S310, S603, S607
from __future__ import annotations

import os
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


def main() -> int:
    host = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    prefix = sys.argv[2] if len(sys.argv) > 2 else "w1"

    paliers = [int(u) for u in os.getenv("PALIERS", "10 25 50 100 150").split()]
    duree = os.getenv("DUREE", "2m")
    warmup = os.getenv("WARMUP", "1m")

    here = Path(__file__).resolve().parent
    out = Path("results") / prefix
    out.mkdir(parents=True, exist_ok=True)

    print(f"Vérification de la disponibilité de l'API sur {host}/ready...")
    try:
        with urllib.request.urlopen(f"{host}/ready", timeout=5) as resp:
            model_info = resp.read().decode("utf-8")
    except Exception as e:
        print(f"Erreur : L'API ne répond pas sur {host}/ready : {e}", file=sys.stderr)
        return 1

    # Informations de protocole
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        commit = "inconnu"

    try:
        import locust

        locust_ver = f"locust {locust.__version__}"
    except Exception:
        locust_ver = "inconnu"

    protocole_file = out / "protocole.txt"
    with protocole_file.open("w", encoding="utf-8") as f:
        f.write(f"date_utc={datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}\n")
        f.write(f"host={host}\n")
        f.write(f"paliers={' '.join(str(u) for u in paliers)} duree={duree} warmup={warmup}\n")
        f.write(f"commit={commit}\n")
        f.write(f"poste_coeurs={os.cpu_count()}\n")
        f.write(f"locust={locust_ver}\n")
        f.write(f"model={model_info}\n")

    print(f"Échauffement ({warmup}, non compté)...")
    cmd_warmup = [
        sys.executable,
        "-m",
        "locust",
        "-f",
        str(here / "locustfile.py"),
        "--host",
        host,
        "--headless",
        "-u",
        "10",
        "-r",
        "10",
        "-t",
        warmup,
        "--only-summary",
    ]
    subprocess.run(cmd_warmup, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for u in paliers:
        r = u if u < 20 else max(1, u // 5)
        print(f"Palier {u} usagers (montée: {r} usagers/s, durée: {duree})...")
        csv_prefix = out / f"u{u}"
        log_file = out / f"u{u}.log"

        cmd = [
            sys.executable,
            "-m",
            "locust",
            "-f",
            str(here / "locustfile.py"),
            "--host",
            host,
            "--headless",
            "-u",
            str(u),
            "-r",
            str(r),
            "-t",
            duree,
            "--csv",
            str(csv_prefix),
            "--only-summary",
        ]
        with log_file.open("w", encoding="utf-8") as lf:
            subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT)

    print(f"\nRésultats enregistrés dans {out}/")
    print("\nGénération du résumé :")
    subprocess.run([sys.executable, str(here / "summary.py"), str(out), "--markdown"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
