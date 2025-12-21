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

load_dotenv()
import websockets
from functools import partial

logger = None


class WebSocketServer:
    def __init__(self, log, ble_manager):
        self.connected_clients = set()
        self.server = None
        self.broadcast_lock = None # initialized in start/broadcast
        self.client_connected = None # initialized in start
        self.logger = log
        self.bluetooth_manager = ble_manager

    async def handler(self, websocket):
        """Handle new WebSocket connections"""
        # path = websocket.path
        client_address = websocket.remote_address[0]
        self.logger.info(f"new websocket client connected: {client_address}")

        if not self.connected_clients:
            self.client_connected.set()
        self.connected_clients.add(websocket)

        try:
            await websocket.send(
                json.dumps(
                    {
                        "type": "connection_status",
                        "status": "connected",
                        "message": "connected to trachhub data stream",
                    }
                )
            )

            async for message in websocket:
                logger.debug(f"received message from {client_address}: {message}")

        except websockets.exceptions.ConnectionClosed:
            self.logger.info(f"websocket client disconnected: {client_address}")
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

        if self.broadcast_lock is None:
            self.broadcast_lock = asyncio.Lock()

        async with self.broadcast_lock:
            for ws in list(self.connected_clients):
                try:
                    await ws.send(message)
                except Exception:
                    self.connected_clients.discard(ws)


    async def start(self, host="0.0.0.0", port=8765):
        """start the websocket server"""
        if self.broadcast_lock is None:
            self.broadcast_lock = asyncio.Lock()
        if self.client_connected is None:
            self.client_connected = asyncio.Event()

        try:
            self.server = await websockets.serve(self.handler, host, port)
            self.logger.info(f"websocket server started on ws://{host}:{port}")
            await self.server.wait_closed()
        except asyncio.CancelledError:
            self.logger.info("websocket server task cancelled, closing...")
            if self.server:
                self.server.close()
                await self.server.wait_closed()
        except OSError as e:
            # address already in use (48 on mac, 98 on linux, 10048 on windows)
            if getattr(e, 'errno', None) in (48, 98, 10048):
                self.logger.warning(f"websocket port {port} already in use, skipping server start")
                return
            self.logger.error(f"websocket server os error: {e}")
            raise
        except Exception as e:
            self.logger.error(f"websocket server error: {e}")
            raise

    async def stop(self):
        """Stop the WebSocket server"""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.logger.info("websocket server stopped")
