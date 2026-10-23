"""Download the NSW DCCEEW without-development archive for gauge 410008.

The source archive is saved byte-for-byte as published. It contains modelled
daily flows, not observations, and is licensed CC BY-NC-ND 4.0; keep it
separate from measured calibration data and consult the licence before reuse.
"""

from __future__ import annotations

import json
import hashlib
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "data" / "input" / "routing"
URL = (
    "https://datasets.seed.nsw.gov.au/dataset/2bb923b4-78f0-462a-ae1e-"
    "f007ebbf3355/resource/40fdec54-f271-4217-b68f-790ed4a935b0/download/"
    "410008_murrumbidgeeburrinjuck.zip"
)
ARCHIVE = DEST / "410008_murrumbidgee_burrinjuck_without_development.zip"
METADATA = DEST / "410008_murrumbidgee_burrinjuck_without_development_metadata.json"


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(URL, headers={"User-Agent": "mdb-model public hydrology data downloader"})
    with urllib.request.urlopen(request, timeout=180) as response:
        body = response.read()
    if not body.startswith(b"PK\x03\x04"):
        raise RuntimeError(f"Expected a ZIP archive from {URL}; received {len(body)} bytes")
    ARCHIVE.write_bytes(body)

    with zipfile.ZipFile(ARCHIVE) as zf:
        bad_member = zf.testzip()
        if bad_member:
            raise RuntimeError(f"Corrupt ZIP member: {bad_member}")
        members = [{"path": i.filename, "bytes": i.file_size} for i in zf.infolist() if not i.is_dir()]

    metadata = {
        "source": "NSW Department of Climate Change, Energy, the Environment and Water, via SEED/Data.NSW",
        "dataset": "Water Modelling-Modelled Data-Without Development-Murrumbidgee",
        "gauge_resource": "410008_Murrumbidgee@Burrinjuck",
        "source_url": URL,
        "resource_page": "https://www.data.nsw.gov.au/data/dataset/water-modelling-modelled-data-without-development-murrumbidgee-valley/resource/fc884215-55d6-4f3e-8363-8f8b5e997539",
        "last_updated": "2026-10-04",
        "temporal_coverage_dataset": "1895-01-01 through 2025-07-31",
        "units": "daily flow rate, ML/day (as described by the dataset record)",
        "license": "Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International",
        "archive_sha256": hashlib.sha256(body).hexdigest(),
        "archive_bytes": len(body),
        "archive_members": members,
        "notes": [
            "This is an agency modelled without-development scenario, not observed river discharge.",
            "The scenario removes as much water development and infrastructure as possible; it is not a pristine pre-human flow reconstruction.",
            "The archive is saved unchanged. Keep it distinct from measured calibration data and check the CC BY-NC-ND licence before adapting or redistributing it.",
        ],
    }
    METADATA.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved unchanged archive ({len(body):,} bytes) to {ARCHIVE}")
    print(f"Archive members: {[m['path'] for m in members]}")


if __name__ == "__main__":
    main()
