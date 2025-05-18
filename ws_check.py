#!/usr/bin/env python3
import asyncio
import json
import websockets

URI = "ws://127.0.0.1:8765"  

async def check_connection():
    try:
        async with websockets.connect(URI) as ws:
            print("Connected to WebSocket server.")

            async def receiver():
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        msg = raw
                    print("📨", msg)

            recv_task = asyncio.create_task(receiver())

            await asyncio.sleep(30)
            recv_task.cancel()

    except Exception as e:
        print(f"❌ Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(check_connection())
