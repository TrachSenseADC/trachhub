#!/usr/bin/env python3
import asyncio
import websockets

async def check_connection():
    try:
        async with websockets.connect("ws://127.0.0.1:8765") as ws:
            print("Connected to WebSocket server.")
            await asyncio.sleep(30)
    except Exception as e:
        print(f"❌ Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(check_connection())
