#!/usr/bin/env python3
"""Fetch latest NDBC real-time observations for stations in stations.json."""
import json
import urllib.request
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://www.ndbc.noaa.gov/data/realtime2/"
STATIONS = "site/data/stations.json"
OUT = "site/data/observations.json"
FIELDS = ["WVHT", "DPD", "APD", "MWD", "WSPD", "WDIR", "GST", "WTMP", "ATMP", "PRES"]
MISSING = {"MM", "99", "99.0", "999", "999.0", "9999", "9999.0"}

def fetch_station(station):
    sid = station["id"]
    url = BASE + sid + ".txt"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SurferToday-SurfReport/1.0"})
        with urllib.request.urlopen(req, timeout=20) as response:
            lines = response.read().decode("utf-8", "replace").splitlines()
        header = None
        units = None
        rows = []
        for line in lines:
            line = line.strip()
            if line.startswith("#YY"):
                header = line.lstrip("#").split()
            elif line.startswith("#") and header and units is None:
                units = line.lstrip("#").split()
            elif line and not line.startswith("#") and header:
                parts = line.split()
                if len(parts) >= len(header):
                    rows.append(parts)
        if not header or not rows:
            return sid, None
        # Search backwards for the latest row containing at least one usable observation.
        for row in reversed(rows[-24:]):
            values = {}
            for field in FIELDS:
                if field not in header:
                    continue
                value = row[header.index(field)]
                if value in MISSING:
                    continue
                try:
                    values[field] = float(value)
                except ValueError:
                    continue
            if values:
                stamp = {}
                for key in ("YY", "MM", "DD", "hh", "mm"):
                    if key in header:
                        stamp[key] = row[header.index(key)]
                return sid, {
                    "station_id": sid,
                    "observed_at": stamp,
                    "values": values,
                    "units": {f: units[header.index(f)] for f in values if units and f in header and header.index(f) < len(units)},
                    "fields": sorted(values.keys()),
                    "source_url": url
                }
    except Exception as exc:
        return sid, {"error": str(exc)[:180], "station_id": sid}
    return sid, None

def main():
    with open(STATIONS, encoding="utf-8") as f:
        station_data = json.load(f)
    results = {}
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(fetch_station, s) for s in station_data["stations"] if s.get("has_standard_feed")]
        for future in as_completed(futures):
            sid, observation = future.result()
            if observation:
                results[sid] = observation
    output = {
        "source": "NOAA National Data Buoy Center (NDBC)",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "station_count": len(station_data["stations"]),
        "observations_returned": len(results),
        "observations": results
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Saved observations for {len(results)} stations")

if __name__ == "__main__":
    main()
