#!/usr/bin/env python3
"""
Citroen EV Hub - one-shot MQTT wakeup with automatic remote-token recovery.
"""
import json, os, random, re, socket, ssl, sys, threading, time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import requests
import paho.mqtt.client as mqtt

BASE_DIR = Path(__file__).resolve().parent
SERVER_DIR = BASE_DIR
REMOTE_DIR = BASE_DIR
OAUTH_FILE = BASE_DIR / "oauth.json"
REMOTE_FILE = BASE_DIR / "remote_credentials.json"
OTP_FILE = BASE_DIR / "otp.bin"
PSACC_SRC = BASE_DIR / "psacc-src"
API_BASE = "https://api.groupe-psa.com"
USER_INFO_URL = API_BASE + "/applications/cvs/v4/mauv/car-associations"
VEHICLES_URL = API_BASE + "/connectedcar/v4/user/vehicles"
REMOTE_TOKEN_URL = API_BASE + "/connectedcar/v4/virtualkey/remoteaccess/token"
MQTT_SERVER = "mwa.mpsa.com"
MQTT_PORT = 8885
MQTT_KEEPALIVE = 120
REQ_PREFIX = "psa/RemoteServices/from/cid/"
RESP_PREFIX = "psa/RemoteServices/to/cid/"
EVENT_PREFIX = "psa/RemoteServices/events/MPHRTServices/"

def fail(message, code=1):
    print("ERROR:", message)
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
    if not value: return None
    try: return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception: return None

def safe_error(response):
    try: data = response.json()
    except Exception: return response.text[:300]
    if isinstance(data, dict):
        return data.get("error_description") or data.get("error") or data.get("message") or str(data)
    return str(data)

def refresh_oauth_if_needed(client_id, client_secret, token_url):
    oauth = load_json(OAUTH_FILE)
    access, refresh = oauth.get("access_token"), oauth.get("refresh_token")
    if not access or not refresh: fail("oauth.json is missing access_token or refresh_token")
    expiry = parse_expiry(oauth.get("expires_at"))
    if expiry and expiry > time.time() + 300:
        print("OAuth token:       valid"); return oauth
    print("OAuth token:       refreshing...")
    try:
        r = requests.post(token_url, auth=(client_id, client_secret), data={"grant_type":"refresh_token","refresh_token":refresh}, headers={"Accept":"application/json","Content-Type":"application/x-www-form-urlencoded","User-Agent":"MyCitroen/1.0 okhttp/4.8.0"}, timeout=30)
    except requests.RequestException as exc: fail("OAuth refresh failed: " + str(exc))
    if not 200 <= r.status_code < 300: fail("OAuth refresh rejected: " + safe_error(r))
    data = r.json()
    if not data.get("access_token"): fail("OAuth refresh response has no access_token")
    if not data.get("refresh_token"): data["refresh_token"] = refresh
    expires_in = int(data.get("expires_in") or 0)
    data["expires_at"] = datetime.fromtimestamp(time.time()+expires_in, timezone.utc).isoformat()
    data["stored_at"] = datetime.now(timezone.utc).isoformat()
    atomic_json(OAUTH_FILE, data)
    print("OAuth refresh:     OK")
    return data

def api_headers(access_token, realm):
    return {"Authorization":"Bearer "+access_token,"User-Agent":"okhttp/4.8.0","Accept":"application/hal+json","x-introspect-realm":realm}

def get_customer_id(client_id, locale, access_token, realm):
    headers = api_headers(access_token, realm); headers["x-transaction-id"] = str(uuid4())
    try: r = requests.get(USER_INFO_URL, params={"client_id":client_id,"locale":locale}, headers=headers, timeout=30)
    except requests.RequestException as exc: fail("car-associations request failed: " + str(exc))
    if not 200 <= r.status_code < 300: fail("car-associations rejected: " + safe_error(r))
    data = r.json()
    if not isinstance(data, list) or not data: fail("car-associations returned no associations")
    customer = data[0].get("customer")
    if not customer: fail("car-associations did not contain customer")
    return str(customer)

def get_vin(client_id, locale, access_token, realm):
    try: r = requests.get(VEHICLES_URL, params={"client_id":client_id,"locale":locale}, headers=api_headers(access_token, realm), timeout=30)
    except requests.RequestException as exc: fail("vehicle list request failed: " + str(exc))
    if not 200 <= r.status_code < 300: fail("vehicle list rejected: " + safe_error(r))
    vehicles = r.json().get("_embedded", {}).get("vehicles", [])
    if not vehicles: fail("No vehicle found")
    vin = vehicles[0].get("vin")
    if not vin: fail("Vehicle entry does not contain VIN")
    return str(vin)

