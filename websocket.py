import asyncio
import websockets
import json
import os
from dotenv import load_dotenv
from db import Database
from sensors import co2
import time
from analyzer import BreathingPatternAnalyzer

load_dotenv()
class WebSocket:
    def __init__(self):
        self.connected_clients = set()
        self.run = True
        self.db = Database()
        self.ws_host = os.getenv('WS_HOST', 'localhost')
        self.ws_port = int(os.getenv('WS_PORT', '8765'))
        self.last_processed_row = 0
        self.db.setup_database()
        self.db.create_pool()
        self.broadcast_lock = asyncio.Lock()
        self.data_buffer = []
        self.buffer_size = 100  
        self.client_connected = asyncio.Event()

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

    async def send_data(self, co2_value: float, pattern):
        
        """Send data to all connected WebSocket clients and handle disconnected clients by removing them from self.connected_servers"""
        """Send real-time CO₂ data to all connected WebSocket clients."""
        if not self.connected_clients:
            print("No clients connected")
            return

        message = json.dumps({
            "type": "data_update",
            "timestamp": time.time(),
            "data": co2_value,
            "pattern": pattern
        })

        async with self.broadcast_lock:
            for client in list(self.connected_clients):
                try:
                    await client.send(message)
                    print(f"Sent data to client: {client.remote_address}")
                except Exception as e:
                    print(f"Error sending data to client {client.remote_address}: {e}")
                    self.connected_clients.discard(client)
                    break

    # this will get the data from the arduino that is configured in co2.py, and will return it
    async def receive_data(self):
        while True:
            if co2.arduino.in_waiting > 0:
                try:
                    return float(co2.arduino.readline().decode('ascii').strip())
                except Exception as e:
                    print(f"Unexpected error: {e}")
                break

    async def process_data(self):
        print('Awaiting client connection...')
        await self.client_connected.wait()
        print('Starting data processing loop...')
        analyzer = BreathingPatternAnalyzer(buffer_size=self.buffer_size)
        
        while self.run:
            try:
                co2_data = await self.receive_data()
                print(f"Received C02 data: {co2_data}")
                # we add our data to the data buffer and make sure it hasn't passed our size limit
                self.data_buffer.append(co2_data)
                if len(self.data_buffer) > self.buffer_size:
                    self.data_buffer.pop(0) 
                
                if len(self.data_buffer) == self.buffer_size: # perform analysis once we have sufficient amount of data
                    analyzer.update_data(self.data_buffer)
                    pattern = analyzer.detect_pattern()
                else:
                    pattern = "insufficient data"

                # Store in DB and send via WebSocket
                db_task = asyncio.create_task(self.db_store_data(co2_data, pattern))
                await self.send_data(co2_data, pattern)
                await db_task

                await asyncio.sleep(0.3)  # Prevent flooding

            except Exception as e:
                print(f"Error in process_data loop: {e}")
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