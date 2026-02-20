from flask import Blueprint, jsonify, request
import asyncio
import concurrent.futures
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
def bluetooth_scan():
    """
    API endpoint to scan for nearby Bluetooth devices.
    routes the async ble scan to the main event loop.
    """
    try:
        devices = _dispatch_to_ble_loop(run_bluetooth_scan(debug_mode), timeout=15)
        return jsonify({"devices": devices})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def _dispatch_to_ble_loop(coro, timeout=10):
    """helper: schedule a coroutine on the ble loop and wait for the result."""
    loop = bluetooth_manager._loop
    if loop is None:
        raise RuntimeError("ble loop not initialized yet")
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)

@bluetooth_bp.route("/api/bluetooth/connect", methods=["POST"])
def bluetooth_connect_route():
    """
    API endpoint to connect to a specific Bluetooth device.
    routes the async ble call to the main event loop.
    """
    data = request.get_json()
    if not data or "address" not in data:
        return jsonify({"success": False, "error": "no address provided"}), 400

    try:
        success = _dispatch_to_ble_loop(bluetooth_manager.connect(data["address"]))
        return jsonify({"success": success})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@bluetooth_bp.route("/api/status")
def status():
    """
    API endpoint to check the overall system and connection status.
    """
    return jsonify(bluetooth_manager.get_status())

@bluetooth_bp.route("/api/bluetooth/start", methods=["POST"])
def bluetooth_start_streaming():
    """
    API endpoint to start streaming data from the connected device.
    routes the async ble call to the main event loop.
    """
    try:
        success = _dispatch_to_ble_loop(bluetooth_manager.start_stream())
        return jsonify({"success": success})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@bluetooth_bp.route("/api/bluetooth/stop", methods=["POST"])
def bluetooth_stop_streaming():
    """
    API endpoint to stop streaming data from the connected device.
    routes the async ble call to the main event loop.
    """
    try:
        success = _dispatch_to_ble_loop(bluetooth_manager.stop_stream())
        return jsonify({"success": success})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
