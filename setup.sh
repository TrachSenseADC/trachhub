#!/bin/bash
set -eo pipefail

# path for trachhub installation
PROJECT_DIR="$HOME/trachhub"
REPO_URL="https://github.com/TrachSenseADC/trachhub.git"
LOG_FILE="$HOME/trachhub_setup.log"

# clean up on errors
cleanup() {
  echo -e "\nerror occurred. check $LOG_FILE for details."
  exit 1
}
trap cleanup ERR

echo "starting trachhub setup"
echo "--------------------------------------------------------------"

# redirect output to console and log
exec > >(tee "$LOG_FILE") 2>&1

echo "step 1/5: installing system tools and headers"
sudo apt-get update -qq
sudo apt-get install -y -qq curl python3 python3-pip git libatlas-base-dev libopenblas-dev libdbus-1-dev build-essential libffi-dev libssl-dev

echo "step 2/5: installing uv"
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

echo "step 3/5: setting up database (postgresql 13 + timescaledb)"
sudo apt-get install -y -qq postgresql-13 postgresql-server-dev-13 postgresql-client-13
# build timescaledb from source
cd /tmp
rm -rf timescaledb
git clone https://github.com/timescale/timescaledb.git
cd timescaledb
git checkout 2.15.1
./bootstrap -DAPACHE_ONLY=0 -DPG_CONFIG=/usr/lib/postgresql/13/bin/pg_config
cd build && make
sudo make install

# configure postgres
POSTGRES_CONF="/etc/postgresql/13/main/postgresql.conf"
if ! grep -q "shared_preload_libraries.*timescaledb" "$POSTGRES_CONF"; then
  sudo sed -i "/#shared_preload_libraries/s/#\(shared_preload_libraries = '\)/\1timescaledb,/" "$POSTGRES_CONF" || \
  echo "shared_preload_libraries = 'timescaledb'" | sudo tee -a "$POSTGRES_CONF"
fi
sudo systemctl restart postgresql

# setup user and db
if ! sudo -u postgres psql -t -c "SELECT 1 FROM pg_roles WHERE rolname='trachuser'" | grep -q 1; then
  sudo -u postgres psql -c "CREATE USER trachuser WITH PASSWORD 'trachpassword';"
  sudo -u postgres psql -c "ALTER USER trachuser WITH SUPERUSER;"
  sudo -u postgres psql -c "CREATE DATABASE trachdb OWNER trachuser;"
  sudo -u postgres psql -d trachdb -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
fi

echo "step 4/5: downloading project code"
if [ -d "$PROJECT_DIR/.git" ]; then
  git -C "$PROJECT_DIR" pull origin main --quiet
else
  git clone --quiet "$REPO_URL" "$PROJECT_DIR"
fi

echo "step 5/5: syncing python environment"
cd "$PROJECT_DIR"
# uv creates the virtual environment (.venv) automatically here
uv sync --no-cache

echo "setup complete. starting server."
echo "--------------------------------------------------------------"
# uv run uses the automatically created environment
uv run app.py &