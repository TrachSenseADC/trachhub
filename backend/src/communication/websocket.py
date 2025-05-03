import asyncio
import websockets
import json
import os
from dotenv import load_dotenv
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.abspath(__file__), "../../../../")))

from backend.src.db import Database
import time
from backend.src.data_processing.analyzer import BreathingPatternAnalyzer
from app import device_state, bluetooth_manager

excel_file = '../data/decann.xlsx'

load_dotenv()
class WebSocket:
    def __init__(self):
        self.connected_clients = set()
        self.run = True
        self.db = Database()
        self.ws_host = os.getenv('WS_HOST', 'localhost')
        self.ws_port = int(os.getenv('WS_PORT', '8765'))
        self.db.setup_database()
        self.db.create_pool()
        self.broadcast_lock = asyncio.Lock()
        self.data_buffer = []
        self.buffer_size = 100  
        self.client_connected = asyncio.Event()
        self.last_sensor_value = None
        self.last_processed_time = 0

    async def handle_client(self, websocket):
        """Handle new WebSocket client connections"""
        client_address = websocket.remote_address
        print(f"New Flutter client connected from {client_address}")
        if not self.connected_clients:
            self.client_connected.set()
        self.connected_clients.add(websocket)
        
        try:
            await websocket.send(json.dumps({
                "type": "connection_status",
                "status": "connected",
                "message": "Successfully connected to data stream"
            }))
            
            async for message in websocket:
                print(f"Received message from client {client_address}: {message}")
                
        except websockets.exceptions.ConnectionClosed:
            print(f"Flutter client disconnected: {client_address}")
        finally:
            self.connected_clients.remove(websocket)
            if not self.connected_clients:
                self.client_connected.clear()

    async def send_data(self, data: dict):
        """Send data to all connected WebSocket clients and handle disconnected clients by removing them from self.connected_servers"""
        if not self.connected_clients:
            print("No clients connected")
            return

        async with self.broadcast_lock:
            messages = [json.dumps({
                "type": "data_update",
                "timestamp": time.time(),
                "data": value["value"],
                "pattern": value["pattern"]
            }) for value in data]

            send_tasks = []
            for client in list(self.connected_clients):
                for message in messages:
                    print('Message:', message)
                    try:
                        task = asyncio.create_task(client.send(message))
                        send_tasks.append(task)
                        print(f"Data queued for client: {client.remote_address}")
                    except Exception as e:
                        print(f"Error queuing data for client {client.remote_address}: {e}")
                        self.connected_clients.discard(client)
                        break

            if send_tasks:
                await asyncio.gather(*send_tasks, return_exceptions=True)

    async def process_data(self):
        """Main data processing loop that reads from Bluetooth sensor"""
        print('Awaiting client connection...')
        await self.client_connected.wait()
        print('Starting real-time data processing from sensor...')
        
        analyzer = BreathingPatternAnalyzer(buffer_size=self.buffer_size)
        
        while self.run:
            try:
                current_value = device_state.get('device_data')
                
                if current_value is not None and current_value != self.last_sensor_value:
                    timestamp = time.time()
                    self.last_sensor_value = current_value
                    
                    self.data_buffer.append({
                        "value": current_value,
                        "timestamp": timestamp
                    })
                    
                    if len(self.data_buffer) >= self.buffer_size:

                        values = [item["value"] for item in self.data_buffer]
                        analyzer.update_data(values)
                        pattern = analyzer.detect_pattern()
                        
                        processed_batch = [{
                            "value": item["value"],
                            "timestamp": item["timestamp"],
                            "pattern": pattern
                        } for item in self.data_buffer]
                        
                        await self.send_data(processed_batch)
                        await self.db_store_data(processed_batch)
                        
                        print(f"Processed batch of {len(processed_batch)} sensor readings")
                        self.data_buffer = []
                    
                    await asyncio.sleep(0.05)
                
                elif not bluetooth_manager.is_connected:
                    print("Bluetooth disconnected, waiting for reconnection...")
                    await asyncio.sleep(1)
                
                else:
                    await asyncio.sleep(0.1)
                    
            except Exception as e:
                print(f"Error in sensor data processing: {e}")
                await asyncio.sleep(1) 
    async def db_store_data(self, chunk):
        # Wrap the synchronous database operation in an async function
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.db.batch_store_data, chunk)

    async def process_queue(self):
        """Go through the data queue and use send_data to send it to all connected servers"""
        while self.run:
            for data in self.data_queue:
                self.send_data(data)
        

    async def start_server(self):
        """Start the WebSocket server"""
        self.db.setup_database()
        
        async with websockets.serve(
            self.handle_client,
            self.ws_host,
            self.ws_port
        ):
            print(f"Server started on {self.ws_host}:{self.ws_port}")
            await asyncio.create_task(self.process_data())
            
            try:
                await asyncio.Future()  
            except asyncio.CancelledError:
                self.stop()
                self.db.close_pool()
        
    def stop(self):
        """Stop the server and cleanup"""
        print("Shutting down server...")
        self.run = False

if __name__ == "__main__":
    server = WebSocket()
    try:
        asyncio.run(server.start_server())
    except KeyboardInterrupt:
        print("\nShutting down...")
        
    finally:
        server.stop()
