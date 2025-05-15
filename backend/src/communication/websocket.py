import asyncio
import websockets
import json
import os
from dotenv import load_dotenv
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.abspath(__file__), "../../../../")))

from backend.src.db import Database
from backend.src.data_processing.analyzer import BreathingPatternAnalyzer
from app import device_state

load_dotenv()

class WebSocket:
    def __init__(self, host='0.0.0.0', port=8765, buffer_size=100, poll_interval=0.05):
        self.host = host
        self.port = port
        self.buffer_size = buffer_size
        self.poll_interval = poll_interval
        self.connected = set()
        self.broadcast_lock = None
        self.client_evt = None
        self.data_buf = []
        self.last_value = None
        self.db = Database()
        self.db.setup_database()


    async def handle_client(self, websocket, path):
        if not self.client_evt.is_set():
            self.client_evt.set()
        self.connected.add(websocket)
        try:
            await websocket.send(json.dumps({"type":"connected"}))
            async for _ in websocket: pass
        finally:
            self.connected.remove(websocket)
            if not self.connected:
                self.client_evt.clear()

    async def process_loop(self):
        """Wait for a client, then start listening to sensor device."""
        await self.client_evt.wait()
        analyzer = BreathingPatternAnalyzer(buffer_size=self.buffer_size)
        while True:
            val = device_state.get('device_data')
            if val is not None and val != self.last_value:
                self.last_value = val
                timestamp = time.time()
                self.data_buf.append({"value": val, "ts": timestamp})

                if len(self.data_buf) >= self.buffer_size:
                    analyzer.update_data([d["value"] for d in self.data_buf])
                    pattern = analyzer.detect_pattern()
                    payload = {
                        "type": "batch",
                        "pattern": pattern,
                        "readings": self.data_buf
                    }
                    await self.broadcast_data(payload)
                    batch_copy = self.data_buf.copy()

                    asyncio.get_running_loop().run_in_executor(
                        None,
                        self.db.batch_store_data,
                        [
                            {
                                "timestamp": datetime.utcfromtimestamp(d["ts"]),
                                "value":     d["value"],
                                "pattern":   pattern
                            }
                            for d in batch_copy
                        ]
                    )
                    self.data_buf.clear()
            await asyncio.sleep(self.poll_interval)

    async def db_store_data(self, chunk):
        """Store data in the database asynchronously"""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.db.batch_store_data, chunk)
    
    async def broadcast_data(self, obj):
        msg = json.dumps(obj)
        async with self.broadcast_lock:
            to_drop = []
            for ws in self.connected:
                try:
                    await asyncio.wait_for(ws.send(msg), timeout=1)
                except Exception as e:
                    print(f"Error sending data to client {ws.remote_address}: {e}")
                    to_drop.append(ws)
            for ws in to_drop:
                self.connected.discard(ws)
                
    async def start(self):
        self.broacast_lock = asyncio.Lock()
        self.client_evt = asyncio.Event()
        asyncio.create_task(self.process_loop())
        async with websockets.serve(self.handle_client, self.host, self.port):
            await asyncio.Future()