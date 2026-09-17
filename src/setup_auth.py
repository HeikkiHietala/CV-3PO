#!/usr/bin/env python3
"""
CV-3PO initial authentication setup.

Creates the authentication files required by CV-3PO:

    oauth.json
    otp.bin
    remote_credentials.json

Existing authentication files are never overwritten automatically.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
PSACC_SRC = BASE_DIR / "psacc-src"

OAUTH_FILE = BASE_DIR / "oauth.json"
OTP_FILE = BASE_DIR / "otp.bin"
REMOTE_FILE = BASE_DIR / "remote_credentials.json"

SCOPE = ["openid", "profile"]


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

    client_id = require_env("OAUTH_CLIENT_ID")
    client_secret = require_env("OAUTH_CLIENT_SECRET")
    realm = require_env("OAUTH_REALM")
    country_code = require_env("COUNTRY_CODE")

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
    print("PREVIEW ONLY: no OAuth request has been completed")
    print("and no authentication files have been written.")


if __name__ == "__main__":
    main()
