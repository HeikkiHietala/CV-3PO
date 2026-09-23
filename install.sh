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

echo "User:    $CV3PO_USER"
echo "Project: $PROJECT_DIR"
echo

echo "Creating CV-3PO system group..."
sudo groupadd -f cv3po

echo "Adding users to CV-3PO group..."
sudo usermod -aG cv3po "$CV3PO_USER"
sudo usermod -aG cv3po www-data

echo "Creating CV-3PO runtime directory..."
sudo install -d -m 2770 -o "$CV3PO_USER" -g cv3po /var/lib/cv3po

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

echo
echo "Installer preflight OK."
