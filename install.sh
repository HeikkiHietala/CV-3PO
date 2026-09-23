#!/bin/bash
set -euo pipefail

echo
echo "CV-3PO installer"
echo "================"
echo

if [ "$(id -u)" -eq 0 ]; then
    echo "Please run this installer as your normal user, not as root."
    exit 1
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CV3PO_USER="$(id -un)"
CV3PO_HOSTNAME="cv3po"

echo "User:    $CV3PO_USER"
echo "Project: $PROJECT_DIR"
echo

echo "Installing required system packages..."
sudo apt-get update
sudo apt-get install -y \
    git \
    python3 \
    python3-venv \
    python3-pip \
    apache2 \
    php \
    libapache2-mod-php

echo "Configuring CV-3PO hostname..."
if [ "$(hostname)" != "$CV3PO_HOSTNAME" ]; then
    sudo hostnamectl set-hostname "$CV3PO_HOSTNAME"
    echo "Hostname changed to $CV3PO_HOSTNAME."
else
    echo "Hostname already set to $CV3PO_HOSTNAME."
fi

echo "Creating CV-3PO system group..."
sudo groupadd -f cv3po

echo "Adding users to CV-3PO group..."
sudo usermod -aG cv3po "$CV3PO_USER"
sudo usermod -aG cv3po www-data

echo "Creating CV-3PO runtime directory..."
sudo install -d -m 2770 -o "$CV3PO_USER" -g cv3po /var/lib/cv3po

echo "Setting up Python environment..."
if [ ! -x "$PROJECT_DIR/venv/bin/python" ] || [ ! -x "$PROJECT_DIR/venv/bin/pip" ]; then
    echo "Creating or repairing Python virtual environment..."
    rm -rf "$PROJECT_DIR/venv"
    python3 -m venv "$PROJECT_DIR/venv"
fi

"$PROJECT_DIR/venv/bin/python" -m pip install --upgrade pip
"$PROJECT_DIR/venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

echo "Checking PSA Car Controller dependency..."
if [ ! -d "$PROJECT_DIR/src/psacc-src/.git" ]; then
    git clone https://github.com/flobz/psa_car_controller.git "$PROJECT_DIR/src/psacc-src"
else
    echo "PSA Car Controller already installed."
fi

echo "Preparing CV-3PO configuration..."
if [ ! -f "$PROJECT_DIR/.env" ]; then
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    chmod 600 "$PROJECT_DIR/.env"
    echo "Created .env from .env.example."
else
    echo "Existing .env preserved."
fi

echo "Setting up vehicle authentication..."
set -a
source "$PROJECT_DIR/.env"
set +a
"$PROJECT_DIR/venv/bin/python" "$PROJECT_DIR/src/setup_auth.py"

echo "Installing CV-3PO web interface..."
sudo install -d -m 755 -o root -g root /var/www/cv3po
sudo cp -a "$PROJECT_DIR/web/." /var/www/cv3po/
sudo chown -R root:root /var/www/cv3po
sudo find /var/www/cv3po -type d -exec chmod 755 {} +
sudo find /var/www/cv3po -type f -exec chmod 644 {} +

echo "Installing Apache configuration..."
sudo install -m 644 "$PROJECT_DIR/apache/cv3po.conf" /etc/apache2/sites-available/cv3po.conf
sudo a2dissite 000-default.conf >/dev/null
sudo a2ensite cv3po.conf >/dev/null
sudo apache2ctl configtest
sudo systemctl restart apache2

echo "Installing CV-3PO status service..."
sed \
    -e "s|__CV3PO_USER__|$CV3PO_USER|g" \
    -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    "$PROJECT_DIR/systemd/cv3po-status.service.example" \
    | sudo tee /etc/systemd/system/cv3po-status.service >/dev/null

sudo install -m 644 \
    "$PROJECT_DIR/systemd/cv3po-status.timer.example" \
    /etc/systemd/system/cv3po-status.timer

sudo systemctl daemon-reload
sudo systemctl enable --now cv3po-status.timer

echo
echo "================================"
echo "CV-3PO installation complete."
echo "================================"
echo
echo "Vehicle status updates are running automatically."
echo "Open CV-3PO in your browser:"
echo
echo "    http://cv3po.local/"
echo
