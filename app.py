                                    
                                                                                                                     
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

from flask import Flask, render_template, jsonify, request
import struct
import subprocess
import threading
import time
import logging
from bleak import BleakScanner, BleakClient
import socket
import asyncio
import platform
import os
import signal
from datetime import datetime
import sys
from pathlib import Path

home_usr = Path.home()
path_usr_log = os.path.join(home_usr, 'trachhub.log')

print(path_usr_log)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(path_usr_log) if platform.system() != "Windows" else logging.FileHandler(path_usr_log),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
background_loop = None

app = Flask(__name__)

# signal.signal(signal.SIGINT, lambda x, y: None)

device_state = {
    'wifi_connected': False,
    'bluetooth_connected': False,
    'device_data': None,
    'connected_ssid': None,
    'last_bluetooth_connection': None,
    'reconnection_attempts': 0
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
                self.client = BleakClient(address, disconnected_callback=self.handle_disconnect)
                await self.client.connect()
                self.is_connected = True
                self.reconnect_attempts = 0
                self.last_data_time = datetime.now()
                device_state['bluetooth_connected'] = True
                device_state['last_bluetooth_connection'] = datetime.now().isoformat()
                logger.info(f"Connected to device: {address}")

                # Start notification on the characteristic
                characteristic = "00002a1f-0000-1000-8000-00805f9b34fb"
                await self.client.start_notify(characteristic, self.notification_handler)
                logger.info("Started notification on characteristic.")

                asyncio.create_task(self.monitor_connection())
                return True
            except Exception as e:
                logger.error(f"Failed to connect: {e}")
                return False
    
    def notification_handler(self, sender, data):
        try:
            value = struct.unpack('<B', data)[0]
            # logger.info(f"Notification received from TrachSense: {value}")
            device_state['device_data'] = value
            self.last_data_time = datetime.now()
            asyncio.create_task(websocket_server.broadcast_data(value))
        except Exception as e:
            logger.error(f"Error in notification handler: {e}")

    def handle_disconnect(self, client):
        """
        Callback method triggered on Bluetooth disconnection. Updates the connection 
        status and initiates a reconnection attempt.
        """
        logger.warning("Device disconnected, attempting to reconnect...")
        self.is_connected = False
        device_state['bluetooth_connected'] = False
        if not self._lock.locked():
            asyncio.create_task(self.attempt_reconnect())

    async def attempt_reconnect(self):
        """
        Tries to reconnect to the Bluetooth device. Continues to retry until either 
        the maximum number of attempts is reached or the connection is re-established.
        """
        while not self.is_connected and self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                self.reconnect_attempts += 1
                device_state['reconnection_attempts'] = self.reconnect_attempts
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
                    services = await self.client.get_services()
                    self.last_data_time = datetime.now()
                except Exception as e:
                    logger.error(f"Connection check failed: {e}")
                    self.is_connected = False
                    device_state['bluetooth_connected'] = False
                    await self.attempt_reconnect()
            await asyncio.sleep(5)

bluetooth_manager = BluetoothManager()

import asyncio
import websockets
import json
import os
from dotenv import load_dotenv
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.abspath(__file__), "../../../../")))

from backend.src.db import Database
from backend.src.data_processing.analyzer import BreathingPatternAnalyzer
from app import device_state, bluetooth_manager

load_dotenv()
import websockets
from functools import partial

# Add this class definition somewhere before your Flask routes
class WebSocketServer:
    def __init__(self):
        self.connected_clients = set()
        self.loop = asyncio.get_event_loop()
        self.server = None
        self.broadcast_lock = asyncio.Lock()
        self.client_connected = asyncio.Event()

    async def handler(self, websocket, path):
        """Handle new WebSocket connections"""
        client_address = websocket.remote_address[0]
        logger.info(f"New WebSocket client connected: {client_address}")
        
        if not self.connected_clients:
            self.client_connected.set()
        self.connected_clients.add(websocket)
        
        try:
            await websocket.send(json.dumps({
                "type": "connection_status",
                "status": "connected",
                "message": "Connected to TrachHub data stream"
            }))
            
            async for message in websocket:
                logger.debug(f"Received message from {client_address}: {message}")
                
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"WebSocket client disconnected: {client_address}")
        finally:
            self.connected_clients.remove(websocket)
            if not self.connected_clients:
                self.client_connected.clear()

    async def broadcast_data(self, data):
        """Broadcast data to all connected WebSocket clients"""

        message = json.dumps({
            "type": "sensor_data",
            "timestamp": datetime.now().isoformat(),
            "data": data,
            "bluetooth_connected": bluetooth_manager.is_connected
        })

        # logger.info(f"Broadcasting data: {message}")

        if not self.connected_clients:
            return

        async with self.broadcast_lock:
            for client in list(self.connected_clients):
                try:
                    await client.send(message)
                except:
                    self.connected_clients.remove(client)

    async def start(self, host='0.0.0.0', port=8765):
        """Start the WebSocket server"""
        self.server = await websockets.serve(
            self.handler,
            host,
            port
        )
        logger.info(f"WebSocket server started on ws://{host}:{port}")

    async def stop(self):
        """Stop the WebSocket server"""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info("WebSocket server stopped")

