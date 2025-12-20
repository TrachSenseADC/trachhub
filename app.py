"""
TrachHub - Bluetooth and WiFi Management Server

This script sets up a Flask-based web server to manage Bluetooth and WiFi connections on a system.
It includes endpoints for scanning and connecting to available WiFi and Bluetooth devices, monitoring
connection statuses, and offering a health check API for general system status.

Main Components:
- Flask Server: Hosts the web interface and provides REST APIs for client interaction.
- Logging: Configures both file and console logging for debugging and status monitoring.
- BluetoothManager Class: Manages Bluetooth connections with retry logic to maintain a stable connection.
- Background Tasks: Runs periodic system and connection checks, intended primarily for non-Windows systems.
- Platform-Specific WiFi Handling: Supports WiFi scanning and connection on both Windows and Linux (Raspberry Pi).

Key Endpoints:
- `/api/wifi/scan` - Scans and returns available WiFi networks.
- `/api/wifi/connect` - Connects to a specified WiFi network.
- `/api/bluetooth/scan` - Scans for nearby Bluetooth devices.
- `/api/bluetooth/connect` - Connects to a specific Bluetooth device.
- `/api/status` - Returns the current connection statuses of WiFi and Bluetooth.
- `/health` - Provides a basic health check of system connectivity and uptime.

Modules:
- `BluetoothManager`: Contains methods for establishing and monitoring Bluetooth connections with reconnection logic.
- `get_wifi_networks`, `connect_wifi`: Functions for platform-specific WiFi network scanning and connection management.
- `start_background_tasks`: Initializes background monitoring for system health and connection stability.

"""

import json
from flask import Flask, render_template, jsonify, request

# Events db
from backend.src.events.events import events_bp


import struct
import subprocess
import threading
import time
import logging
from bleak import BleakClient, BleakScanner, BleakClient
import socket
import asyncio
import platform
import os
import signal
from datetime import datetime, timezone
import sys
from pathlib import Path
from services.ws import WebSocketServer
from backend.src.data_processing.analyzer import BreathingPatternAnalyzer
from hypercorn.asyncio import serve
from hypercorn.config import Config


from sqlalchemy.orm import Session
from backend.src.data_processing.edb import engine
from backend.src.models.events import Anomaly
from datetime import datetime, timezone
import uuid

from calibrate import calibrate
from CONSTANTS import A, B, C, GAS_READING
from plot import plot_live_co2
from logger import DataLoggerCSV

# Argument parsing for debug mode
import argparse
parser = argparse.ArgumentParser(description="TrachHub Server")
parser.add_argument("--debug", action="store_true", help="enable developer debug features (internal emulator)")
args, unknown = parser.parse_known_args()
DEBUG_MODE = args.debug

diff_logger = DataLoggerCSV(os.path.join(os.path.dirname(__file__), "diff.csv"))


BUFFER_ANALYZER = 100
BUFFER_STREAM = 1


batch_100 = []
chunk_50 = []
analyzer = BreathingPatternAnalyzer(
    buffer_size=BUFFER_ANALYZER, batch_size=BUFFER_ANALYZER
)

in_anomaly = False
anomaly_start = None
anomaly_end = None
current_state = "normal breathing"

home_usr = Path.home()
path_usr_log = os.path.join(home_usr, "trachhub.log")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        (
            logging.FileHandler(path_usr_log)
            if platform.system() != "Windows"
            else logging.FileHandler(path_usr_log)
        ),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)
background_loop = None

app = Flask(__name__)
app.register_blueprint(events_bp)


device_state = {
    "wifi_connected": False,
    "bluetooth_connected": False,
    "device_data": None,
    "connected_ssid": None,
    "last_bluetooth_connection": None,
    "reconnection_attempts": 0,
}


# helper to convert full bluetooth uuid to short 16-bit hex if possible
def convertUUIDtoShortID(uuid_str):
    if "-" in uuid_str:
        # check if it matches the bluetooth base uuid
        if uuid_str.lower().endswith("-0000-1000-8000-00805f9b34fb"):
            return uuid_str[4:8]
    return uuid_str

