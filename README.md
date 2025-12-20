# trachhub 

raspberry pi based trachsense hub for monitoring respiratory health. 

## setup 

### first time setup 

you will need `git`, `python` >= 3.9, and `uv` installed.

1. **install system dependencies**:
   these are required to build numeric and bluetooth packages on 32-bit arm.
   ```bash 
   sudo apt-get update
   sudo apt-get install -y libatlas-base-dev libopenblas-dev libdbus-1-dev build-essential libffi-dev libssl-dev
   ```

2. **clone and sync**:
   ```bash
   git clone https://github.com/TrachSenseADC/trachhub.git 
   cd trachhub 
   uv sync
   ```

3. **database setup**:
   the `setup.sh` script handles the full installation of postgresql 13 and timescaledb. for a manual install, refer to the script logic.

### quick start (using setup script)

for a fully automated installation on a fresh pi:
```bash
curl -sSL https://raw.githubusercontent.com/TrachSenseADC/trachhub/main/setup.sh | bash
```

### running the app

if already configured, simply run:
```bash
cd trachhub
uv run app.py
```

to enable the internal virtual emulator for developer testing:
```bash
uv run app.py --debug
```

if you encounter issues with architecture compatibility on the pi, try a clean sync:
```bash
rm -rf .venv
uv sync --no-cache
```

## using the app

once the app runs, it will print the local server URL. open that in your browser.

1. **skip wifi**: you can choose to skip the wifi setup and move directly to trachsense connection.
2. **connect**: find "trachsense" in the list of bluetooth devices (use ctrl+f if needed). 
3. **data stream**: you might see a visual error message saying "failed to connect"—you can ignore this for now if values start printing in the terminal.
4. **visualization**: once connected, you will see live values and a real-time plot.

## data storage

readings are stored in `diff.csv`. if the server fails to write this file on a pi, you can use the `bt_check.py` script as a fallback to verify hardware communication.

to see a complete stationary graph of your recorded data:
```bash
uv run plot.py
```

if you still encounter issues, please let Yashas ([ybhat@umd.edu](mailto:ybhat@umd.edu)) know.