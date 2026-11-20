#!/usr/bin/env python3
"""Build a NOAA NDBC station inventory from official public metadata and real-time files."""
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser

BASE = "https://www.ndbc.noaa.gov"
ACTIVE_XML = BASE + "/activestations.xml"
REALTIME_INDEX = BASE + "/data/realtime2/"
OUT = "site/data/stations.json"

class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href:
                self.hrefs.append(href)

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "SurferToday-SurfReport/1.0"})
    with urllib.request.urlopen(req, timeout=45) as response:
        return response.read()

def main():
    root = ET.fromstring(get(ACTIVE_XML))
    parser = Links()
    parser.feed(get(REALTIME_INDEX).decode("utf-8", "replace"))
    files = set(parser.hrefs)

    stations = []
    for node in root.iter():
        if node.tag.lower().split("}")[-1] != "station":
            continue
        a = node.attrib
        sid = a.get("id", "").strip()
        try:
            lat, lon = float(a["lat"]), float(a["lon"])
        except (KeyError, ValueError):
            continue
        if not sid or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue

        txt = sid + ".txt"
        spec = sid + ".spec"
        if txt not in files and spec not in files:
            continue

        station = {
            "id": sid,
            "name": a.get("name", sid).strip(),
            "owner": a.get("owner", "").strip(),
            "latitude": lat,
            "longitude": lon,
            "has_meteorological_feed": a.get("met", "n").lower() == "y",
            "has_wave_feed": spec in files,
            "has_standard_feed": txt in files,
            "source": "NOAA NDBC",
            "station_url": BASE + "/station_page.php?station=" + sid,
            "observations_url": BASE + "/data/realtime2/" + txt
        }
        stations.append(station)

    stations.sort(key=lambda s: (s["name"].lower(), s["id"]))
    result = {
        "source": "NOAA National Data Buoy Center (NDBC)",
        "source_metadata": ACTIVE_XML,
        "source_realtime_directory": REALTIME_INDEX,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": "Active-station XML for station identity and coordinates; current NDBC real-time directory for available .txt and .spec feeds. Meteorological feed availability does not guarantee every wind variable is measured at every station.",
        "count": len(stations),
        "stations": stations
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Wrote {len(stations)} stations to {OUT}")

if __name__ == "__main__":
    main()
