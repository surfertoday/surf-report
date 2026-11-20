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


def parse_stamp(row):
    year = int(row.get("YY", row.get("YYYY", "0")))
    if year < 100:
        year += 2000
    return datetime(
        year, int(row["MM"]), int(row["DD"]),
        int(row["hh"]), int(row["mm"]), tzinfo=timezone.utc
    )


def fetch_station_supplement(station_id):
    """Fetch the individual NDBC realtime2 file for a priority station."""
    url = f"https://www.ndbc.noaa.gov/data/realtime2/{station_id}.txt"
    request = urllib.request.Request(
        url, headers={"User-Agent": "SurferToday-SurfReport/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            lines = response.read().decode("utf-8", "replace").splitlines()
    except Exception as exc:
        print(f"Supplemental feed unavailable for {station_id}: {exc}")
        return None

    header = None
    newest = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            candidate = line.lstrip("#").split()
            if "YY" in candidate and "MM" in candidate and "hh" in candidate:
                header = candidate
            continue
        if not header:
            continue
        parts = line.split()
        if len(parts) < len(header):
            continue
        row = dict(zip(header, parts))
        try:
            stamp = parse_stamp(row)
        except (ValueError, TypeError, KeyError):
            continue
        values, value_units = {}, {}
        for field in FIELDS:
            raw = row.get(field, "").strip()
            if not raw or raw in MISSING:
                continue
            try:
                values[field] = float(raw)
                value_units[field] = UNITS[field]
            except ValueError:
                continue
        if values and (newest is None or stamp > newest["stamp"]):
            newest = {"stamp": stamp, "values": values, "units": value_units}

    if newest is None:
        return None
    stamp = newest["stamp"]
    stamp_obj = {
        "YY": f"{stamp.year:04d}", "MM": f"{stamp.month:02d}",
        "DD": f"{stamp.day:02d}", "hh": f"{stamp.hour:02d}",
        "mm": f"{stamp.minute:02d}"
    }
    return {
        "station_id": station_id, "observed_at": stamp_obj,
        "value_times": {field: stamp_obj for field in newest["values"]},
        "values": newest["values"], "units": newest["units"],
        "fields": sorted(newest["values"]),
        "source_url": url
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

    # The consolidated feed can lag the individual station file. Check this
    # priority station independently and keep whichever report is newer.
    for sid in ("46053",):
        supplemental = fetch_station_supplement(sid)
        if supplemental:
            current = results.get(sid)
            try:
                current_stamp = parse_stamp(current["observed_at"]) if current else None
                new_stamp = parse_stamp(supplemental["observed_at"])
            except (ValueError, TypeError, KeyError):
                current_stamp = None
                new_stamp = None
            if current is None:
                results[sid] = supplemental
            elif new_stamp and (current_stamp is None or new_stamp > current_stamp):
                # Merge by variable, not by whole station record. A newer
                # meteorological row may omit wave fields that remain valid
                # in the consolidated feed.
                merged = current
                merged_values = dict(current.get("values", {}))
                merged_units = dict(current.get("units", {}))
                merged_times = dict(current.get("value_times", {}))
                for field, value in supplemental.get("values", {}).items():
                    existing_time = merged_times.get(field)
                    try:
                        existing_stamp = parse_stamp(existing_time) if existing_time else None
                    except (ValueError, TypeError, KeyError):
                        existing_stamp = None
                    field_stamp = parse_stamp(supplemental["value_times"][field])
                    if existing_stamp is None or field_stamp > existing_stamp:
                        merged_values[field] = value
                        merged_units[field] = supplemental["units"][field]
                        merged_times[field] = supplemental["value_times"][field]

                latest_stamp = max(parse_stamp(t) for t in merged_times.values())
                merged["values"] = merged_values
                merged["units"] = merged_units
                merged["value_times"] = merged_times
                merged["fields"] = sorted(merged_values)
                merged["observed_at"] = {
                    "YY": f"{latest_stamp.year:04d}",
                    "MM": f"{latest_stamp.month:02d}",
                    "DD": f"{latest_stamp.day:02d}",
                    "hh": f"{latest_stamp.hour:02d}",
                    "mm": f"{latest_stamp.minute:02d}"
                }
                merged["source_url"] = "NOAA consolidated and individual station feeds"
                results[sid] = merged
                print(f"Merged newest individual-station values for {sid}: {supplemental['observed_at']}")

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
        f.write("\n")

    print(f"Saved fresh observations for {len(results)} stations")
    print(f"Stations with WVHT: {sum('WVHT' in o['values'] for o in results.values())}")
    print(f"Stations with WSPD: {sum('WSPD' in o['values'] for o in results.values())}")


if __name__ == "__main__":
    main()
