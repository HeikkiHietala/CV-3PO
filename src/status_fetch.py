#!/usr/bin/env python3
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import requests

BASE_DIR = Path(__file__).resolve().parent
OAUTH_FILE = BASE_DIR / "oauth.json"
STATUS_FILE = BASE_DIR.parent / "data" / "status.json"

API_BASE = "https://api.groupe-psa.com"
VEHICLES_URL = API_BASE + "/connectedcar/v4/user/vehicles"

# Put the same long random value in fetch_status.php.
STATUS_URL = os.environ.get("STATUS_URL")
STATUS_KEY = os.environ.get("STATUS_KEY")


def fail(message, code=1):
    print("ERROR:", message, flush=True)
    raise SystemExit(code)


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"Cannot read {path}: {exc}")


def atomic_json(path: Path, data: dict):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)


def parse_expiry(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def safe_error(response):
    try:
        data = response.json()
    except Exception:
        return response.text[:300]
    if isinstance(data, dict):
        return data.get("error_description") or data.get("error") or data.get("message") or str(data)
    return str(data)


def refresh_oauth_if_needed(client_id, client_secret, token_url):
    oauth = load_json(OAUTH_FILE)
    access = oauth.get("access_token")
    refresh = oauth.get("refresh_token")
    if not access or not refresh:
        fail("oauth.json is missing access_token or refresh_token")

    expiry = parse_expiry(oauth.get("expires_at"))
    if expiry and expiry > time.time() + 300:
        print("OAuth token:       valid")
        return oauth

    print("OAuth token:       refreshing...")
    r = requests.post(
        token_url,
        auth=(client_id, client_secret),
        data={"grant_type": "refresh_token", "refresh_token": refresh},
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "MyCitroen/1.0 okhttp/4.8.0",
        },
        timeout=30,
    )
    if not 200 <= r.status_code < 300:
        fail("OAuth refresh rejected: " + safe_error(r))

    data = r.json()
    if not data.get("access_token"):
        fail("OAuth refresh response has no access_token")
    if not data.get("refresh_token"):
        data["refresh_token"] = refresh

    expires_in = int(data.get("expires_in") or 0)
    data["expires_at"] = datetime.fromtimestamp(time.time() + expires_in, timezone.utc).isoformat()
    data["stored_at"] = datetime.now(timezone.utc).isoformat()
    atomic_json(OAUTH_FILE, data)
    print("OAuth refresh:     OK")
    return data


def api_headers(access_token, realm):
    return {
        "Authorization": "Bearer " + access_token,
        "User-Agent": "okhttp/4.8.0",
        "Accept": "application/hal+json",
        "x-introspect-realm": realm,
    }


def get_vehicle(client_id, locale, access_token, realm):
    r = requests.get(
        VEHICLES_URL,
        params={"client_id": client_id, "locale": locale},
        headers=api_headers(access_token, realm),
        timeout=30,
    )
    if not 200 <= r.status_code < 300:
        fail("vehicle list rejected: " + safe_error(r))
    vehicles = r.json().get("_embedded", {}).get("vehicles", [])
    if not vehicles:
        fail("No vehicle found")
    vehicle_id = vehicles[0].get("id")
    if not vehicle_id:
        fail("Vehicle entry does not contain id")
    return str(vehicle_id)


def get_status(vehicle_id, client_id, locale, access_token, realm):
    url = API_BASE + "/connectedcar/v4/user/vehicles/" + quote(vehicle_id, safe="") + "/status"
    headers = api_headers(access_token, realm)
    headers["x-transaction-id"] = str(uuid4())
    r = requests.get(
        url,
        params={"client_id": client_id, "locale": locale},
        headers=headers,
        timeout=30,
    )
    if not 200 <= r.status_code < 300:
        fail("vehicle status rejected: " + safe_error(r))
    return r.json()


