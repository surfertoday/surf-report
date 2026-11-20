#!/usr/bin/env python3
"""Fetch the latest available value per variable from NOAA NDBC real-time feeds."""
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
        with urllib.request.urlopen(req, timeout=25) as response:
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

        indexes = {field: header.index(field) for field in FIELDS if field in header}
        values, value_times, value_units = {}, {}, {}
        # Work backwards so each variable gets its own latest valid reading.
        for row in reversed(rows[-48:]):
            stamp = {}
            for key in ("YY", "MM", "DD", "hh", "mm"):
                if key in header:
                    stamp[key] = row[header.index(key)]
            for field, index in indexes.items():
                if field in values:
                    continue
                raw = row[index].strip()
                if raw in MISSING:
                    continue
                try:
                    values[field] = float(raw)
                    value_times[field] = stamp
                    if units and index < len(units):
                        value_units[field] = units[index]
                except ValueError:
                    continue
            if len(values) == len(indexes):
                break
        if not values:
            return sid, None
        # Overall timestamp is the newest timestamp among the values included.
        def stamp_key(stamp):
            try:
                return tuple(int(stamp.get(k, 0)) for k in ("YY","MM","DD","hh","mm"))
            except Exception:
                return (0,0,0,0,0)
        latest_stamp = max(value_times.values(), key=stamp_key)
        return sid, {
            "station_id": sid,
            "observed_at": latest_stamp,
            "value_times": value_times,
            "values": values,
            "units": value_units,
            "fields": sorted(values.keys()),
            "source_url": url
        }
    except Exception as exc:
        return sid, {"error": str(exc)[:180], "station_id": sid}

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
    print(f"Stations with current WVHT: {sum('WVHT' in o.get('values', {}) for o in results.values())}")
    print(f"Stations with current wind speed: {sum('WSPD' in o.get('values', {}) for o in results.values())}")

if __name__ == "__main__":
    main()
