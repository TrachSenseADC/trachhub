#!/bin/bash
set -eo pipefail



# friendly configuration for trachub installation
INSTALL_DIR="$HOME/TrachHub"
SCRIPTS_SOURCE="https://github.com/TrachSenseADC/trachhub.git"
LOG_FILE="$INSTALL_DIR/setup.log"

# handle unexpected errors by cleaning up and logging
cleanup() {
  echo -e "\n❌ something went wrong. check $LOG_FILE or contact support."
  exit 1
}
trap cleanup ERR

# display welcome message and setup instructions
echo "welcome to trachub setup!"
echo "this will take 2-3 minutes. please don't turn off your device."
echo "--------------------------------------------------------------"

# redirect all output (stdout and stderr) to both console and log file
exec > >(tee "$LOG_FILE") 2>&1 # *1

# verify internet connectivity before proceeding
echo -e "\nstep 1/6: checking internet connection..."
if ! ping -c 1 google.com &> /dev/null; then
  echo -e "\n❌ no internet. please connect to wi-fi and try again."
  exit 1
fi

# create necessary directories for the installation
echo -e "\nstep 2/6: setting up folders..."
mkdir -p "$INSTALL_DIR" || { echo "could not create installation directory. check permissions."; exit 1; }

# install system dependencies and tools required for trachub
echo -e "\nstep 3/6: installing required system tools..."
sudo apt-get update -qq # *1
sudo apt-get install -y -qq python3 python3-pip git # *1


# install PostgreSQL and TimescaleDB
echo -e "\nStep 4/7: Installing PostgreSQL and TimescaleDB..."
# Run PostgreSQL setup script
sudo apt install gnupg postgresql-common apt-transport-https lsb-release wget
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y

# Install PostgreSQL development libraries
sudo apt-get install -y postgresql-server-dev-17

# Add TimescaleDB repository
echo "deb https://packagecloud.io/timescale/timescaledb/$(lsb_release -is | tr '[:upper:]' '[:lower:]')/ $(lsb_release -cs) main" | \
  sudo tee /etc/apt/sources.list.d/timescaledb.list

# Install TimescaleDB GPG key
if [ "$(lsb_release -rs)" \> "21.10" ]; then
  wget --quiet -O - https://packagecloud.io/timescale/timescaledb/gpgkey | sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/timescaledb.gpg
else
  wget --quiet -O - https://packagecloud.io/timescale/timescaledb/gpgkey | sudo apt-key add -
fi

# Update repository list
sudo apt update -qq

# Install TimescaleDB
sudo apt install -y timescaledb-2-postgresql-17 postgresql-client-17

# Tune PostgreSQL for TimescaleDB
echo -e "\nTuning PostgreSQL for TimescaleDB..."
sudo timescaledb-tune --quiet --yes

# Restart PostgreSQL
sudo systemctl restart postgresql

# Configure PostgreSQL password (non-interactive)
echo -e "\nConfiguring PostgreSQL user..."
if sudo -u postgres psql -t -c "SELECT 1 FROM pg_roles WHERE rolname='trachuser'" | grep -q 1; then
  echo "Database user already exists, skipping creation"
else
  sudo -u postgres psql -c "CREATE USER trachuser WITH PASSWORD 'trachpassword';"
  sudo -u postgres psql -c "ALTER USER trachuser WITH SUPERUSER;"
  sudo -u postgres psql -c "CREATE DATABASE trachdb OWNER trachuser;"
  sudo -u postgres psql -d trachdb -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
fi


# download or update trachub scripts from the remote repository
echo -e "\n⬇step 4/6: downloading trachub scripts..."
if [ -d "$INSTALL_DIR/scripts/.git" ]; then
  git -C "$INSTALL_DIR/scripts" pull origin setup --quiet
else
  git clone --quiet -b setup "$SCRIPTS_SOURCE" "$INSTALL_DIR/scripts"
fi

# prepare python virtual environment and install dependencies
echo -e "\nstep 5/6: preparing python environment..."
python3 -m venv "$INSTALL_DIR/venv" || { echo "failed to create python virtual environment. see log."; exit 1; }
source "$INSTALL_DIR/venv/bin/activate"
response=$(curl -s https://raw.githubusercontent.com/TrachSenseADC/trachhub/refs/heads/setup/requirements.txt -o requirements.txt)
python3 -m pip install --no-cache-dir -r requirements.txt

# launch trachub server in the background
echo -e "\n🚀 step 6/6: starting trachub server..."
cd "$INSTALL_DIR/scripts"
python3 app.py & # (moh's script, connects board to hub) start server script for bluetooth connection and data streaming

echo -e "\n✅ setup complete! trachub is now running."
echo "--------------------------------------------------------------"
echo "to stop trachub, restart your device or contact support."