# helper to build the 26-byte trachsense config packet
def build_config_packet(duration=3600, alert_level=1):
    import struct
    packet = bytearray(26)
    packet[0] = 2 # mode
    
    # duration (bytes 1-4, uint32, little-endian)
    duration_bytes = struct.pack("<I", duration)
    packet[1:5] = duration_bytes
    
    # alert level (bytes 11-12, uint16, little-endian)
    alert_bytes = struct.pack("<H", alert_level)
    packet[11:13] = alert_bytes
    
    # cr lf (bytes 24-25)
    packet[24] = 13 # cr
    packet[25] = 10 # lf
    
    return packet

# helper to parse trachsense data packets
def parse_packet(data):
    if len(data) < 8:
        return None
    import struct
    # timestamp (4 bytes, little-endian uint32, divided by 100000.0)
    timestamp_raw = struct.unpack("<I", data[0:4])[0]
    timestamp_s = timestamp_raw / 100000.0
    
    # on/off values (swapped endian-ness in the protocol)
    on_val = data[5] + (data[4] << 8)
    off_val = data[7] + (data[6] << 8)
    diff = on_val - off_val
    
    return {
        "time": timestamp_s,
        "on": on_val,
        "off": off_val,
        "diff": diff
    }

class BluetoothManager:
    """
    Manages Bluetooth device connection and reconnection attempts with built-in
    persistence. The class maintains the connection state, initiates reconnection
    on disconnection, and handles connection monitoring.

    Attributes:
    - `client` (BleakClient): Active Bluetooth client instance.
    - `device_address` (str): Address of the Bluetooth device to connect.
    - `is_connected` (bool): Tracks connection status.
    - `reconnect_attempts` (int): Counter for reconnection attempts.
    - `max_reconnect_attempts` (int): Maximum attempts to reconnect.
    - `reconnect_delay` (int): Delay in seconds between reconnection attempts.
    - `_lock` (asyncio.Lock): Ensures safe async handling of connection state.
    - `last_data_time` (datetime): Timestamp of last received data from device.
    """

    def __init__(self):
        self.client = None
        self.device_address = None
        self.is_connected = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 2
        self._lock = asyncio.Lock()
        self.last_data_time = None

    async def connect(self, address):
        """
        Establishes a connection to the specified Bluetooth device. If a connection
        already exists, it disconnects and reconnects.

        Parameters:
        - `address` (str): Bluetooth address of the target device.

        Returns:
        - `bool`: True if connection was successful, False otherwise.
        """
        async with self._lock:
            try:
                if self.client and self.is_connected:
                    await self.client.disconnect()

                self.device_address = address
                
                if address == "EMULATOR" and DEBUG_MODE:
                    logger.info("routing connection to internal emulator...")
                    self.is_connected = True
                    device_state["bluetooth_connected"] = True
                    asyncio.create_task(self.run_mock_stream())
                    return True

                self.client = BleakClient(
                    address, disconnected_callback=self.handle_disconnect
                )
                await self.client.connect()
                
                services = self.client.services
                chars_by_short = {}
                for service in services:
                    for char in service.characteristics:
                        short_id = convertUUIDtoShortID(char.uuid)
                        chars_by_short[short_id] = char
                        logger.info(f"discovered: {short_id} ({char.uuid})")

                # trachsense protocol sequence
                # fff4: stream, fff3: config, fff1: command
                stream_char = chars_by_short.get("fff4")
                config_char = chars_by_short.get("fff3")
                cmd_char    = chars_by_short.get("fff1")

                if stream_char:
                    logger.info(f"subscribing to {stream_char.uuid}")
                    await self.client.start_notify(stream_char.uuid, self.notification_handler)
                    
                    # If we got here, the core connection/subscription is active
                    # Handshake steps (config/start) are important but we allow minor failures
                    try:
                        if config_char:
                            logger.info(f"sending config to {config_char.uuid}")
                            packet = build_config_packet()
                            await self.client.write_gatt_char(config_char.uuid, packet, response=True)
                        
                        if cmd_char:
                            logger.info(f"sending start command 'S' to {cmd_char.uuid}")
                            await self.client.write_gatt_char(cmd_char.uuid, b"S", response=True)
                    except Exception as gatt_err:
                        logger.warning(f"GATT handshake warning (non-fatal): {gatt_err}")

                logger.info("bluetooth connection sequence finished.")
                
                # Only set connected state AFTER everything succeeds
                self.is_connected = True
                self.reconnect_attempts = 0
                self.last_data_time = datetime.now()
                device_state["bluetooth_connected"] = True
                device_state["last_bluetooth_connection"] = datetime.now().isoformat()
                logger.info(f"Connected to device: {address}")
                
                # Broadcast connection status to WebSocket clients
                asyncio.create_task(websocket_server.broadcast_data({
                    "type": "bluetooth_status",
                    "bluetooth_connected": True,
                    "device_address": address,
                    "timestamp": datetime.now().isoformat()
                }))

                asyncio.create_task(self.monitor_connection())
                return True
            except Exception as e:
                logger.error(f"Failed to connect: {e}")
                # Ensure state is reset on failure
                self.is_connected = False
                device_state["bluetooth_connected"] = False
                return False

    def notification_handler(self, sender, data):
        """ble notification -> parse 8-byte packet -> store diff value."""

        global batch_100, chunk_50
        global in_anomaly, anomaly_start, anomaly_end, current_state
        try:
            parsed = parse_packet(data)
            if not parsed:
                # ignore short or invalid packets
                return
            
            # using calculated 'diff' for breathing patterns
            value = parsed["diff"]
            calibrated_co2 = calibrate(A, B, C, value, GAS_READING)
            logger.info(f"diff: {value} | calculated: {calibrated_co2}")
            
            # data logging (raw/diff)
            if diff_logger:
                try:
                    diff_logger.log({
                        "time": parsed["time"],
                        "on": parsed["on"],
                        "off": parsed["off"],
                        "diff": parsed["diff"]
                    })
                except Exception as e:
                    logger.error(f"logging error: {e}")
            
            # live plotting (calibrated)
            try:
                plot_live_co2(calibrated_co2)
            except Exception as e:
                logger.error(f"plotting error: {e}")
            
            now = datetime.now(tz=timezone.utc)

            batch_100.append(value)
            if len(batch_100) == BUFFER_ANALYZER:
                analyzer.update_data(batch_100)
                current_state = analyzer.detect_pattern()
                batch_100.clear()

                global in_anomaly, anomaly_start, anomaly_end
                if current_state != "normal breathing":
                    if not in_anomaly:  # anomaly just started
                        in_anomaly = True
                        anomaly_start = now
                        anomaly_end = None
                        print(f"anomaly started: {current_state}")

                else:  # back to normal
                    if in_anomaly:  # anomaly ends here
                        in_anomaly = False
                        anomaly_end = now
                        duration = (anomaly_end - anomaly_start).total_seconds()

                        # severity assessment based on duration
                        severity = (
                            "high"
                            if duration > 30
                            else "medium" if duration > 10 else "low"
                        )

                        print(f"anomaly ended: {duration:.2f} s (sev={severity})")
                        print("logging anomaly to events db")

                        # log anomaly to the database
                        with Session(engine) as session:
                            anomaly = Anomaly(
                                uuid=str(uuid.uuid4()),
                                title=current_state.lower(),
                                start_time=anomaly_start,
                                end_time=anomaly_end,
                                note="auto-logged via ble stream",
                                duration=duration,
                                severity=severity,
                            )
                            session.add(anomaly)
                            print(f"adding {anomaly.to_dict()}")
                            session.commit()

            chunk_50.append(value)
            if len(chunk_50) == BUFFER_STREAM:
                payload = {
                    "type": "sensor_chunk",
                    "timestamp": now.isoformat(),
                    "values": chunk_50.copy(),
                    "bluetooth_connected": bluetooth_manager.is_connected,
                }
                # attach anomaly field while episode is active
                if in_anomaly:
                    payload["anomaly"]      = {"start": anomaly_start.isoformat()}
                    payload["anomaly_type"] = current_state

                if anomaly_end is not None:
                    payload["anomaly"] = {
                        "start": anomaly_start.isoformat(),
                        "end":   anomaly_end.isoformat(),
                    }

                    anomaly_start = None
                    anomaly_end = None

                # broadcast to all connected websocket clients
                asyncio.get_running_loop().create_task(
                    websocket_server.broadcast_data(payload)
                )

                chunk_50.clear()  # ready for next chunk

            device_state["device_data"] = value
            self.last_data_time = datetime.now()

        except Exception as e:
            logger.error(f"error in notification handler: {e}")

    def handle_disconnect(self, client):
        """handler for unexpected ble disconnections. attempts to send stop command 'E'."""
        logger.warning("device disconnected, attempting to reconnect...")
        
        # try to send stop command 'E' if the logic allows
        try:
            for service in client.services:
                for char in service.characteristics:
                    if convertUUIDtoShortID(char.uuid) == "fff1":
                        # this is a best-effort attempt on disconnect
                        asyncio.get_running_loop().create_task(
                            client.write_gatt_char(char.uuid, b"E", response=True)
                        )
                        break
        except:
            pass

        self.is_connected = False
        device_state["bluetooth_connected"] = False
        
        # Broadcast disconnection status to WebSocket clients
        try:
            asyncio.create_task(websocket_server.broadcast_data({
                "type": "bluetooth_status",
                "bluetooth_connected": False,
                "timestamp": datetime.now().isoformat()
            }))
        except Exception as e:
            logger.error(f"Failed to broadcast disconnect status: {e}")
        
        # close session logger
        global diff_logger
        if diff_logger:
            try:
                diff_logger.close()
                logger.info("session logger closed.")
            except Exception as e:
                logger.error(f"error closing logger: {e}")
        
        if not self._lock.locked():
            asyncio.create_task(self.attempt_reconnect())


    async def run_mock_stream(self):
        """simulates the data stream from a trachsense device."""
        logger.info("VIRTUAL EMULATOR: starting data stream")
        from trachsense_emulator import TrachSenseEmulator
        emulator = TrachSenseEmulator()
        
        try:
            while self.is_connected and self.device_address == "EMULATOR":
                packet, on, off, diff = emulator.generate_packet()
                self.notification_handler(None, packet)
                await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"VIRTUAL EMULATOR error: {e}")
        finally:
            logger.info("VIRTUAL EMULATOR: stop streaming")

    async def attempt_reconnect(self):
        """
        Tries to reconnect to the Bluetooth device. Continues to retry until either
        the maximum number of attempts is reached or the connection is re-established.
        """
        while (
            not self.is_connected
            and self.reconnect_attempts < self.max_reconnect_attempts
        ):
            try:
                self.reconnect_attempts += 1
                device_state["reconnection_attempts"] = self.reconnect_attempts
                logger.info(f"Reconnection attempt {self.reconnect_attempts}")

                await self.connect(self.device_address)
                if self.is_connected:
                    logger.info("Successfully reconnected")
                    break
            except Exception as e:
                logger.error(f"Reconnection failed: {e}")
                await asyncio.sleep(self.reconnect_delay)

    async def monitor_connection(self):
        """
        Continuously monitors the Bluetooth connection status. If the connection fails,
        triggers reconnection logic.
        """
        while True:
            if self.is_connected and self.client:
                try:
                    # ping the device to check connection
                    services = self.client.services
                    self.last_data_time = datetime.now()
                except Exception as e:
                    logger.error(f"Connection check failed: {e}")
                    self.is_connected = False
                    device_state["bluetooth_connected"] = False
                    await self.attempt_reconnect()
            await asyncio.sleep(5)


