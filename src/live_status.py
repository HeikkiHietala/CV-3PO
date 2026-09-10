#!/usr/bin/env python3
import os
import subprocess, sys, time
from pathlib import Path
import requests

BASE_DIR = Path(__file__).resolve().parent
STATUS_URL = os.environ.get("STATUS_URL")
POLL_INTERVAL = 20
MAX_WAIT = 120

def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)

def get_cached():
    r = requests.get(STATUS_URL, params={"ts": int(time.time())}, timeout=20)
    r.raise_for_status()
    return r.json()

def created_at(data):
    try:
        e = data["raw"]["energies"]
        return e[0].get("createdAt") if e else None
    except Exception:
        return None

def run(name, timeout=90):
    p = subprocess.run(
        [sys.executable, str(BASE_DIR / name)],
        cwd=str(BASE_DIR),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    print(p.stdout, end="", flush=True)
    return p.returncode

def main():
    if not STATUS_URL:
        raise SystemExit("Missing required environment variable: STATUS_URL")

    log("Live status refresh started")

    try:
        baseline = created_at(get_cached())
    except Exception as exc:
        baseline = None
        print("Baseline read failed:", exc, flush=True)

    print("Baseline energy timestamp:", baseline or "unknown", flush=True)

    log("Sending wakeup")
    try:
        run("wakeup.py")
    except subprocess.TimeoutExpired:
        print("wakeup.py timeout", flush=True)

    started = time.monotonic()
    attempt = 0

    while True:
        attempt += 1
        log(f"Status poll {attempt}")

        try:
            rc = run("status_fetch.py")
        except subprocess.TimeoutExpired:
            rc = 124
            print("status_fetch.py timeout", flush=True)

        if rc == 0:
            try:
                data = get_cached()
                current = created_at(data)
                s = data.get("summary", {})
                print(
                    f"SoC={s.get('soc')}% range={s.get('rangeKm')} km "
                    f"energy_createdAt={current or 'unknown'}",
                    flush=True,
                )

                if baseline and current and current != baseline:
                    log("Fresh vehicle data confirmed")
                    return 0
            except Exception as exc:
                print("Status inspection failed:", exc, flush=True)

        elapsed = time.monotonic() - started
        if elapsed >= MAX_WAIT:
            print(
                f"No newer energy timestamp after {int(elapsed)} seconds.",
                flush=True,
            )
            return 2

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    raise SystemExit(main())
