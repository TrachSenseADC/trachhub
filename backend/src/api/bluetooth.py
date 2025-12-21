from flask import Blueprint, jsonify, request
import asyncio
from services.bluetooth import run_bluetooth_scan

bluetooth_bp = Blueprint('bluetooth', __name__)

# this will be initialized by the main app
bluetooth_manager = None
debug_mode = False

def init_bluetooth_api(mgr, debug):
    global bluetooth_manager, debug_mode
    bluetooth_manager = mgr
    debug_mode = debug

@bluetooth_bp.route("/api/bluetooth/scan")
async def bluetooth_scan():
    """
    API endpoint to scan for nearby Bluetooth devices.
    """
    try:
        devices = await run_bluetooth_scan(debug_mode)
        return jsonify({"devices": devices})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bluetooth_bp.route("/api/bluetooth/connect", methods=["POST"])
async def bluetooth_connect_route():
    """
    API endpoint to connect to a specific Bluetooth device.
    """
    data = request.get_json()
    if not data or "address" not in data:
        return jsonify({"success": False, "error": "No address provided"}), 400
        
    success = await bluetooth_manager.connect(data["address"])
    return jsonify({"success": success})

@bluetooth_bp.route("/api/status")
def status():
    """
    API endpoint to check the overall system and connection status.
    """
    return jsonify(bluetooth_manager.get_status())

@bluetooth_bp.route("/api/bluetooth/start", methods=["POST"])
async def bluetooth_start_streaming():
    """
    API endpoint to start streaming data from the connected device.
    """
    success = await bluetooth_manager.start_stream()
    return jsonify({"success": success})

@bluetooth_bp.route("/api/bluetooth/stop", methods=["POST"])
async def bluetooth_stop_streaming():
    """
    API endpoint to stop streaming data from the connected device.
    """
    success = await bluetooth_manager.stop_stream()
    return jsonify({"success": success})
