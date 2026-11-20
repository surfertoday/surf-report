#!/usr/bin/env python3
"""Build an NDBC inventory and detect variables with actual recent numeric readings."""
import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://www.ndbc.noaa.gov"
ACTIVE_XML = BASE + "/activestations.xml"
REALTIME_INDEX = BASE + "/data/realtime2/"
OUT = "site/data/stations.json"
WAVE_FIELDS = {"WVHT", "DPD", "APD", "MWD"}
WIND_FIELDS = {"WSPD", "WDIR", "GST"}
TARGET_FIELDS = WAVE_FIELDS | WIND_FIELDS
MISSING = {"MM", "99", "99.0", "999", "999.0", "9999", "9999.0"}

class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = set()
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href:
                self.hrefs.add(href)

def get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "SurferToday-SurfReport/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()

def inspect_feed(station_id):
    result = {"fields": set(), "header_fields": set(), "recent_rows_checked": 0}
    try:
        lines = get(f"{REALTIME_INDEX}{station_id}.txt").decode("utf-8", "replace").splitlines()
        header = None
        rows = []
        for raw in lines:
            line = raw.strip()
            if line.startswith("#YY"):
                header = line.lstrip("#").split()
            elif line and not line.startswith("#") and header:
                values = line.split()
                if len(values) >= len(header):
                    rows.append(values)
        if not header:
            return result
        result["header_fields"] = set(header) & TARGET_FIELDS
        # Check the most recent records in the feed (NDBC real-time files are chronological).
        recent = rows[-12:]
        result["recent_rows_checked"] = len(recent)
        indexes = {field: header.index(field) for field in TARGET_FIELDS if field in header}
        for field, index in indexes.items():
            for row in recent:
                value = row[index].strip()
                if value not in MISSING:
                    try:
                        float(value)
                        result["fields"].add(field)
                        break
                    except ValueError:
                        continue
    except Exception:
        pass
    return result

def main():
    root = ET.fromstring(get(ACTIVE_XML))
    parser = Links()
    parser.feed(get(REALTIME_INDEX).decode("utf-8", "replace"))
    files = parser.hrefs

    candidates = []
    for node in root.iter():
        if node.tag.lower().split("}")[-1] != "station":
            continue
        a = node.attrib
        sid = a.get("id", "").strip()
        try:
            lat, lon = float(a["lat"]), float(a["lon"])
        except (KeyError, ValueError):
            continue
        if sid and -90 <= lat <= 90 and -180 <= lon <= 180 and (sid + ".txt" in files or sid + ".spec" in files):
            candidates.append((sid, a, lat, lon))

    inspections = {}
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(inspect_feed, sid): sid for sid, a, lat, lon in candidates if sid + ".txt" in files}
        for future in as_completed(futures):
            inspections[futures[future]] = future.result()

    stations = []
    for sid, a, lat, lon in candidates:
        check = inspections.get(sid, {"fields": set(), "header_fields": set(), "recent_rows_checked": 0})
        fields = check["fields"]
        wave_fields = sorted(fields & WAVE_FIELDS)
        wind_fields = sorted(fields & WIND_FIELDS)
        name = (a.get("name") or "").strip()
        owner = (a.get("owner") or "").strip()
        if not name:
            name = owner if owner and owner.upper() not in {"NDBC", "NOAA"} else sid
        spec_available = sid + ".spec" in files
        stations.append({
            "id": sid, "name": name, "owner": owner,
            "latitude": lat, "longitude": lon,
            "has_wave_feed": bool(wave_fields) or spec_available,
            "has_significant_wave_height": "WVHT" in fields,
            "has_wave_period": bool(fields & {"DPD", "APD"}),
            "has_wave_direction": "MWD" in fields,
            "has_wind_data": bool(wind_fields),
            "has_wind_speed": "WSPD" in fields,
            "has_wind_direction": "WDIR" in fields,
            "has_wind_gust": "GST" in fields,
            "wave_variables": wave_fields,
            "wind_variables": wind_fields,
            "has_spectral_wave_feed": spec_available,
            "has_standard_feed": sid + ".txt" in files,
            "recent_rows_checked": check["recent_rows_checked"],
            "source": "NOAA NDBC",
            "station_url": BASE + "/station_page.php?station=" + sid,
            "observations_url": REALTIME_INDEX + sid + ".txt"
        })

    stations.sort(key=lambda s: (s["name"].lower(), s["id"]))
    result = {
        "source": "NOAA National Data Buoy Center (NDBC)",
        "source_metadata": ACTIVE_XML,
        "source_realtime_directory": REALTIME_INDEX,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": "Active-station XML provides station coordinates. Variable availability is based on numeric, non-missing readings in the last 12 records of each current real-time .txt feed. Spectral .spec availability is recorded separately. This indicates recent observed values, not guaranteed continuous sensor availability.",
        "count": len(stations),
        "stations": stations
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Wrote {len(stations)} stations to {OUT}")
    for field, label in [
        ("has_significant_wave_height", "WVHT"),
        ("has_wave_period", "wave period"),
        ("has_wave_direction", "MWD"),
        ("has_wind_speed", "WSPD"),
        ("has_wind_direction", "WDIR"),
        ("has_wind_gust", "GST"),
    ]:
        print(f"Stations with recent {label} readings: {sum(s[field] for s in stations)}")

if __name__ == "__main__":
    main()