def acquire_remote_token_via_otp(client_id, access_token, realm):
    if not OTP_FILE.exists(): fail("Cannot recover remote token: otp.bin is missing")
    if not PSACC_SRC.exists(): fail("Cannot recover remote token: psacc-src is missing")
    print("Remote token:      recovering via OTP...")
    sys.path.insert(0, str(PSACC_SRC))
    try: from psa_car_controller.psa.otp.otp import load_otp, save_otp
    except Exception as exc: fail("Cannot import OTP module: " + repr(exc))
    old_cwd = Path.cwd(); otp_password = None
    os.chdir(REMOTE_DIR)
    try:
        otp = load_otp(str(OTP_FILE))
        if otp is None: fail("otp.bin could not be loaded")
        print("OTP session:       OK")
        otp_password = otp.get_otp_code()
        save_otp(otp, str(OTP_FILE))
    except SystemExit: raise
    except Exception as exc: fail("OTP generation failed: " + repr(exc))
    finally: os.chdir(old_cwd)
    if not otp_password: fail("OTP generator returned an empty value")
    print("OTP password:      generated (not displayed)")
    try:
        r = requests.post(REMOTE_TOKEN_URL, params={"client_id":client_id}, headers={**api_headers(access_token, realm),"Content-Type":"application/json"}, json={"grant_type":"password","password":otp_password}, timeout=30)
    except requests.RequestException as exc: fail("Remote token recovery failed: " + str(exc))
    finally: otp_password = None
    if not 200 <= r.status_code < 300: fail("Remote token recovery rejected: " + safe_error(r))
    data = r.json()
    if not data.get("access_token"): fail("Remote recovery response has no access_token")
    data["stored_at"] = datetime.now(timezone.utc).isoformat()
    atomic_json(REMOTE_FILE, data)
    print("Remote token:      recovered")
    print("Remote refresh:    " + ("present" if data.get("refresh_token") else "missing"))
    return data

def refresh_remote_token(client_id, access_token, realm):
    remote = load_json(REMOTE_FILE)
    refresh = remote.get("refresh_token")
    if not refresh:
        print("Remote refresh:    missing")
        return acquire_remote_token_via_otp(client_id, access_token, realm)
    print("Remote token:      refreshing...")
    try:
        r = requests.post(REMOTE_TOKEN_URL, params={"client_id":client_id}, headers={**api_headers(access_token, realm),"Content-Type":"application/json"}, json={"grant_type":"refresh_token","refresh_token":refresh}, timeout=30)
    except requests.RequestException as exc: fail("Remote token refresh failed: " + str(exc))
    if 200 <= r.status_code < 300:
        data = r.json()
        if not data.get("access_token"): fail("Remote token response has no access_token")
        if not data.get("refresh_token"): data["refresh_token"] = refresh
        data["stored_at"] = datetime.now(timezone.utc).isoformat()
        atomic_json(REMOTE_FILE, data)
        print("Remote refresh:    OK")
        return data
    error = str(safe_error(r))
    print("Remote refresh rejected: " + error)
    if "grant is invalid" in error.lower():
        return acquire_remote_token_via_otp(client_id, access_token, realm)
    fail("Remote token refresh rejected: " + error)

class MqttClientMod(mqtt.Client):
    def _create_socket_connection(self):
        if hasattr(self, "_get_proxy") and self._get_proxy(): return super()._create_socket_connection()
        addr_infos = list(socket.getaddrinfo(self._host, self._port, 0, socket.SOCK_STREAM)); random.shuffle(addr_infos)
        last_error = None
        for af, socktype, proto, _canonname, sa in addr_infos:
            sock = None
            try:
                sock = socket.socket(af, socktype, proto)
                if af in (socket.AF_INET, socket.AF_INET6):
                    try: sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_MAXSEG, 1456)
                    except OSError: pass
                sock.settimeout(self._connect_timeout); sock.connect(sa); return sock
            except OSError as exc:
                last_error = exc
                if sock is not None: sock.close()
        if last_error: raise last_error
        raise OSError("No MQTT address could be connected")

def new_mqtt_client():
    try: return MqttClientMod(mqtt.CallbackAPIVersion.VERSION1, clean_session=True, protocol=mqtt.MQTTv311)
    except (AttributeError, TypeError): return MqttClientMod(clean_session=True, protocol=mqtt.MQTTv311)

