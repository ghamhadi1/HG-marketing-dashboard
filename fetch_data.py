"""Pull raw records from the GoHighLevel sandbox (read-only) into data/raw/.

Reads credentials from .env so the key never lives in code that gets published.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
RAW = ROOT.parent / "data" / "raw"   # outside this folder: raw records are never published
BASE = "https://services.leadconnectorhq.com"
PIPELINE_NAME = "Sales Pipeline"


def load_env():
    # Local runs: the .env sits one folder ABOVE this one, so it can never be uploaded with the site.
    # Hosted runs (GitHub Actions): no file, the values arrive as environment secrets.
    env_file = ROOT.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    for name in ("GHL_API_KEY", "GHL_LOCATION_ID"):
        value = os.environ.get(name, "")
        if not value or value.startswith("PASTE_"):
            sys.exit(f"{name} is not set. Open the .env file in the 'Project 1' folder, paste the value "
                     f"after '{name}=' and run this again.")


def call(method, path, params=None, body=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + os.environ["GHL_API_KEY"],
        "Version": "2021-07-28",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "HG-dashboard/1.0",
    })
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 4:
                time.sleep(2 * (attempt + 1))
                continue
            hint = " Check the key and location ID in .env." if e.code in (401, 403) else ""
            sys.exit(f"{method} {path} failed: {e.code} {e.read().decode('utf-8', 'replace')[:500]}{hint}")
        except urllib.error.URLError as e:
            sys.exit(f"Could not reach GoHighLevel ({e.reason}). Check the internet connection and run this again.")


def fetch_pipelines(location_id):
    return call("GET", "/opportunities/pipelines", {"locationId": location_id})["pipelines"]


def fetch_opportunities(location_id, pipeline_id):
    out, page = [], 1
    while True:
        res = call("GET", "/opportunities/search", {
            "location_id": location_id, "pipeline_id": pipeline_id, "limit": 100, "page": page,
        })
        batch = res.get("opportunities", [])
        out.extend(batch)
        if len(batch) < 100:
            return out
        page += 1


def fetch_contacts(location_id):
    out, search_after = [], None
    while True:
        body = {"locationId": location_id, "pageLimit": 100}
        if search_after:
            body["searchAfter"] = search_after
        else:
            body["page"] = 1
        res = call("POST", "/contacts/search", body=body)
        batch = res.get("contacts", [])
        out.extend(batch)
        if len(batch) < 100:
            return out
        search_after = batch[-1].get("searchAfter")
        if not search_after:
            return out


def main():
    load_env()
    location_id = os.environ["GHL_LOCATION_ID"]
    RAW.mkdir(parents=True, exist_ok=True)

    pipelines = fetch_pipelines(location_id)
    pipeline_id = next((p["id"] for p in pipelines if p["name"] == PIPELINE_NAME), None)
    if pipeline_id is None:
        sys.exit(f'No pipeline called "{PIPELINE_NAME}" in this location. Found: '
                 + ", ".join(p["name"] for p in pipelines))
    opportunities = fetch_opportunities(location_id, pipeline_id)
    contacts = fetch_contacts(location_id)

    for name, rows in (("pipelines", pipelines), ("opportunities", opportunities), ("contacts", contacts)):
        (RAW / f"{name}.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
        print(f"{name}: {len(rows)}")


if __name__ == "__main__":
    main()
