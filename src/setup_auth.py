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
import requests
import shutil
import sys
import tempfile
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
ENV_FILE = PROJECT_DIR / ".env"
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



def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"Could not read {path.name}: {exc}")

def load_env_file():
    if not ENV_FILE.exists():
        return

    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")

        if name:
            os.environ.setdefault(name, value)        

def require_env(name):
    value = os.environ.get(name)
    if not value:
        fail(f"Missing required environment variable: {name}")
    return value

def extract_authorization_code(value):
    value = value.strip()

    if "code=" in value:
        value = value.split("code=", 1)[1].split("&", 1)[0]

    if len(value) != 36:
        fail(
            "Authorization code should be 36 characters. "
            "Paste either the code itself or the complete redirect URL."
        )

    return value


def save_oauth_client_to_env(client_id, client_secret):
    if not ENV_FILE.exists():
        fail(f"Missing .env file: {ENV_FILE}")

    values = {
        "OAUTH_CLIENT_ID": client_id,
        "OAUTH_CLIENT_SECRET": client_secret,
    }

    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    found = set()
    output = []

    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else None
        if key in values:
            output.append(f"{key}={values[key]}")
            found.add(key)
        else:
            output.append(line)

    if output and output[-1] != "":
        output.append("")

    for key, value in values.items():
        if key not in found:
            output.append(f"{key}={value}")

    ENV_FILE.write_text("\n".join(output) + "\n", encoding="utf-8")
    os.chmod(ENV_FILE, 0o600)
    print("OAuth client settings saved to .env")


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


def request_sms_code(manager, client_id, realm):
    url = (
        "https://api.groupe-psa.com/applications/cvs/v4/mobile/"
        "smsCode?client_id=" + client_id
    )
    headers = {
        "x-introspect-realm": realm,
        "accept": "application/hal+json",
        "User-Agent": "okhttp/4.8.0",
    }

    try:
        response = manager.post(
            url,
            headers=headers,
            timeout=30,
        )
    except Exception as exc:
        fail(f"SMS code request failed: {exc}")

    if not response.ok:
        fail(
            "SMS code request failed: "
            f"HTTP {response.status_code}"
        )

    return response


def create_otp_file(sms_code, pin_code):
    from psa_car_controller.psa.otp.otp import new_otp_session

    original_cwd = Path.cwd()

    try:
        with tempfile.TemporaryDirectory(prefix="cv3po-otp-") as tmp:
            tmp_path = Path(tmp)

            os.chdir(tmp_path)
            try:
                new_otp_session(sms_code, pin_code)
            finally:
                os.chdir(original_cwd)

            generated = tmp_path / "otp.bin"
            if not generated.exists():
                fail("OTP activation succeeded but otp.bin was not created")

            shutil.copyfile(generated, OTP_FILE)
            os.chmod(OTP_FILE, 0o600)

    except SystemExit:
        raise
    except Exception as exc:
        fail(f"OTP activation failed: {exc}")


def create_remote_credentials(client_id, access_token, realm):
    from psa_car_controller.psa.otp.otp import load_otp, save_otp

    api_base = "https://api.groupe-psa.com"
    remote_token_url = (
        api_base + "/connectedcar/v4/virtualkey/remoteaccess/token"
    )

    headers = {
        "Authorization": "Bearer " + access_token,
        "User-Agent": "okhttp/4.8.0",
        "Accept": "application/hal+json",
        "x-introspect-realm": realm,
        "Content-Type": "application/json",
    }

    max_attempts = 3
    response = None

    for attempt in range(1, max_attempts + 1):
        otp_password = None

        try:
            otp = load_otp(str(OTP_FILE))
            if otp is None:
                fail("otp.bin could not be loaded")

            otp_password = otp.get_otp_code()
            save_otp(otp, str(OTP_FILE))
            os.chmod(OTP_FILE, 0o600)

            if not otp_password:
                fail("OTP generator returned an empty value")

            response = requests.post(
                remote_token_url,
                params={"client_id": client_id},
                headers=headers,
                json={
                    "grant_type": "password",
                    "password": otp_password,
                },
                timeout=30,
            )

        except SystemExit:
            raise
        except Exception as exc:
            if attempt == max_attempts:
                fail(f"Remote token request failed: {exc}")

            print(
                f"Remote token request failed "
                f"(attempt {attempt}/{max_attempts})."
            )
            print("Retrying in 5 seconds...")
            time.sleep(5)
            continue

        finally:
            otp_password = None

        if response.ok:
            break

        if attempt == max_attempts:
            fail(
                "Remote token request rejected after "
                f"{max_attempts} attempts: HTTP {response.status_code}"
            )

        print(
            "Remote token request rejected: "
            f"HTTP {response.status_code} "
            f"(attempt {attempt}/{max_attempts})."
        )
        print("Retrying with a new OTP code in 5 seconds...")
        time.sleep(5)

    try:
        data = response.json()
    except Exception as exc:
        fail(f"Remote token response is not valid JSON: {exc}")

    if not data.get("access_token"):
        fail("Remote token response does not contain access_token")

    data["stored_at"] = datetime.now(timezone.utc).isoformat()
    atomic_json(REMOTE_FILE, data)

    print("Remote-command credentials created.")
    print("Created:", REMOTE_FILE)


