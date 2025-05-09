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

class WebSocket:
    def __init__(self):
        self.connected_clients = set()
        self.run = True
        self.ws_host = os.getenv('WS_HOST', 'localhost')
        self.ws_port = int(os.getenv('WS_PORT', '8765'))
        # Database setup moved to async init
        self.broadcast_lock = None  # Will be initialized in start_server
        self.data_buffer = []
        self.buffer_size = 100
        self.client_connected = None  # Will be initialized in start_server
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
        """Send data to all connected WebSocket clients"""
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

            clients_to_remove = set()
            for client in self.connected_clients:
                for message in messages:
                    try:
                        await client.send(message)
                        print(f"Data sent to client: {client.remote_address}")
                    except Exception as e:
                        print(f"Error sending data to client {client.remote_address}: {e}")
                        clients_to_remove.add(client)
                        break
            
            # Remove disconnected clients after iteration
            for client in clients_to_remove:
                self.connected_clients.discard(client)

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
                        # Database storage would go here if needed
                        
                        print(f"Processed batch of {len(processed_batch)} sensor readings")
                        self.data_buffer = []
                    
                    await asyncio.sleep(0.05)
                
                elif not bluetooth_manager.is_connected:
                    print("Bluetooth disconnected, waiting for reconnection...")
                    await asyncio.sleep(1)
                
                else:
                    await asyncio.sleep(0.1)
                    
            except asyncio.CancelledError:
                # Re-raise to allow proper task cancellation
                raise
            except Exception as e:
                print(f"Error in sensor data processing: {e}")
                await asyncio.sleep(1)

    async def db_store_data(self, chunk):
        """Store data in the database asynchronously"""
        loop = asyncio.get_running_loop()  # Get the current running loop
        await loop.run_in_executor(None, self.db.batch_store_data, chunk)

    async def start_server(self):
        """Start the WebSocket server"""
        # Initialize asyncio primitives inside the event loop
        self.broadcast_lock = asyncio.Lock()
        self.client_connected = asyncio.Event()
        
        # Initialize database if needed
        # self.db = Database()
        # await loop.run_in_executor(None, self.db.setup_database)
        # await loop.run_in_executor(None, self.db.create_pool)
        
        # Create and store the process_data task to properly handle cancellation
        process_task = asyncio.create_task(self.process_data())
        
        async with websockets.serve(
            self.handle_client,
            self.ws_host,
            self.ws_port
        ):
            print(f"Server started on {self.ws_host}:{self.ws_port}")
            
            try:
                await asyncio.Future()  # Run forever
            except asyncio.CancelledError:
                print("Server is being cancelled...")
                # Cancel our process_data task
                process_task.cancel()
                try:
                    await process_task  # Wait for cancellation to complete
                except asyncio.CancelledError:
                    pass  # Expected during shutdown
                
                self.stop()
                # Database cleanup would go here
                # await loop.run_in_executor(None, self.db.close_pool)
                raise  # Re-raise the CancelledError
        
    def stop(self):
        """Stop the server and cleanup"""
        print("Shutting down server...")
        self.run = False

async def main():
    """Main entry point for the WebSocket server"""
    server = WebSocket()
    await server.start_server()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down due to keyboard interrupt...")
    except Exception as e:
        print(f"Error in main loop: {e}")