# Create an instance of the WebSocket server
websocket_server = WebSocketServer()

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
                ['netsh', 'wlan', 'show', 'networks'], 
                text=True, 
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            # parse SSID names from the command output
            for line in output.split('\n'):
                if 'SSID' in line and 'BSSID' not in line:
                    ssid = line.split(':')[1].strip()
                    if ssid:
                        networks.append(ssid)
            return list(set(networks))
        else:
            # for TrachHub RPI WiFi scanning
            output = subprocess.check_output(['sudo', 'iwlist', 'wlan0', 'scan'])
            networks = []
            for line in output.decode('utf-8').split('\n'):
                if 'ESSID:' in line:
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
            with open(profile_path, 'w') as f:
                f.write(profile)
            
            subprocess.run(
                ['netsh', 'wlan', 'add', 'profile', f'filename="{profile_path}"'],
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            subprocess.run(
                ['netsh', 'wlan', 'connect', f'name={ssid}'],
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            os.remove(profile_path)
        else:
            # Linux/Raspberry Pi WiFi connection configuration
            config = (
                f'network={{\n'
                f'    ssid="{ssid}"\n'
                f'    psk="{password}"\n'
                f'    key_mgmt=WPA-PSK\n'
                f'}}\n'
            )
            
            with open('/etc/wpa_supplicant/wpa_supplicant.conf', 'a') as f:
                f.write(config)
            
            subprocess.run(['sudo', 'wpa_cli', 'reconfigure'])
            subprocess.run(['sudo', 'systemctl', 'restart', 'networking'])
        
        # Update connection state
        device_state['wifi_connected'] = True
        device_state['connected_ssid'] = ssid
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
        return [{
            'name': dev.name or 'Unknown Device',
            'address': dev.address,
            'rssi': dev.rssi
        } for dev in devices]
    except Exception as e:
        logger.error(f"Error scanning Bluetooth: {e}")
        return []
    finally:
        loop.close()

@app.route('/api/bluetooth/scan')
def bluetooth_scan():
    devices = run_bluetooth_scan()
    return jsonify({'devices': devices})

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
        device_state['bluetooth_connected'] = success
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
            if device_state['bluetooth_connected'] and bluetooth_manager.client:
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

# if platform.system() != "Windows":
#     # Initialize background tasks when running on a Linux/Raspberry Pi system
#     asyncio.create_task(start_background_tasks())

# Routes with async support
@app.route('/')
def index():
    """
    Renders the main index page for the web interface. This serves as the front-facing HTML template for the application,
    intended as a landing page or basic interface.
    
    Returns:
    - Rendered HTML template `index.html`.
    """
    return render_template('index.html')

@app.route('/api/wifi/scan')
def wifi_scan():
    """
    API endpoint to scan for available WiFi networks. Invokes `get_wifi_networks` to retrieve the list of SSIDs.

    Returns:
    - JSON response with the list of available WiFi networks (`{'networks': [...]}`)
    """
    networks = get_wifi_networks()
    return jsonify({'networks': networks})

@app.route('/api/wifi/connect', methods=['POST'])
def wifi_connect_route():
    """
    API endpoint to connect to a specified WiFi network. Expects a JSON payload containing `ssid` and `password` keys.
    
    Returns:
    - JSON response indicating connection success or failure (`{'success': True/False}`)
    """
    data = request.get_json()
    success = connect_wifi(data['ssid'], data['password'])
    return jsonify({'success': success})

# lol, I'm not going to implement this
# @app.route('/api/bluetooth/scan')
# async def bluetooth_scan():
#     """
#     API endpoint to scan for nearby Bluetooth devices asynchronously. Calls `run_bluetooth_scan` to discover devices.

#     Returns:
#     - JSON response containing a list of detected Bluetooth devices (`{'devices': [...]}`)
#     - On error, returns JSON with an error message and empty device list (`{'devices': [], 'error': ...}`)
#     """
#     try:
#         devices = await run_bluetooth_scan()
#         return jsonify({'devices': devices})
#     except Exception as e:
#         logger.error(f"Bluetooth scan error: {e}")
#         return jsonify({'devices': [], 'error': str(e)}), 500

# @app.route('/api/bluetooth/connect', methods=['POST'])
# async def bluetooth_connect():
#     """
#     API endpoint to connect to a Bluetooth device asynchronously. Expects JSON payload with an `address` key.
    
#     Returns:
#     - JSON response with connection status and timestamp (`{'success': True/False, 'status': 'connected'/'failed', 'timestamp': ...}`)
#     - On error, returns JSON with failure status and error message (`{'success': False, 'error': ...}`)
#     """
#     try:
#         data = request.get_json()
#         success = await connect_bluetooth_device(data['address'])
#         return jsonify({
#             'success': success,
#             'status': 'connected' if success else 'failed',
#             'timestamp': datetime.now().isoformat()
#         })
#     except Exception as e:
#         logger.error(f"Bluetooth connect error: {e}")
#         return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/bluetooth/connect', methods=['POST'])
def bluetooth_connect():
    data = request.get_json()
    # Schedule the coroutine on the background loop and get the result
    future = asyncio.run_coroutine_threadsafe(
        connect_bluetooth_device(data['address']),
        background_loop
    )
    success = future.result()
    return jsonify({'success': success})

@app.route('/api/status')
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
        'current_wifi': current_ssid,
        'system_time': datetime.now().isoformat(),
        'bluetooth_manager_status': {
            'connected': bluetooth_manager.is_connected if bluetooth_manager else False,
            'last_data_time': bluetooth_manager.last_data_time.isoformat() if bluetooth_manager and bluetooth_manager.last_data_time else None,
            'reconnection_attempts': bluetooth_manager.reconnect_attempts if bluetooth_manager else 0
        }
    }
    return jsonify(status)

@app.route('/api/data')
def get_data():
    """
    API endpoint to retrieve data from the connected Bluetooth device. If the device is not connected,
    returns an error response.

    Returns:
    - JSON response with data from Bluetooth device or an error message if not connected (`{'data': [...]}` or `{'error': ...}`)
    """
    if not bluetooth_manager or not bluetooth_manager.is_connected:
        return jsonify({
            'data': [],
            'error': 'Device not connected',
            'last_connection': device_state.get('last_bluetooth_connection')
        })
    
    # Return the last value received via notification
    value = device_state.get('device_data')
    if value is not None:
        return jsonify({'data': [value]})
    else:
        return jsonify({
            'data': [],
            'error': 'No data received yet',
            'last_connection': device_state.get('last_bluetooth_connection')
        })

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
                ['netsh', 'wlan', 'show', 'interfaces'],
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            for line in output.split('\n'):
                if 'SSID' in line and 'BSSID' not in line:
                    ssid = line.split(':')[1].strip()
                    if ssid:
                        return ssid
        else:  # for Linux/Raspberry Pi
            try:
                output = subprocess.check_output(['iwgetid', '-r'], text=True)
                return output.strip()
            except subprocess.CalledProcessError:
                try:
                    output = subprocess.check_output(['iwconfig', 'wlan0'], text=True)
                    for line in output.split('\n'):
                        if 'ESSID:' in line:
                            ssid = line.split('ESSID:"')[1].split('"')[0]
                            if ssid:
                                return ssid
                except:
                    pass
    except Exception as e:
        logger.error(f"Error getting current WiFi: {e}")
    return None

@app.route('/api/wifi/current')
def get_wifi_status():
    """
    API endpoint to check the current WiFi connection status. Calls `get_current_wifi` to determine the connected SSID.

    Returns:
    - JSON response with connection status, SSID, and current timestamp.
    """
    current_ssid = get_current_wifi()
    connected = bool(current_ssid)
    device_state['wifi_connected'] = connected
    device_state['connected_ssid'] = current_ssid if connected else None
    return jsonify({
        'connected': connected,
        'ssid': current_ssid,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/health')
def health_check():
    """
    System health check endpoint. Provides a basic report on system connectivity status for WiFi and Bluetooth,
    including system uptime.

    Returns:
    - JSON object with system health details: WiFi status, Bluetooth status, and uptime.
    """
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'wifi': {
            'connected': device_state['wifi_connected'],
            'ssid': device_state['connected_ssid']
        },
        'bluetooth': {
            'connected': bluetooth_manager.is_connected if bluetooth_manager else False,
            'last_data_time': bluetooth_manager.last_data_time.isoformat() if bluetooth_manager and bluetooth_manager.last_data_time else None,
            'reconnection_attempts': bluetooth_manager.reconnect_attempts if bluetooth_manager else 0
        },
        'uptime': time.time() - start_time
    })
from hypercorn.asyncio import serve
from hypercorn.config import Config

start_time = time.time()
async def run_servers():

    loop = asyncio.get_event_loop()
    global background_loop
    background_loop = loop
    # Create a task for the WebSocket server
    ws_task = asyncio.create_task(websocket_server.start())
    
    # Configure and run Hypercorn (Flask) server
    config = Config()
    config.bind = [f"{local_ip}:5000"]
    config.worker_class = 'asyncio'
    
    flask_task = asyncio.create_task(serve(app, config))
    
    # Also run the background monitoring
    start_background_tasks(asyncio.get_event_loop())
    
    # Wait for both servers to run (they won't complete normally)
    await asyncio.gather(ws_task, flask_task)

if __name__ == '__main__':
    try:
        # Get local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 1))
        local_ip = s.getsockname()[0]
        s.close()
        
        if platform.system() != "Windows":
            try:
                subprocess.run(['sudo', 'setterm', '-blank', '5', '-powerdown', '5'])
                subprocess.run(['sudo', 'systemctl', 'disable', 'apt-daily.service'])
                subprocess.run(['sudo', 'systemctl', 'disable', 'apt-daily.timer'])
            except Exception as e:
                logger.warning(f"Failed to configure system settings: {e}")
        
        print(f"TrachHub Server running at http://{local_ip}:5000")
        print(f"WebSocket server running at ws://{local_ip}:8765")
        
        # Set up logging
        werkzeug_logger = logging.getLogger('werkzeug')
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