def main():
    load_env_file()
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

    if REMOTE_FILE.exists():
        if not OAUTH_FILE.exists() or not OTP_FILE.exists():
            fail(
                "Authentication files are inconsistent: "
                "remote_credentials.json exists without all prerequisites"
            )

        print()
        print("Authentication setup is already complete.")
        print("Existing authentication files were not changed.")
        return

    if OTP_FILE.exists() and not OAUTH_FILE.exists():
        fail(
            "Authentication files are inconsistent: "
            "otp.bin exists without oauth.json"
        )

    if OAUTH_FILE.exists():
        print()
        print("OAuth authorization already completed.")
        print("Setup will continue with OTP provisioning.")

    sys.path.insert(0, str(PSACC_SRC))

    from oauth2_client.credentials_manager import ServiceInformation
    from psa_car_controller.psa.constants import (
        AUTHORIZE_SERVICE,
        realm_info,
    )
    from psa_car_controller.psa.oauth import OpenIdCredentialManager
    from psa_car_controller.psa.otp.otp import (
        new_otp_session,
    )

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
    save_oauth_client_to_env(client_id, client_secret)

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

    if OAUTH_FILE.exists():
        oauth_data = load_json(OAUTH_FILE)

        if not oauth_data.get("access_token"):
            fail("Existing oauth.json does not contain access_token")

        if not oauth_data.get("refresh_token"):
            fail("Existing oauth.json does not contain refresh_token")

        print("Existing oauth.json loaded successfully.")
        print("Refreshing OAuth token...")

        old_refresh_token = oauth_data["refresh_token"]

        try:
            manager.init_with_token(old_refresh_token)
        except Exception as exc:
            fail(f"OAuth token refresh failed: {exc}")

        refreshed = manager.last_token_response
        if not refreshed or not refreshed.get("access_token"):
            fail("OAuth refresh succeeded but no access_token was captured")

        if not refreshed.get("refresh_token"):
            refreshed["refresh_token"] = old_refresh_token

        expires_in = int(refreshed.get("expires_in") or 0)
        refreshed["expires_at"] = datetime.fromtimestamp(
            time.time() + expires_in,
            timezone.utc,
        ).isoformat()
        refreshed["stored_at"] = datetime.now(timezone.utc).isoformat()

        atomic_json(OAUTH_FILE, refreshed)
        oauth_data = refreshed

        print("OAuth token refreshed successfully.")

    else:
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
        print("After completing the Citroen login, the browser may appear to do nothing.")
        print("If that happens:")
        print("  1. Open Developer Tools (F12).")
        print("  2. Select the Console tab.")
        print("  3. Find the message containing mymacsdk://oauth2redirect/...")
        print("  4. Copy either the complete redirect URL or just the code= value.")
        print()

        code_input = input("Paste the authorization code or redirect URL: ")
        code = extract_authorization_code(code_input)
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
        oauth_data = data

        print()
        print("OAuth authorization successful.")
        print("Created:", OAUTH_FILE)


    if not OTP_FILE.exists():
        print()
        print("Requesting SMS activation code...")

        request_sms_code(manager, client_id, realm)

        print("SMS activation code requested.")
        print()
        sms_code = input("Enter the SMS activation code: ").strip()
        pin_code = input("Choose a PIN for remote commands: ").strip()

        if not sms_code:
            fail("SMS activation code cannot be empty")

        if not pin_code:
            fail("PIN cannot be empty")

        print()
        print("Activating remote-command OTP...")

        create_otp_file(sms_code, pin_code)

        print("OTP activation successful.")
        print("Created:", OTP_FILE)

    else:
        print()
        print("Existing otp.bin detected.")
        print("OTP provisioning already completed.")

    if not REMOTE_FILE.exists():
        print()
        print("Creating remote-command credentials...")

        create_remote_credentials(
            client_id,
            oauth_data["access_token"],
            realm,
        )

    else:
        print()
        print("Existing remote_credentials.json detected.")
        print("Remote-command provisioning already completed.")


if __name__ == "__main__":
    main()
