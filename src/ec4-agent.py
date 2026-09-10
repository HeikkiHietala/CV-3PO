#!/usr/bin/env python3

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests


BASE_DIR = Path(__file__).resolve().parent

AGENT_URL = os.environ.get("AGENT_URL")
STATUS_URL = os.environ.get("STATUS_URL")
AGENT_KEY = os.environ.get("AGENT_KEY")

POLL_SECONDS = 10
REQUEST_TIMEOUT = 20

CHARGING_INTERVAL = 5 * 60
IDLE_INTERVAL = 20 * 60
FIRST_AUTO_DELAY = 60

BLUE_LED = 17
RED_LED = 27


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def set_led(pin, on):
    level = "dh" if on else "dl"
    try:
        subprocess.run(
            ["pinctrl", "set", str(pin), "op", level],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception as exc:
        log(f"LED control failed for GPIO{pin}: {exc}")


def thinking_on():
    set_led(BLUE_LED, True)


def thinking_off():
    set_led(BLUE_LED, False)


def error_on():
    set_led(RED_LED, True)


def error_off():
    set_led(RED_LED, False)


def job_success():
    thinking_off()
    error_off()


def job_failed():
    thinking_off()
    error_on()


def poll_task():
    r = requests.get(
        AGENT_URL,
        headers={"X-EC4-Key": AGENT_KEY},
        timeout=REQUEST_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def report_done(job_id, ok, return_code, output_tail):
    payload = {
        "job_id": job_id,
        "ok": bool(ok),
        "return_code": int(return_code),
        "output_tail": output_tail[-2000:],
    }

    r = requests.post(
        AGENT_URL,
        headers={
            "X-EC4-Key": AGENT_KEY,
            "Content-Type": "application/json",
        },
        data=json.dumps(payload),
        timeout=REQUEST_TIMEOUT,
    )
    r.raise_for_status()


def get_cached_status():
    r = requests.get(
        STATUS_URL,
        params={"ts": int(time.time())},
        headers={"Cache-Control": "no-cache"},
        timeout=REQUEST_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def is_charging(data):
    summary = data.get("summary") or {}
    status = str(summary.get("chargingStatus") or "").lower()

    return (
        "progress" in status
        or status == "charging"
        or status.startswith("charg")
    )


def next_interval_from_cache():
    try:
        data = get_cached_status()
        charging = is_charging(data)

        if charging:
            log("Charging detected -> next automatic refresh in 5 min")
            return CHARGING_INTERVAL

        log("Not charging -> next automatic refresh in 20 min")
        return IDLE_INTERVAL

    except Exception as exc:
        log(f"Could not read cached charging state: {exc}")
        log("Using 20 min fallback interval")
        return IDLE_INTERVAL


def run_script(filename, timeout):
    path = BASE_DIR / filename
    log(f"Running {filename}")

    # Stream live_status.py line by line. As soon as the first useful
    # status has been uploaded, THINKING can go dark even if the script
    # continues polling Stellantis for a newer vehicle timestamp.
    if filename == "live_status.py":
        proc = subprocess.Popen(
            [sys.executable, "-u", str(path)],
            cwd=str(BASE_DIR),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )

        output_lines = []
        status_received = False
        start = time.monotonic()

        try:
            while True:
                if time.monotonic() - start > timeout:
                    proc.kill()
                    proc.wait()
                    raise subprocess.TimeoutExpired(
                        cmd=[sys.executable, "-u", str(path)],
                        timeout=timeout,
                        output="".join(output_lines),
                    )

                line = proc.stdout.readline()

                if line:
                    output_lines.append(line)
                    print(line, end="", flush=True)

                    # live_status.py prints this only after valid data has
                    # been uploaded. At that point the user's request has
                    # effectively been answered.
                    if not status_received and "Status uploaded:" in line:
                        status_received = True
                        thinking_off()
                        log("Status received -> THINKING LED off")

                elif proc.poll() is not None:
                    break
                else:
                    time.sleep(0.1)

            return proc.returncode, "".join(output_lines)

        finally:
            if proc.stdout is not None:
                proc.stdout.close()

    # Other helper scripts keep the original simple behaviour.
    proc = subprocess.run(
        [sys.executable, str(path)],
        cwd=str(BASE_DIR),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )

    print(proc.stdout, end="", flush=True)
    return proc.returncode, proc.stdout


def execute_job(action):
    if action == "wakeup":
        return run_script("wakeup.py", 90)

    if action == "status":
        return run_script("live_status.py", 240)

    return 2, f"Unknown action: {action}\n"


def run_automatic_status():
    log("Automatic live status refresh")

    try:
        rc, output = run_script("live_status.py", 240)
        ok = (rc in (0, 2))

        if rc == 0:
            log("Automatic live status refresh complete")
        elif rc == 2:
            log("Automatic live status refresh complete - no newer vehicle timestamp")
        else:
            log(f"Automatic live status refresh ended with code {rc}")

        return ok, output

    except subprocess.TimeoutExpired:
        log("Automatic live status refresh timed out")
        return False, "TIMEOUT"


def main():
    missing = [
        name
        for name, value in (
            ("AGENT_URL", AGENT_URL),
            ("STATUS_URL", STATUS_URL),
            ("AGENT_KEY", AGENT_KEY),
        )
        if not value
    ]

    if missing:
        raise SystemExit(
            "Missing required environment variable(s): "
            + ", ".join(missing)
        )

    thinking_off()
    error_off()

    log("CV-3PO agent started")

    next_auto_at = time.monotonic() + FIRST_AUTO_DELAY
    log("First automatic status refresh scheduled in 1 min")

    while True:
        try:
            task = poll_task()
            action = task.get("action", "none")
            job_id = task.get("job_id")

            if action in ("wakeup", "status") and job_id:
                log(f"{action} job received: {job_id}")

                thinking_on()

                try:
                    rc, output = execute_job(action)

                    if action == "status":
                        ok = (rc in (0, 2))
                    else:
                        ok = (rc == 0)

                except subprocess.TimeoutExpired as exc:
                    rc = 124
                    ok = False

                    stdout = exc.stdout or ""
                    if isinstance(stdout, bytes):
                        stdout = stdout.decode(errors="replace")

                    output = stdout + "\nTIMEOUT"

                if ok:
                    job_success()
                else:
                    job_failed()

                try:
                    report_done(job_id, ok, rc, output)
                    log(
                        f"Job {job_id} complete, "
                        f"action={action}, ok={ok}, rc={rc}"
                    )

                except Exception as exc:
                    log(f"Could not report completion: {exc}")

                if action == "status":
                    next_auto_at = (
                        time.monotonic()
                        + next_interval_from_cache()
                    )

            elif action not in ("none", None, ""):
                log(f"Unknown action from server: {action!r}")

            if time.monotonic() >= next_auto_at:
                thinking_on()

                ok, output = run_automatic_status()

                if ok:
                    job_success()
                else:
                    job_failed()

                next_auto_at = (
                    time.monotonic()
                    + next_interval_from_cache()
                )

        except KeyboardInterrupt:
            thinking_off()
            log("Agent stopped")
            return

        except Exception as exc:
            log(f"Agent loop error: {exc}")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
