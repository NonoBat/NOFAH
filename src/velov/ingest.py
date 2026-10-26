from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(message)s")
logger = logging.getLogger("velov.ingest")

FEEDS = {
    "station_status": "https://download.data.grandlyon.com/files/rdata/jcd_jcdecaux.jcdvelov/station_status.json",
    "station_information": "https://download.data.grandlyon.com/files/rdata/jcd_jcdecaux.jcdvelov/station_information.json",
}

DEFAULT_BRONZE_DIR = Path("data/bronze")

# On récupère le JSON brut.
def fetch_json(url: str, timeout: int = 10) -> dict:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()

# (référence au pptx S3 diapo 15.)
def ingest(url: str, bronze: Path, feed: str) -> tuple[Path, bool]:
    payload = fetch_json(url) # timeout de 10s
    key = payload["last_updated"] # horodatage de la source
    ts = datetime.fromtimestamp(key, tz=timezone.utc)
    target = bronze / feed / f"dt={ts:%Y-%m-%d}" / f"{key}.json"
    if target.exists():
        return target, False  # déjà ingéré
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload))
    tmp.replace(target)  # écriture atomique
    return target, True

def main() -> None:
    bronze_dir = Path(os.getenv("BRONZE_DIR", DEFAULT_BRONZE_DIR))

    written = 0
    already_present = 0

    for feed, url in FEEDS.items():
        _, created = ingest(url, bronze_dir, feed)
        if created:
            written += 1
        else:
            already_present += 1

    logger.info("bronze : %d fichiers écrits, %d déjà présents", written, already_present)


if __name__ == "__main__":
    main()
