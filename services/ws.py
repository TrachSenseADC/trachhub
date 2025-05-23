import asyncio
import websockets
import json
import os
from dotenv import load_dotenv
import sys
import time
from datetime import datetime


sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.abspath(__file__), "../../../../"))
)

from backend.src.db import Database
from backend.src.data_processing.analyzer import BreathingPatternAnalyzer

# from app import device_state, bluetooth_manager

load_dotenv()
import websockets
from functools import partial

logger = None


class WebSocketServer:
    def __init__(self, log, ble_manager):
        self.connected_clients = set()
        self.loop = asyncio.get_event_loop()
        self.server = None
        self.broadcast_lock = asyncio.Lock()
        self.client_connected = asyncio.Event()
        self.logger = log
        self.bluetooth_manager = ble_manager

    async def handler(self, websocket):
        """Handle new WebSocket connections"""
        # path = websocket.path
        client_address = websocket.remote_address[0]
        self.logger.info(f"New WebSocket client connected: {client_address}")

        if not self.connected_clients:
            self.client_connected.set()
        self.connected_clients.add(websocket)

        try:
            await websocket.send(
                json.dumps(
                    {
                        "type": "connection_status",
                        "status": "connected",
                        "message": "Connected to TrachHub data stream",
                    }
                )
            )

            async for message in websocket:
                logger.debug(f"Received message from {client_address}: {message}")

        except websockets.exceptions.ConnectionClosed:
            self.logger.info(f"WebSocket client disconnected: {client_address}")
        finally:
            self.connected_clients.remove(websocket)
            if not self.connected_clients:
                self.client_connected.clear()

    async def broadcast_json(self, obj: dict) -> None:
        
        await self.broadcast_data(json.dumps(obj))

    async def broadcast_data(self, data):
        """Send one JSON message to every connected WebSocket client."""
        # Encode once, and only once
        if isinstance(data, (dict, list)):
            message = json.dumps(data, default=str)
        else:
            message = data  # already a JSON string or bytes

        # self.logger.info("Broadcasting: %s", message)

        if not self.connected_clients:
            return

        async with self.broadcast_lock:
            for ws in list(self.connected_clients):
                try:
                    await ws.send(message)
                except Exception:
                    self.connected_clients.discard(ws)


    async def start(self, host="0.0.0.0", port=8765):
        """Start the WebSocket server"""
        self.server = await websockets.serve(self.handler, host, port)
        self.logger.info(f"WebSocket server started on ws://{host}:{port}")

    async def stop(self):
        """Stop the WebSocket server"""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.logger.info("WebSocket server stopped")
