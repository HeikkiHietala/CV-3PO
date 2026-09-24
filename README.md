# CV-3PO

CV-3PO is an experimental Raspberry Pi based interface for retrieving status data and sending remote commands to compatible Citroen vehicles through Stellantis connected-car services.

## Features

- Retrieve vehicle status such as state of charge and estimated range
- Wake the vehicle through Stellantis remote services and MQTT
- Request fresh vehicle data and verify its timestamp
- Upload status data to a configurable web endpoint
- Run a lightweight agent for web-triggered and automatic status updates
- Keep credentials and vehicle-specific authentication data outside the Git repository

## Installation

CV-3PO is designed to be installed on Raspberry Pi OS using the included installer.

On a fresh Raspberry Pi OS installation, install Git first if it is not already available:

```bash
sudo apt update
sudo apt install -y git
```

```bash
git clone https://github.com/HeikkiHietala/CV-3PO.git cv3po
cd cv3po
```

Run the installer as your normal user:

```bash
chmod +x install.sh
./install.sh
```

Do not run the installer as root.

The installer installs the required system and Python packages, creates the Python virtual environment, installs the PSA Car Controller dependency, prepares the local runtime directory and configuration, runs vehicle authentication setup, and installs the CV-3PO web interface and systemd services.

When installation is complete, open:

```
http://cv3po.local/
```

## Configuration

The installer creates `.env` automatically from `.env.example` if it does not already exist.

The Stellantis OAuth client ID and client secret do not need to be entered manually. They are discovered automatically during authentication setup and stored locally in `.env`.

Never commit `.env`, OAuth tokens, OTP data, remote credentials, VINs, API keys, or other private vehicle/account information to Git.

## PSA Car Controller dependency

The current wakeup implementation uses OTP support from the upstream `psa_car_controller` project. The installer automatically clones this dependency into `src/psacc-src`.

The upstream project is licensed under GPLv3 and is intentionally kept outside this repository.

## Testing

Activate the virtual environment and load the configuration before running the tools:

```bash
source venv/bin/activate
set -a
source .env
set +a
```

Send one vehicle wakeup command:

```bash
python src/wakeup.py
```

Wake the vehicle and wait for fresh status data:

```bash
python src/live_status.py
```

## Authentication files

The installer runs the interactive vehicle authentication setup automatically.

To run the authentication setup manually, use `python src/setup_auth.py`.

If authentication setup is interrupted, run the same command again. Completed authentication stages are reused where possible.

Remote vehicle commands also require local authentication files in the `src` directory:

- `oauth.json`
- `remote_credentials.json`
- `otp.bin`

These files contain private authentication material, are excluded by `.gitignore`, and must never be committed or shared.

## systemd service

The installer configures and enables the CV-3PO status service and timer automatically.

Check the timer with:

```bash
systemctl status cv3po-status.timer --no-pager
```

Check the status service with:

```bash
systemctl status cv3po-status.service --no-pager
```

The service uses the project virtual environment and loads configuration from `.env`.
