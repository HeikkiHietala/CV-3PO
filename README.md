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

Clone the repository, create a Python virtual environment, and install the required Python packages:

```bash
git clone https://github.com/HeikkiHietala/CV-3PO.git cv3po
cd cv3po
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Copy the example configuration and edit it with your own endpoint settings:

```bash
cp .env.example .env
chmod 600 .env
```

The Stellantis OAuth client ID and client secret do not need to be entered manually. They are discovered automatically during authentication setup and stored locally in `.env`.

Never commit `.env`, OAuth tokens, OTP data, remote credentials, VINs, API keys, or other private vehicle/account information to Git.

## PSA Car Controller dependency

The current wakeup implementation uses the OTP support from the upstream `psa_car_controller` project. Clone it into `src/psacc-src`:

```bash
git clone https://github.com/flobz/psa_car_controller.git src/psacc-src
```

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

Run the authentication setup before using remote vehicle commands.

Run `python src/setup_auth.py`.

If authentication setup is interrupted, run the same command again. Completed authentication stages are reused where possible.

Remote vehicle commands also require local authentication files in the `src` directory:

- `oauth.json`
- `remote_credentials.json`
- `otp.bin`

These files contain private authentication material, are excluded by `.gitignore`, and must never be committed or shared.

## systemd service

A tested oneshot service example is included in `systemd/cv3po-status.service.example`.

Copy the example service file into systemd:

```bash
sudo cp systemd/cv3po-status.service.example /etc/systemd/system/cv3po-status.service
```

Edit the installed service file and replace `YOUR_USER` with your Linux username:

```bash
sudo micro /etc/systemd/system/cv3po-status.service
```

Then reload systemd and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl start cv3po-status.service
```

Check the result with:

```bash
systemctl status cv3po-status.service --no-pager
```

The service uses the project virtual environment and loads configuration from `.env` through `EnvironmentFile=`.

