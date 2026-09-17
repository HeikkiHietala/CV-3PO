#!/usr/bin/env python3
"""
CV-3PO initial authentication setup.

Creates the authentication files required by CV-3PO:

    oauth.json
    otp.bin
    remote_credentials.json

The setup uses psa_car_controller for the Stellantis OAuth and OTP
protocols.

IMPORTANT:
Existing authentication files are never overwritten automatically.
"""

import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
PSACC_SRC = BASE_DIR / "psacc-src"

OAUTH_FILE = BASE_DIR / "oauth.json"
OTP_FILE = BASE_DIR / "otp.bin"
REMOTE_FILE = BASE_DIR / "remote_credentials.json"


def fail(message, code=1):
    print("ERROR:", message)
    raise SystemExit(code)


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

    print()
    print("No existing authentication files detected.")
    print("Ready for initial authentication setup.")
    print()
    print("OAuth and OTP provisioning will be added next.")


if __name__ == "__main__":
    main()
