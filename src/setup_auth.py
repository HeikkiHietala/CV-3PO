#!/usr/bin/env python3
"""
CV-3PO initial authentication setup.

Creates the authentication files required by CV-3PO:

    oauth.json
    otp.bin
    remote_credentials.json

Existing authentication files are never overwritten automatically.
"""

import bz2
import json
import os
import sys
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
PSACC_SRC = BASE_DIR / "psacc-src"

OAUTH_FILE = BASE_DIR / "oauth.json"
OTP_FILE = BASE_DIR / "otp.bin"
REMOTE_FILE = BASE_DIR / "remote_credentials.json"

SCOPE = ["openid", "profile"]

APK_BZ2_URL = (
    "https://raw.githubusercontent.com/flobz/psa_apk/master/"
    "mycitroen.apk.bz2"
)


def fail(message, code=1):
    print("ERROR:", message)
    raise SystemExit(code)

def atomic_json(path: Path, data: dict):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)


def require_env(name):
    value = os.environ.get(name)
    if not value:
        fail(f"Missing required environment variable: {name}")
    return value



def get_oauth_credentials_from_apk(country_code):
    apk_bz2 = BASE_DIR / "mycitroen.apk.bz2"
    apk_file = BASE_DIR / "mycitroen.apk"

    print()
    print("Retrieving MyCitroen application configuration...")

    try:
        print("Downloading MyCitroen APK (~32 MB)...")
        urllib.request.urlretrieve(APK_BZ2_URL, apk_bz2)

        print("Decompressing APK...")
        with bz2.open(apk_bz2, "rb") as source:
            with apk_file.open("wb") as target:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    target.write(chunk)

        print("Reading OAuth configuration from APK...")

        with zipfile.ZipFile(apk_file) as apk:
            cultures = json.loads(
                apk.read("res/raw/cultures.json")
            )

            country = country_code.upper()
            if country not in cultures:
                fail(
                    "Country code is not present in MyCitroen APK: "
                    + country
                )

            culture = cultures[country]["languages"][0]
            language, region = culture.split("_", 1)

            parameters_path = (
                f"res/raw-{language}-r{region}/parameters.json"
            )

            parameters = json.loads(
                apk.read(parameters_path)
            )

            client_id = parameters.get("cvsClientId")
            client_secret = parameters.get("cvsSecret")

            if not client_id or not client_secret:
                fail(
                    "OAuth client configuration was not found "
                    "in MyCitroen APK"
                )

        print(
            "OAuth application credentials found "
            f"for {culture}."
        )
        return client_id, client_secret

    except SystemExit:
        raise
    except Exception as exc:
        fail(f"Could not retrieve OAuth configuration: {exc}")

    finally:
        for path in (apk_file, apk_bz2):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

def main():
    print("CV-3PO initial authentication setup")
    print("-----------------------------------")

    if not PSACC_SRC.exists():
        fail(
            "psa_car_controller source is missing: "
            + str(PSACC_SRC)
        )

    existing = [
        path.name
        for path in (OAUTH_FILE, OTP_FILE, REMOTE_FILE)
        if path.exists()
    ]

    if existing:
        print()
        print("Existing authentication files detected:")
        for name in existing:
            print("  -", name)

        print()
        print("Setup stopped without changing anything.")
        print("Existing authentication files are protected.")
        return

    sys.path.insert(0, str(PSACC_SRC))

    from oauth2_client.credentials_manager import ServiceInformation
    from psa_car_controller.psa.constants import (
        AUTHORIZE_SERVICE,
        realm_info,
    )
    from psa_car_controller.psa.oauth import OpenIdCredentialManager

    class CapturingOpenIdCredentialManager(OpenIdCredentialManager):
        def __init__(self, service_information, proxies=None):
            super().__init__(service_information, proxies)
            self.last_token_response = None

        def _process_token_response(
            self,
            token_response,
            refresh_token_mandatory,
        ):
            self.last_token_response = dict(token_response)
            super()._process_token_response(
                token_response,
                refresh_token_mandatory,
            )

    realm = require_env("OAUTH_REALM")
    country_code = require_env("COUNTRY_CODE")

    client_id, client_secret = get_oauth_credentials_from_apk(
        country_code
    )

    if realm not in realm_info or realm not in AUTHORIZE_SERVICE:
        fail(f"Unknown OAuth realm: {realm}")

    service_information = ServiceInformation(
        AUTHORIZE_SERVICE[realm],
        realm_info[realm]["oauth_url"],
        client_id,
        client_secret,
        SCOPE,
        True,
    )

    manager = CapturingOpenIdCredentialManager(
        service_information
    )
    manager.redirect_uri = (
        realm_info[realm]["scheme"]
        + "://oauth2redirect/"
        + country_code.lower()
    )

    login_url = manager.generate_redirect_url()

    print()
    print("No existing authentication files detected.")
    print()
    print("OAuth configuration:")
    print("  Realm:        ", realm)
    print("  Country code: ", country_code)
    print("  Redirect URI: ", manager.redirect_uri)
    print()
    print("Open this URL in a browser:")
    print()
    print(login_url)
    print()
    code = input("Enter the 36-character authorization code: ").strip()

    try:
        manager.connect_with_code(code)
    except Exception as exc:
        fail(f"OAuth authorization failed: {exc}")

    data = manager.last_token_response
    if not data:
        fail("OAuth succeeded but no token response was captured")

    if not data.get("access_token"):
        fail("OAuth response does not contain access_token")

    if not data.get("refresh_token"):
        fail("OAuth response does not contain refresh_token")

    expires_in = int(data.get("expires_in") or 0)
    data["expires_at"] = datetime.fromtimestamp(
        time.time() + expires_in,
        timezone.utc,
    ).isoformat()
    data["stored_at"] = datetime.now(timezone.utc).isoformat()

    atomic_json(OAUTH_FILE, data)

    print()
    print("OAuth authorization successful.")
    print("Created:", OAUTH_FILE)


if __name__ == "__main__":
    main()
