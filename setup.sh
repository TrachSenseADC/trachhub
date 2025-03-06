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
echo -e "\n🔍 step 1/6: checking internet connection..."
if ! ping -c 1 google.com &> /dev/null; then
  echo -e "\n❌ no internet. please connect to wi-fi and try again."
  exit 1
fi

# create necessary directories for the installation
echo -e "\n📁 step 2/6: setting up folders..."
mkdir -p "$INSTALL_DIR" || { echo "could not create installation directory. check permissions."; exit 1; }

# install system dependencies and tools required for trachub
echo -e "\n🛠️ step 3/6: installing required system tools..."
sudo apt-get update -qq # *1
sudo apt-get install -y -qq python3 python3-pip git # *1

# download or update trachub scripts from the remote repository
echo -e "\n⬇️ step 4/6: downloading trachub scripts..."
if [ -d "$INSTALL_DIR/scripts/.git" ]; then
  git -C "$INSTALL_DIR/scripts" pull --quiet
else
  git clone --quiet "$SCRIPTS_SOURCE" "$INSTALL_DIR/scripts"
fi

# prepare python virtual environment and install dependencies
echo -e "\n🐍 step 5/6: preparing python environment..."
python3 -m venv "$INSTALL_DIR/venv" || { echo "failed to create python virtual environment. see log."; exit 1; }
source "$INSTALL_DIR/venv/bin/activate"
response=$(curl -s https://raw.githubusercontent.com/TrachSenseADC/trachhub/refs/heads/setup/requirements.txt -o requirements.txt)
pip install --no-cache-dir -q -r requirements.txt

# launch trachub server in the background
echo -e "\n🚀 step 6/6: starting trachub server..."
cd "$INSTALL_DIR/scripts"
python3 app.py & # (moh's script, connects board to hub) start server script for bluetooth connection and data streaming

echo -e "\n✅ setup complete! trachub is now running."
echo "--------------------------------------------------------------"
echo "to stop trachub, restart your device or contact support."