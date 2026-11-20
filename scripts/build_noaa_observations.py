#!/usr/bin/env python3
"""Build fresh NOAA observations from NDBC's consolidated latest-observations feed."""
import json
import urllib.request
from datetime import datetime, timezone

SOURCE_URL = "https://www.ndbc.noaa.gov/data/latest_obs/latest_obs.txt"
STATIONS = "site/data/stations.json"
OUT = "site/data/observations.json"
FIELDS = ["WVHT", "DPD", "APD", "MWD", "WSPD", "WDIR", "GST", "WTMP", "ATMP", "PRES"]
MISSING = {"MM", "99", "99.0", "999", "999.0", "9999", "9999.0"}
UNITS = {
    "WVHT": "m", "DPD": "sec", "APD": "sec", "MWD": "degT",
    "WSPD": "m/s", "WDIR": "degT", "GST": "m/s",
    "WTMP": "degC", "ATMP": "degC", "PRES": "hPa"
}


def main():
    with open(STATIONS, encoding="utf-8") as f:
        station_data = json.load(f)
    known_ids = {str(s["id"]) for s in station_data["stations"]}

    request = urllib.request.Request(
        SOURCE_URL,
        headers={"User-Agent": "SurferToday-SurfReport/1.0"}
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        lines = response.read().decode("utf-8", "replace").splitlines()

    header = None
    results = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            candidate = line.lstrip("#").split()
            if "STN" in candidate and "YYYY" in candidate:
                header = candidate
            continue
        if not header:
            continue

        parts = line.split()
        if len(parts) < len(header):
            continue
        row = dict(zip(header, parts))
        sid = row.get("STN", "").strip()
        if sid not in known_ids:
            continue

        stamp = {
            "YY": row.get("YYYY", ""),
            "MM": row.get("MM", ""),
            "DD": row.get("DD", ""),
            "hh": row.get("hh", ""),
            "mm": row.get("mm", "")
        }
        values = {}
        value_units = {}
        for field in FIELDS:
            raw = row.get(field, "").strip()
            if not raw or raw in MISSING:
                continue
            try:
                values[field] = float(raw)
                value_units[field] = UNITS[field]
            except ValueError:
                continue
        if not values:
            continue

        results[sid] = {
            "station_id": sid,
            "observed_at": stamp,
            "value_times": {field: stamp for field in values},
            "values": values,
            "units": value_units,
            "fields": sorted(values.keys()),
            "source_url": SOURCE_URL
        }

    output = {
        "source": "NOAA National Data Buoy Center (NDBC) latest observations",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "station_count": len(station_data["stations"]),
        "observations_returned": len(results),
        "freshness_window": "NDBC latest observations feed: observations less than two hours old",
        "observations": results
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write("\\n")

    print(f"Saved fresh observations for {len(results)} stations")
    print(f"Stations with WVHT: {sum('WVHT' in o['values'] for o in results.values())}")
    print(f"Stations with WSPD: {sum('WSPD' in o['values'] for o in results.values())}")


if __name__ == "__main__":
    main()
