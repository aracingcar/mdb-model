"""Download the WaterNSW daily discharge-volume series at Burrinjuck DS.

Station 410008 is immediately below Burrinjuck Dam. The legacy public
WaterNSW Hydstra endpoint exposes a daily discharge-volume variable (151.00)
with a quality code per day. This is kept as a separate comparison series:
the quality codes are preserved and the daily volume is not presented as a
quality-screened discharge observation.

Run from the repository root with ``python 3b_calibration/download_waternsw_burrinjuck_release.py``.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "data" / "input" / "routing"
URL = "https://realtimedata.waternsw.com.au/cgi/webservice.exe"
STATION = "410008"
PARAM = "151.00"  # Discharge Volume, daily total, ML/day equivalent
START = "20120101000000"
END = "20230101000000"
USER_AGENT = "mdb-model public hydrology data downloader"


def fetch():
    query = {
        "function": "get_ts_traces",
        "version": 2,
        "params": {
            "site_list": STATION,
            "datasource": "A",
            "varfrom": PARAM,
            "varto": PARAM,
            "start_time": START,
            "end_time": END,
            "data_type": "tot",
            "interval": "day",
            "multiplier": "1",
        },
    }
    url = URL + "?" + urllib.parse.quote(json.dumps(query, separators=(",", ":")), safe="") + "&ver=2"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.load(response)
    if payload.get("error_num"):
        raise RuntimeError(f"WaterNSW API error {payload['error_num']}: {payload.get('error_msg')}")
    traces = payload.get("return", {}).get("traces", [])
    if len(traces) != 1 or traces[0].get("error_num"):
        raise RuntimeError(f"Unexpected WaterNSW response: {traces[:1]}")
    return traces[0]


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    trace = fetch()
    rows = trace.get("trace", [])
    if not rows:
        raise RuntimeError("WaterNSW returned no observations")

    import csv

    output_csv = DEST / "murrumbidgee_410008_waternsw_daily_discharge.csv"
    quality_counts = Counter()
    dates = []
    value_dates = []
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "source_value_ml", "discharge_volume_ml_day", "mean_flow_m3s", "quality_code", "quality_description"])
        for row in sorted(rows, key=lambda x: x["t"]):
            stamp = str(row["t"])
            date = datetime.strptime(stamp[:8], "%Y%m%d").date().isoformat()
            value = float(row["v"])
            code = str(row.get("q", ""))
            description = trace.get("quality_codes", {}).get(code, "")
            # 1 ML/day = 1000 m3 / 86400 s = 1/86.4 m3/s.
            # WaterNSW returns zero placeholders for unavailable records; retain
            # the raw value and quality code but expose those derived fields blank.
            if code in {"201", "255"}:
                volume, flow = "", ""
            else:
                volume, flow = f"{value:.3f}", f"{value / 86.4:.6f}"
                value_dates.append(date)
            writer.writerow([date, f"{value:.3f}", volume, flow, code, description])
            quality_counts[code] += 1
            dates.append(date)

    metadata = {
        "source": "WaterNSW public legacy Hydstra web service",
        "source_url": "https://realtimedata.waternsw.com.au/cgi/webservice.exe",
        "station": STATION,
        "station_name": trace.get("site_details", {}).get("name"),
        "variable": PARAM,
        "variable_name": trace.get("varto_details", {}).get("name", "Discharge Volume"),
        "source_units": "ML per daily record (daily discharge volume)",
        "derived_units": "mean_flow_m3s is daily volume in ML divided by 86.4",
        "period_returned": {"start": min(dates), "end": max(dates)},
        "period_with_reported_values": {"start": min(value_dates), "end": max(value_dates)},
        "rows": len(rows),
        "rows_with_reported_values": len(rows) - quality_counts.get("201", 0) - quality_counts.get("255", 0),
        "quality_code_counts": dict(sorted(quality_counts.items())),
        "quality_code_definitions": trace.get("quality_codes", {}),
        "notes": [
            "Original daily discharge volume and WaterNSW quality code are both preserved.",
            "This is a comparison series and was not quality-filtered or gap-filled here.",
            "Some source quality codes describe large rating uncertainty; consult quality_code before calibration use.",
            "Codes 201 and 255 mean data unavailable; their returned zero placeholders are masked as blank derived values.",
            "Burrinjuck DS is a regulated release-dominated site, not a natural rainfall-runoff gauge.",
        ],
    }
    (DEST / "murrumbidgee_410008_waternsw_daily_discharge_metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Saved {len(rows):,} rows, {min(dates)} to {max(dates)}: {output_csv}")
    print(f"Quality codes: {dict(quality_counts)}")


if __name__ == "__main__":
    main()