bluetooth_manager = BluetoothManager()

websocket_server = WebSocketServer(log=logger, ble_manager=bluetooth_manager)


def get_wifi_networks():
    """
    Scans and retrieves a list of available WiFi networks on the system. Uses platform-specific commands
    for network scanning, supporting both Windows and Linux (primarily for Raspberry Pi).

    Returns:
    - `list`: A list of unique SSIDs (network names) for detected WiFi networks.

    Errors encountered during the scan are logged and an empty list is returned if any issues arise.
    """
    try:
        if platform.system() == "Windows":
            networks = []
            output = subprocess.check_output(
                ["netsh", "wlan", "show", "networks"],
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            # parse SSID names from the command output
            for line in output.split("\n"):
                if "SSID" in line and "BSSID" not in line:
                    ssid = line.split(":")[1].strip()
                    if ssid:
                        networks.append(ssid)
            return list(set(networks))
        else:
            # for TrachHub RPI WiFi scanning
            output = subprocess.check_output(["sudo", "iwlist", "wlan0", "scan"])
            networks = []
            for line in output.decode("utf-8").split("\n"):
                if "ESSID:" in line:
                    ssid = line.split('ESSID:"')[1].split('"')[0]
                    if ssid:
                        networks.append(ssid)
            return list(set(networks))
    except Exception as e:
        logger.error(f"Error scanning WiFi: {e}")
        return []


def connect_wifi(ssid, password):
    """
    Connects to a specified WiFi network using SSID and password. Handles platform-specific WiFi
    connection commands for both Windows and Linux (Raspberry Pi).

    Parameters:
    - `ssid` (str): Name of the WiFi network to connect.
    - `password` (str): Password for the WiFi network.

    Returns:
    - `bool`: True if connection was successful, False otherwise.

    Errors are logged, and connection state is updated in `device_state`.
    """
    try:
        if platform.system() == "Windows":
            # Build the Windows WiFi profile XML
            profile = f"""<?xml version="1.0"?>
            <WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
                <name>{ssid}</name>
                <SSIDConfig>
                    <SSID>
                        <name>{ssid}</name>
                    </SSID>
                </SSIDConfig>
                <connectionType>ESS</connectionType>
                <connectionMode>auto</connectionMode>
                <MSM>
                    <security>
                        <authEncryption>
                            <authentication>WPA2PSK</authentication>
                            <encryption>AES</encryption>
                            <useOneX>false</useOneX>
                        </authEncryption>
                        <sharedKey>
                            <keyType>passPhrase</keyType>
                            <protected>false</protected>
                            <keyMaterial>{password}</keyMaterial>
                        </sharedKey>
                    </security>
                </MSM>
            </WLANProfile>"""

            profile_path = f"{ssid}_profile.xml"

            # Write profile to file, add it, connect, and remove the temporary file
            with open(profile_path, "w") as f:
                f.write(profile)

            subprocess.run(
                ["netsh", "wlan", "add", "profile", f'filename="{profile_path}"'],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            subprocess.run(
                ["netsh", "wlan", "connect", f"name={ssid}"],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            os.remove(profile_path)
        else:
            # Linux/Raspberry Pi WiFi connection configuration
            config = (
                f"network={{\n"
                f'    ssid="{ssid}"\n'
                f'    psk="{password}"\n'
                f"    key_mgmt=WPA-PSK\n"
                f"}}\n"
            )

            with open("/etc/wpa_supplicant/wpa_supplicant.conf", "a") as f:
                f.write(config)

            subprocess.run(["sudo", "wpa_cli", "reconfigure"])
            subprocess.run(["sudo", "systemctl", "restart", "networking"])

        # Update connection state
        device_state["wifi_connected"] = True
        device_state["connected_ssid"] = ssid
        return True
    except Exception as e:
        logger.error(f"Error connecting to WiFi: {e}")
        return False


def run_bluetooth_scan():
    """Run Bluetooth scan in a separate event loop"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        devices = loop.run_until_complete(BleakScanner.discover())
        results = [
            {
                "name": dev.name or "Unknown Device",
                "address": dev.address,
            }
            for dev in devices
        ]
        # inject emulator for easy testing only in debug mode
        if DEBUG_MODE:
            results.insert(0, {
                "name": "TrachSense Emulator (VIRTUAL)",
                "address": "EMULATOR",
            })
        return results
    except Exception as e:
        logger.error(f"Error scanning Bluetooth: {e}")
        return []
    finally:
        loop.close()


@app.route("/api/bluetooth/scan")
def bluetooth_scan():
    devices = run_bluetooth_scan()
    return jsonify({"devices": devices})


async def connect_bluetooth_device(address):
    """
    Initiates connection to a Bluetooth device by address, using the `BluetoothManager` for connection
    handling and persistence.

    Parameters:
    - `address` (str): Bluetooth MAC address of the target device.

    Returns:
    - `bool`: True if connection was successful, False otherwise.

    Connection status is updated in `device_state`, and errors are logged if connection fails.
    """
    try:
        success = await bluetooth_manager.connect(address)
        device_state["bluetooth_connected"] = success
        return success
    except Exception as e:
        logger.error(f"Error connecting to Bluetooth device: {e}")
        return False


def start_background_tasks(loop):
    """
    Launches background asynchronous tasks to continuously monitor system and connection status.

    Parameters:
    - `loop` (asyncio.AbstractEventLoop): The event loop to run tasks on
    """

    async def monitor_system():
        while True:
            if device_state["bluetooth_connected"] and bluetooth_manager.client:
                try:
                    # Periodic check every 5 seconds if connected
                    await asyncio.sleep(5)
                except Exception as e:
                    logger.error(f"Error in monitoring: {e}")
            await asyncio.sleep(1)

    loop.create_task(monitor_system())


def run_background_loop(loop):
    """
    Runs the event loop in a separate thread.

    Parameters:
    - `loop` (asyncio.AbstractEventLoop): The event loop to run
    """
    asyncio.set_event_loop(loop)
    loop.run_forever()


# Routes with async support
@app.route("/")
def index():
    """
    Renders the main index page for the web interface. This serves as the front-facing HTML template for the application,
    intended as a landing page or basic interface.

    Returns:
    - Rendered HTML template `index.html`.
    """
    return render_template("index.html")


@app.route("/api/wifi/scan")
def wifi_scan():
    """
    API endpoint to scan for available WiFi networks. Invokes `get_wifi_networks` to retrieve the list of SSIDs.

    Returns:
    - JSON response with the list of available WiFi networks (`{'networks': [...]}`)
    """
    networks = get_wifi_networks()
    return jsonify({"networks": networks})


@app.route("/api/wifi/connect", methods=["POST"])
def wifi_connect_route():
    """
    API endpoint to connect to a specified WiFi network. Expects a JSON payload containing `ssid` and `password` keys.

    Returns:
    - JSON response indicating connection success or failure (`{'success': True/False}`)
    """
    data = request.get_json()
    success = connect_wifi(data["ssid"], data["password"])
    return jsonify({"success": success})


@app.route("/api/bluetooth/connect", methods=["POST"])
def bluetooth_connect():
    data = request.get_json()
    # Schedule the coroutine on the background loop and get the result
    future = asyncio.run_coroutine_threadsafe(
        connect_bluetooth_device(data["address"]), background_loop
    )
    success = future.result()
    return jsonify({"success": success})


@app.route("/api/status")
def get_status():
    """
    API endpoint to retrieve the current status of WiFi and Bluetooth connections. Calls `get_current_wifi` for WiFi details
    and `bluetooth_manager` attributes for Bluetooth status.

    Returns:
    - JSON object with WiFi, Bluetooth, and system time status.
    """
    current_ssid = get_current_wifi()
    status = {
        **device_state,
        "current_wifi": current_ssid,
        "system_time": datetime.now().isoformat(),
        "bluetooth_manager_status": {
            "connected": bluetooth_manager.is_connected if bluetooth_manager else False,
            "last_data_time": (
                bluetooth_manager.last_data_time.isoformat()
                if bluetooth_manager and bluetooth_manager.last_data_time
                else None
            ),
            "reconnection_attempts": (
                bluetooth_manager.reconnect_attempts if bluetooth_manager else 0
            ),
        },
    }
    return jsonify(status)


@app.route("/api/data")
def get_data():
    """
    API endpoint to retrieve data from the connected Bluetooth device. If the device is not connected,
    returns an error response.

    Returns:
    - JSON response with data from Bluetooth device or an error message if not connected (`{'data': [...]}` or `{'error': ...}`)
    """
    if not bluetooth_manager or not bluetooth_manager.is_connected:
        return jsonify(
            {
                "data": [],
                "error": "Device not connected",
                "last_connection": device_state.get("last_bluetooth_connection"),
            }
        )

    # Return the last value received via notification
    value = device_state.get("device_data")
    if value is not None:
        return jsonify({"data": [value]})
    else:
        return jsonify(
            {
                "data": [],
                "error": "No data received yet",
                "last_connection": device_state.get("last_bluetooth_connection"),
            }
        )


def get_current_wifi():
    """
    Retrieves the SSID of the currently connected WiFi network on the system. Uses platform-specific commands to obtain
    the network name.

    Returns:
    - `str`: SSID of the currently connected WiFi network, or `None` if not connected.
    """
    try:
        if platform.system() == "Windows":
            output = subprocess.check_output(
                ["netsh", "wlan", "show", "interfaces"],
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for line in output.split("\n"):
                if "SSID" in line and "BSSID" not in line:
                    ssid = line.split(":")[1].strip()
                    if ssid:
                        return ssid
        else:  # for Linux/Raspberry Pi
            try:
                output = subprocess.check_output(["iwgetid", "-r"], text=True)
                return output.strip()
            except subprocess.CalledProcessError:
                try:
                    output = subprocess.check_output(["iwconfig", "wlan0"], text=True)
                    for line in output.split("\n"):
                        if "ESSID:" in line:
                            ssid = line.split('ESSID:"')[1].split('"')[0]
                            if ssid:
                                return ssid
                except:
                    pass
    except Exception as e:
        logger.error(f"Error getting current WiFi: {e}")
    return None


@app.route("/api/wifi/current")
def get_wifi_status():
    """
    API endpoint to check the current WiFi connection status. Calls `get_current_wifi` to determine the connected SSID.

    Returns:
    - JSON response with connection status, SSID, and current timestamp.
    """
    current_ssid = get_current_wifi()
    connected = bool(current_ssid)
    device_state["wifi_connected"] = connected
    device_state["connected_ssid"] = current_ssid if connected else None
    return jsonify(
        {
            "connected": connected,
            "ssid": current_ssid,
            "timestamp": datetime.now().isoformat(),
        }
    )


@app.route("/health")
def health_check():
    """
    System health check endpoint. Provides a basic report on system connectivity status for WiFi and Bluetooth,
    including system uptime.

    Returns:
    - JSON object with system health details: WiFi status, Bluetooth status, and uptime.
    """
    return jsonify(
        {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "wifi": {
                "connected": device_state["wifi_connected"],
                "ssid": device_state["connected_ssid"],
            },
            "bluetooth": {
                "connected": (
                    bluetooth_manager.is_connected if bluetooth_manager else False
                ),
                "last_data_time": (
                    bluetooth_manager.last_data_time.isoformat()
                    if bluetooth_manager and bluetooth_manager.last_data_time
                    else None
                ),
                "reconnection_attempts": (
                    bluetooth_manager.reconnect_attempts if bluetooth_manager else 0
                ),
            },
            "uptime": time.time() - start_time,
        }
    )


@app.route("/api/events/add-anomaly")
def create_anomlay():
    data = request.json()


start_time = time.time()


async def run_servers():

    loop = asyncio.get_event_loop()
    global background_loop
    background_loop = loop
    # Create a task for the WebSocket server
    ws_task = asyncio.create_task(websocket_server.start())

    # Configure and run Hypercorn (Flask) server
    config = Config()
    config.bind = ["127.0.0.1:5000"]
    config.worker_class = "asyncio"

    flask_task = asyncio.create_task(serve(app, config))

    # Also run the background monitoring
    start_background_tasks(asyncio.get_event_loop())

    # Wait for both servers to run (they won't complete normally)
    await asyncio.gather(ws_task, flask_task)


if __name__ == "__main__":
    try:

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 1))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            local_ip = "127.0.0.1"

        if platform.system() != "Windows":
            try:
                subprocess.run(["sudo", "setterm", "-blank", "5", "-powerdown", "5"])
                subprocess.run(["sudo", "systemctl", "disable", "apt-daily.service"])
                subprocess.run(["sudo", "systemctl", "disable", "apt-daily.timer"])
            except Exception as e:
                logger.warning(f"Failed to configure system settings: {e}")

        print("TrachHub Server running at http://127.0.0.1:5000")
        print("WebSocket server running at ws://127.0.0.1:8765")

        # Set up logging
        werkzeug_logger = logging.getLogger("werkzeug")
        werkzeug_logger.setLevel(logging.ERROR)

        # Run both servers
        asyncio.run(run_servers())

    except Exception as e:
        logger.error(f"Critical server error: {e}")
        # Attempt to restart
        while True:
            time.sleep(60)
            logger.info("Server restart attempted...")
            try:
                asyncio.run(run_servers())
            except:
                continue
