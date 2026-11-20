#!/usr/bin/env python3
"""Build a NOAA NDBC station inventory using active metadata and live feed headers."""
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

class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href:
                self.hrefs.append(href)

def get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "SurferToday-SurfReport/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()

def feed_fields(station_id):
    url = f"{REALTIME_INDEX}{station_id}.txt"
    try:
        content = get(url).decode("utf-8", "replace")
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("#YY"):
                return set(line.lstrip("#").split())
    except Exception:
        pass
    return set()

def main():
    root = ET.fromstring(get(ACTIVE_XML))
    parser = Links()
    parser.feed(get(REALTIME_INDEX).decode("utf-8", "replace"))
    files = set(parser.hrefs)

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

    headers = {}
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(feed_fields, sid): sid for sid, a, lat, lon in candidates if sid + ".txt" in files}
        for future in as_completed(futures):
            headers[futures[future]] = future.result()

    stations = []
    for sid, a, lat, lon in candidates:
        fields = headers.get(sid, set())
        wave_fields = sorted(fields & WAVE_FIELDS)
        wind_fields = sorted(fields & WIND_FIELDS)
        name = (a.get("name") or "").strip()
        owner = (a.get("owner") or "").strip()
        if not name:
            name = owner if owner and owner.upper() not in {"NDBC", "NOAA"} else sid
        spec_available = sid + ".spec" in files
        stations.append({
            "id": sid,
            "name": name,
            "owner": owner,
            "latitude": lat,
            "longitude": lon,
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
        "method": "Active-station XML provides station coordinates. Each available real-time .txt feed is inspected for its #YY header to identify actual reported wave and wind variables. Spectral .spec availability is recorded separately and is not treated as proof of a WVHT field.",
        "count": len(stations),
        "stations": stations
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Wrote {len(stations)} stations to {OUT}")
    print(f"Stations with WVHT: {sum(s['has_significant_wave_height'] for s in stations)}")
    print(f"Stations with wind speed: {sum(s['has_wind_speed'] for s in stations)}")
    print(f"Stations with wind direction: {sum(s['has_wind_direction'] for s in stations)}")

if __name__ == "__main__":
    main()
