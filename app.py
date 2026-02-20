"""
TrachHub - OS-Agnostic Bluetooth Sensor Hub
Server entry point that orchestrates services and API routes.
"""

import logging
import asyncio
import signal
import os
import socket
import argparse
import threading
import time
import matplotlib.pyplot as plt
from plot import plot_live_co2
from flask import Flask, render_template, request, jsonify
from hypercorn.asyncio import serve
from hypercorn.config import Config

# API Blueprints
from backend.src.events.events import events_bp
from backend.src.api.bluetooth import bluetooth_bp, init_bluetooth_api

# Services
from services.bluetooth import BluetoothManager
from services.ws import WebSocketServer

# DB Engine for health check
from backend.src.data_processing.edb import engine

# Argument parsing
parser = argparse.ArgumentParser(description="TrachHub Server")
parser.add_argument("--debug", action="store_true", help="enable developer debug features")
parser.add_argument("-a", "--anomalous", action="store_true", help="cycle anomalies in emulator for testing")
args, unknown = parser.parse_known_args()
DEBUG_MODE = args.debug
ANOMALY_MODE = args.anomalous

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(os.path.expanduser("~"), "trachhub.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Core Components
bluetooth_manager = None
websocket_server = None
db_available = False

# check if database is available
try:
    with engine.connect() as conn:
        db_available = True
        logger.info("connected to events database.")
except Exception:
    logger.warning("events database not found. anomalies will be logged to console only.")

# set up bluetooth manager with options
bluetooth_manager = BluetoothManager(
    debug_mode=DEBUG_MODE, 
    db_available=db_available,
    anomalous_mode=ANOMALY_MODE
)
websocket_server = WebSocketServer(logger, bluetooth_manager)
bluetooth_manager.websocket_server = websocket_server

# Initialize and Register Blueprints
init_bluetooth_api(bluetooth_manager, DEBUG_MODE)
app.register_blueprint(events_bp)
app.register_blueprint(bluetooth_bp)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/health")
def health_check():
    return jsonify({
        "status": "healthy",
        "db_connected": db_available,
        "bluetooth": {
            "connected": bluetooth_manager.is_connected
        }
    })

async def run_servers(shutdown_event: asyncio.Event):
    """starts background services."""
    # capture the main event loop for ble operations
    bluetooth_manager._loop = asyncio.get_running_loop()

    # start websocket and stream supervisor
    ws_task = asyncio.create_task(websocket_server.start(port=8766))
    supervisor_task = asyncio.create_task(bluetooth_manager.stream_supervisor())

    # start flask via hypercorn with shutdown trigger
    config = Config()
    config.bind = ["0.0.0.0:5050"]
    config.worker_class = "asyncio"
    flask_task = asyncio.create_task(serve(app, config, shutdown_trigger=shutdown_event.wait))

    logger.info("servers starting...")

    # wait for shutdown and then stop services cleanly
    async def _shutdown_watcher():
        await shutdown_event.wait()
        try:
            await websocket_server.stop()
        except Exception:
            pass
        try:
            supervisor_task.cancel()
            await supervisor_task
        except asyncio.CancelledError:
            pass

    watcher_task = asyncio.create_task(_shutdown_watcher())

    # wait for flask to exit (triggered by shutdown_event), then for others
    await flask_task
    await watcher_task
    await ws_task

async def gui_loop(shutdown_event: asyncio.Event):
    """main thread gui pump."""
    logger.info("gui pump started")
    while True:
        try:
            if shutdown_event.is_set():
                break
            if bluetooth_manager and not bluetooth_manager.data_queue.empty():
                while not bluetooth_manager.data_queue.empty():
                    val = bluetooth_manager.data_queue.get_nowait()
                    plot_live_co2(val)
            
            plt.pause(0.005)
            await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"gui error: {e}")
            await asyncio.sleep(1)

async def main():
    """orchestrator."""
    shutdown_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGINT, shutdown_event.set)
        loop.add_signal_handler(signal.SIGTERM, shutdown_event.set)
    except NotImplementedError:
        # signal handlers not supported (e.g on windows) – rely on keyboardinterrupt
        pass

    # run servers and gui; they exit when shutdown_event is set
    await asyncio.gather(
        run_servers(shutdown_event),
        gui_loop(shutdown_event),
    )

if __name__ == "__main__":
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 1))
        local_ip = s.getsockname()[0]
        s.close()
    except:
        local_ip = "127.0.0.1"

    print(f"trachhub server: http://{local_ip}:5050")
    print(f"websocket server: ws://{local_ip}:8766")

    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # fallback for environments without proper signal handling
        pass
    finally:
        logger.info("process finished.")
