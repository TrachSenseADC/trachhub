#!/bin/bash
set -eo pipefail

# Friendly configuration for TrachHub installation
INSTALL_DIR="$HOME/TrachHub"
SCRIPTS_SOURCE="https://github.com/TrachSenseADC/trachhub.git"
LOG_FILE="$INSTALL_DIR/setup.log"

# Handle unexpected errors by cleaning up and logging
cleanup() {
  echo -e "\n❌ Something went wrong. Check $LOG_FILE or contact support."
  exit 1
}
trap cleanup ERR

# Display welcome message and setup instructions
echo "Welcome to TrachHub setup!"
echo "This will take 2-3 minutes. Please don't turn off your device."
echo "--------------------------------------------------------------"

# Redirect all output (stdout and stderr) to both console and log file
exec > >(tee "$LOG_FILE") 2>&1

# Verify internet connectivity before proceeding
echo -e "\nStep 1/7: Checking internet connection..."
if ! ping -c 1 google.com &> /dev/null; then
  echo -e "\n❌ No internet. Please connect to Wi-Fi and try again."
  exit 1
fi

# Create necessary directories for the installation
echo -e "\nStep 2/7: Setting up folders..."
mkdir -p "$INSTALL_DIR" || { echo "Could not create installation directory. Check permissions."; exit 1; }

# Install system dependencies and tools required for TrachHub
echo -e "\nStep 3/7: Installing required system tools..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip git

# Install PostgreSQL 13 and build TimescaleDB from source
echo -e "\nStep 4/7: Installing PostgreSQL 13 and TimescaleDB..."
# Install PostgreSQL 13 and development libraries
sudo apt-get install -y -qq postgresql-13 postgresql-server-dev-13 postgresql-client-13

# Install dependencies for building TimescaleDB
sudo apt-get install -y -qq build-essential cmake git libssl-dev

# Clone and build TimescaleDB 2.15.1
echo -e "\nBuilding TimescaleDB from source..."
cd /tmp
git clone https://github.com/timescale/timescaledb.git
cd timescaledb
git checkout 2.15.1
./bootstrap -DAPACHE_ONLY=0 -DPG_CONFIG=/usr/lib/postgresql/13/bin/pg_config
cd build && make
sudo make install

# Configure PostgreSQL for TimescaleDB
echo -e "\nConfiguring PostgreSQL for TimescaleDB..."
POSTGRES_CONF="/etc/postgresql/13/main/postgresql.conf"
if ! grep -q "shared_preload_libraries.*timescaledb" "$POSTGRES_CONF"; then
  sudo sed -i "/#shared_preload_libraries/s/#\(shared_preload_libraries = '\)/\1timescaledb,/" "$POSTGRES_CONF" || \
  echo "shared_preload_libraries = 'timescaledb'" | sudo tee -a "$POSTGRES_CONF"
fi

# Restart PostgreSQL to apply changes
sudo systemctl restart postgresql

# Configure PostgreSQL user and database
echo -e "\nSetting up PostgreSQL user and database..."
if sudo -u postgres psql -t -c "SELECT 1 FROM pg_roles WHERE rolname='trachuser'" | grep -q 1; then
  echo "Database user already exists, skipping creation"
else
  sudo -u postgres psql -c "CREATE USER trachuser WITH PASSWORD 'trachpassword';"
  sudo -u postgres psql -c "ALTER USER trachuser WITH SUPERUSER;"
  sudo -u postgres psql -c "CREATE DATABASE trachdb OWNER trachuser;"
  sudo -u postgres psql -d trachdb -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
fi

# Verify TimescaleDB installation
echo -e "\nVerifying TimescaleDB installation..."
sudo -u postgres psql -d trachdb -c "\dx" | grep -q timescaledb && echo "TimescaleDB extension successfully enabled" || \
  { echo "Failed to enable TimescaleDB extension"; exit 1; }

# Download or update TrachHub scripts from the remote repository
echo -e "\n⬇ Step 5/7: Downloading TrachHub scripts..."
if [ -d "$INSTALL_DIR/scripts/.git" ]; then
  git -C "$INSTALL_DIR/scripts" pull origin setup --quiet
else
  git clone --quiet -b setup "$SCRIPTS_SOURCE" "$INSTALL_DIR/scripts"
fi

# Prepare Python virtual environment and install dependencies
echo -e "\nStep 6/7: Preparing Python environment..."
python3 -m venv "$INSTALL_DIR/venv" || { echo "Failed to create Python virtual environment. See log."; exit 1; }
source "$INSTALL_DIR/venv/bin/activate"
response=$(curl -s https://raw.githubusercontent.com/TrachSenseADC/trachhub/refs/heads/setup/requirements.txt -o requirements.txt)
python3 -m pip install --no-cache-dir -r requirements.txt

# Launch TrachHub server in the background
echo -e "\n🚀 Step 7/7: Starting TrachHub server..."
cd "$INSTALL_DIR/scripts"
python3 app.py &

echo -e "\n✅ Setup complete! TrachHub is now running."
echo "--------------------------------------------------------------"
echo "To stop TrachHub, restart your device or contact support."