def status_summary(status):
    energies = status.get("energies") or []

    electric = next(
        (
            e for e in energies
            if isinstance(e, dict)
            and str(e.get("type", "")).lower() == "electric"
        ),
        energies[0]
        if energies and isinstance(energies[0], dict)
        else {},
    )

    electric_extension = (
        (electric.get("extension") or {}).get("electric") or {}
    )

    charging = electric_extension.get("charging") or {}
    traction_battery = electric_extension.get("battery") or {}
    battery_load = traction_battery.get("load") or {}
    battery_health = traction_battery.get("health") or {}

    env = ((status.get("environment") or {}).get("air") or {})
    kinetic = status.get("kinetic") or {}
    driving_behavior = status.get("drivingBehavior") or {}
    odometer = status.get("odometer") or {}

    doors = status.get("doorsState") or {}
    locked_states = doors.get("lockedStates") or []
    openings = doors.get("opening") or []

    preconditioning = (
        ((status.get("preconditioning") or {})
         .get("airConditioning") or {})
    )

    open_doors = [
        door.get("identifier")
        for door in openings
        if isinstance(door, dict)
        and str(door.get("state", "")).lower() != "closed"
    ]

    return {
        # Existing fields
        "soc": electric.get("level"),
        "rangeKm": electric.get("autonomy"),
        "chargingStatus": charging.get("status"),
        "plugged": charging.get("plugged"),
        "remainingTime": charging.get(
            "remainingTime",
            charging.get("remainingChargeTime")
        ),
        "outsideTemperature": env.get("temp"),

        # Vehicle state
        "odometerKm": odometer.get("mileage"),
        "speedKmh": kinetic.get("speed"),
        "moving": kinetic.get("moving"),
        "drivingMode": driving_behavior.get("mode"),

        # Doors
        "doorsLocked": "Locked" in locked_states,
        "openDoors": open_doors,

        # Climate / preconditioning
        "preconditioningStatus": preconditioning.get("status"),

        # Traction battery
        "batteryCapacityWh": battery_load.get("capacity"),
        "batteryResidualWh": battery_load.get("residual"),
        "batteryHealthCapacity": battery_health.get("capacity"),
        "batteryHealthResistance": battery_health.get("resistance"),

        # Charging
        "chargingRate": charging.get("chargingRate"),
        "chargingMode": charging.get("chargingMode"),
        "chargingType": charging.get("type"),
        "nextDelayedTime": charging.get("nextDelayedTime"),
    }

def main():
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)

    if not OAUTH_FILE.exists():
        fail("Missing required file: " + str(OAUTH_FILE))

    client_id = os.environ.get("OAUTH_CLIENT_ID")
    client_secret = os.environ.get("OAUTH_CLIENT_SECRET")
    realm = os.environ.get("OAUTH_REALM", "clientsB2CCitroen")
    locale = os.environ.get("LOCALE", "fi-FI")
    token_url = os.environ.get(
        "OAUTH_TOKEN_URL",
        "https://idpcvs.citroen.com/am/oauth2/access_token",
    )

    if not client_id or not client_secret:
        fail("OAuth client ID/secret missing")

    oauth = refresh_oauth_if_needed(client_id, client_secret, token_url)
    vehicle_id = get_vehicle(client_id, locale, oauth["access_token"], realm)
    raw = get_status(vehicle_id, client_id, locale, oauth["access_token"], realm)

    payload = {
        "ok": True,
        "vehicleId": vehicle_id,
        "raw": raw,
        "summary": status_summary(raw),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "ec4pi",
    }

    atomic_json(STATUS_FILE, payload)
    os.chmod(STATUS_FILE, 0o640)

    if STATUS_URL and STATUS_KEY:
        r = requests.post(
            STATUS_URL,
            headers={"X-EC4-Status-Key": STATUS_KEY, "Content-Type": "application/json"},
            data=json.dumps(payload, ensure_ascii=False),
            timeout=30,
        )
        if not 200 <= r.status_code < 300:
            fail("status upload rejected: " + safe_error(r))

    s = payload["summary"]
    print(f"Status saved: SoC={s.get('soc')}% range={s.get('rangeKm')} km")


if __name__ == "__main__":
    main()
