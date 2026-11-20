#!/usr/bin/env python3
"""One-off OSMC coverage audit; does not alter the live NOAA map data."""
import csv
import io
import json
import math
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

ERDDAP = "https://osmc.noaa.gov/erddap/tabledap/OSMC_flattened.csvp"
STATIONS = "site/data/stations.json"
OUT = "site/data/osmc_coverage_report.json"
WINDOW_HOURS = 48
MAX_AGE_HOURS = 24
FIELDS = ["platform_code", "platform_type", "time", "latitude", "longitude",
          "wvht", "windspd", "winddir", "sst", "atmp"]


def distance_km(lat1, lon1, lat2, lon2):
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def main():
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=WINDOW_HOURS)
    query = ",".join(FIELDS) + "&time>=" + start.strftime("%Y-%m-%dT%H:%M:%SZ")
    url = ERDDAP + "?" + urllib.parse.quote(query, safe=",&>:=Z-")
    req = urllib.request.Request(url, headers={"User-Agent": "SurferToday-OSMC-Coverage-Audit/1.0"})
    with urllib.request.urlopen(req, timeout=120) as response:
        raw = response.read().decode("utf-8", "replace")

    rows = csv.DictReader(io.StringIO(raw))
    latest = {}
    types = Counter()
    rows_seen = 0
    for row in rows:
        rows_seen += 1
        code = (row.get("platform_code") or "").strip()
        if not code:
            continue
        ptype = (row.get("platform_type") or "unknown").strip()
        types[ptype] += 1
        try:
            stamp = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
            lat, lon = float(row["latitude"]), float(row["longitude"])
        except (ValueError, TypeError, KeyError):
            continue
        rec = latest.setdefault(code, {
            "platform_code": code, "platform_type": ptype,
            "time": stamp.isoformat(), "latitude": lat, "longitude": lon,
            "values": {}
        })
        if stamp > datetime.fromisoformat(rec["time"]):
            rec.update({"time": stamp.isoformat(), "latitude": lat, "longitude": lon,
                        "platform_type": ptype})
        for field in ("wvht", "windspd", "winddir", "sst", "atmp"):
            raw_value = (row.get(field) or "").strip()
            try:
                value = float(raw_value)
                if math.isfinite(value):
                    rec["values"][field] = value
            except ValueError:
                pass

    with open(STATIONS, encoding="utf-8") as f:
        inventory = json.load(f)["stations"]
    inventory_ids = {str(s.get("id", "")).strip() for s in inventory}
    inventory_coords = []
    for s in inventory:
        try:
            inventory_coords.append((float(s["latitude"]), float(s["longitude"]), str(s["id"])))
        except (KeyError, TypeError, ValueError):
            continue

    cutoff = now - timedelta(hours=MAX_AGE_HOURS)
    recent = [r for r in latest.values()
              if datetime.fromisoformat(r["time"]) >= cutoff]
    buoy_like = [r for r in recent
                 if any(term in r["platform_type"].lower()
                        for term in ("buoy", "drifter", "mooring", "moored"))]

    def classify(records):
        wave = [r for r in records if "wvht" in r["values"]]
        wind = [r for r in records if "windspd" in r["values"] or "winddir" in r["values"]]
        return len(records), len(wave), len(wind)

    new_candidates = []
    for r in buoy_like:
        near = None
        for lat, lon, sid in inventory_coords:
            d = distance_km(r["latitude"], r["longitude"], lat, lon)
            if d <= 5:
                near = {"station_id": sid, "distance_km": round(d, 2)}
                break
        if r["platform_code"] not in inventory_ids and near is None:
            new_candidates.append(r)

    report = {
        "source": "NOAA OSMC flattened observations from GTS",
        "source_url": url,
        "generated_at_utc": now.isoformat(timespec="seconds"),
        "query_window_hours": WINDOW_HOURS,
        "freshness_cutoff_hours": MAX_AGE_HOURS,
        "rows_received": rows_seen,
        "unique_platforms_in_window": len(latest),
        "platform_types_row_counts": dict(types.most_common()),
        "recent_unique_platforms_under_24h": classify(recent)[0],
        "recent_platforms_with_wave_height": classify(recent)[1],
        "recent_platforms_with_wind": classify(recent)[2],
        "buoy_like_platforms_under_24h": classify(buoy_like)[0],
        "buoy_like_with_wave_height": classify(buoy_like)[1],
        "buoy_like_with_wind": classify(buoy_like)[2],
        "new_buoy_like_candidates_after_id_and_5km_match": len(new_candidates),
        "new_candidates": sorted(new_candidates, key=lambda r: r["platform_code"]),
        "notes": [
            "This is a coverage audit only; it does not modify the live map or NOAA observations.",
            "OSMC platform types are classified by labels containing buoy, drifter, mooring, or moored; review platform_types before accepting candidates.",
            "Wave availability means a numeric significant wave height (wvht). Wind availability means numeric wind speed or direction.",
            "Duplicate screening uses exact station ID plus a 5 km coordinate proximity check; candidates still require manual review."
        ]
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps({k: v for k, v in report.items() if k != "new_candidates"}, indent=2))


if __name__ == "__main__":
    main()