def main():
    print("Citroen EV Hub - MQTT wakeup test\n----------------------------------\nThis test sends ONE wakeup command only.\n")
    for p in (OAUTH_FILE, REMOTE_FILE, OTP_FILE, PSACC_SRC):
        if not p.exists(): fail("Missing required item: " + str(p))

    client_id = os.environ.get("OAUTH_CLIENT_ID")
    client_secret = os.environ.get("OAUTH_CLIENT_SECRET")
    realm = os.environ.get("OAUTH_REALM", "clientsB2CCitroen")
    locale = os.environ.get("LOCALE", "fi-FI")
    token_url = os.environ.get(
        "OAUTH_TOKEN_URL",
        "https://idpcvs.citroen.com/am/oauth2/access_token",
    )
    if not client_id or not client_secret: fail("OAuth client ID/secret missing")
    oauth = refresh_oauth_if_needed(client_id, client_secret, token_url); access_token = oauth["access_token"]
    print("\n[1] Getting account/vehicle information...")
    customer_id = get_customer_id(client_id, locale, access_token, realm); vin = get_vin(client_id, locale, access_token, realm)
    print("Customer ID:       " + customer_id[:4] + "…" + customer_id[-4:]); print("VIN:               " + vin[:4] + "…" + vin[-4:])
    print("\n[2] Refreshing remote/MQTT token...")
    remote = refresh_remote_token(client_id, access_token, realm); remote_access = remote["access_token"]
    response_topic = RESP_PREFIX + customer_id + "/#"; event_topic = EVENT_PREFIX + vin; request_topic = REQ_PREFIX + customer_id + "/VehCharge/state"
    connected = threading.Event(); got_response = threading.Event(); result_holder = {}
    client = new_mqtt_client(); client.username_pw_set("IMA_OAUTH_ACCESS_TOKEN", remote_access); client.tls_set_context(ssl.create_default_context())
    def on_connect(c, userdata, flags, rc, properties=None):
        print("MQTT connect:      code", rc)
        if rc == 0:
            c.subscribe(response_topic, qos=0); c.subscribe(event_topic, qos=0); connected.set()
    def on_message(c, userdata, msg):
        try: payload = json.loads(msg.payload.decode("utf-8", errors="replace"))
        except Exception: payload = {"raw": msg.payload.decode("utf-8", errors="replace")[:300]}
        if isinstance(payload, dict): payload.pop("access_token", None)
        result_holder["topic"] = msg.topic; result_holder["payload"] = payload
        print("\nMQTT response received\nTopic:             ", msg.topic)
        if isinstance(payload, dict):
            rc = payload.get("return_code", payload.get("process_code"))
            if rc is not None: print("Return/process code:", rc)
            if payload.get("reason"): print("Reason:             ", payload.get("reason"))
        got_response.set()
    def on_disconnect(c, userdata, rc, properties=None):
        if rc != 0: print("MQTT disconnected unexpectedly, code", rc)
    client.on_connect = on_connect; client.on_message = on_message; client.on_disconnect = on_disconnect
    print("\n[3] Connecting to Stellantis MQTT...")
    try: client.connect(MQTT_SERVER, MQTT_PORT, MQTT_KEEPALIVE)
    except Exception as exc: fail("MQTT connect failed: " + repr(exc))
    client.loop_start()
    if not connected.wait(15):
        client.loop_stop()
        try: client.disconnect()
        except Exception: pass
        fail("MQTT connection did not complete within 15 seconds")
    print("MQTT:              connected")
    now = datetime.now(timezone.utc); correlation_id = uuid4().hex + now.strftime("%Y%m%d%H%M%S%f")[:-3]
    payload = {"access_token":remote_access,"customer_id":customer_id,"correlation_id":correlation_id,"req_date":now.strftime("%Y-%m-%dT%H:%M:%SZ"),"vin":vin,"req_parameters":{"action":"state"}}
    print("\n[4] Sending ONE wakeup...")
    info = client.publish(request_topic, json.dumps(payload), qos=0, retain=False)
    if info.rc != mqtt.MQTT_ERR_SUCCESS:
        client.loop_stop(); client.disconnect(); fail("MQTT publish failed: " + mqtt.error_string(info.rc))
    print("Publish:           OK\nWaiting up to 30 seconds for response...")
    got = got_response.wait(30); client.loop_stop()
    try: client.disconnect()
    except Exception: pass
    print("\n----------------------------------")
    if got:
        payload = result_holder.get("payload", {}); result_code = payload.get("return_code", payload.get("process_code")) if isinstance(payload, dict) else None
        if str(result_code) == "0":
            print("WAKEUP ACCEPTED (return code 0)")
        elif str(result_code) == "901":
            print("Vehicle reported sleep state (code 901).")
            print("The command was delivered; a following status check may still receive fresh data.")
        else:
            print("MQTT command received a response.\nInspect the non-secret return/process code above.")
    else:
        print("No MQTT response was received within 30 seconds.\nThe publish itself succeeded, so check vehicle status after about a minute.")
    print("\nNo token values were printed.")

if __name__ == "__main__": main()
