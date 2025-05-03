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

# Install PostgreSQL
sudo apt install -y postgresql postgresql-contrib

# Install build dependencies
sudo apt install -y \
    build-essential \
    cmake \
    libssl-dev \
    libpq-dev \
    postgresql-server-dev-all

# Build TimescaleDB from source
TS_VERSION="2.19.3"
git clone https://github.com/timescale/timescaledb.git
cd timescaledb
git checkout $TS_VERSION
./bootstrap
cd build && make
sudo make install
cd ~

# Configure PostgreSQL
echo -e "\nConfiguring PostgreSQL port and settings..."
sudo sed -i "s/#listen_addresses = 'localhost'/listen_addresses = '*'/" /etc/postgresql/*/main/postgresql.conf
sudo sed -i "s/#port = 5432/port = 5432/" /etc/postgresql/*/main/postgresql.conf  # Change 5432 to your desired port
sudo sed -i "s/#shared_preload_libraries = ''/shared_preload_libraries = 'timescaledb'/" /etc/postgresql/*/main/postgresql.conf

# Raspberry Pi-specific optimizations
echo "
# Raspberry Pi optimizations
random_page_cost = 1.1
effective_io_concurrency = 2
max_worker_processes = 2
max_parallel_workers_per_gather = 1
timescaledb.max_background_workers = 2
" | sudo tee -a /etc/postgresql/*/main/postgresql.conf

# Update pg_hba.conf to allow connections
echo "
# Allow connections from all IPs, might have to adjust this later for security
host all all 0.0.0.0/0 md5
" | sudo tee -a /etc/postgresql/*/main/pg_hba.conf

# Restart PostgreSQL
sudo service postgresql restart

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