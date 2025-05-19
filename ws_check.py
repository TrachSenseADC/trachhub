#!/usr/bin/env python3
import asyncio, json, websockets, logging, time

URI = "wss://localhost:8765/"
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")

async def receive_forever(ws: websockets.WebSocketClientProtocol) -> None:
    """Print every message until the server closes the socket."""
    async for raw in ws:                       # blocks until close frame
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            msg = raw
        logging.info("📨 %s", msg)

async def main() -> None:
    backoff = 1                                # seconds – exponential back-off
    while True:
        try:
            async with websockets.connect(
                URI,
                ping_interval=20,              # send ping every 20 s
                ping_timeout=10,               # drop if no pong in 10 s
                close_timeout=5,               # wait max 5 s for close ack
            ) as ws:
                logging.info("WebSocket connected")
                backoff = 1                    # reset after a good connect
                await receive_forever(ws)      # blocks until connection closes

        except (websockets.ConnectionClosedOK,    # server sent a close frame
                websockets.ConnectionClosedError, # closed with error
                OSError) as e:                    # network hiccup
            logging.warning("connection lost: %s", e)
        except Exception as e:
            logging.error("unexpected error: %s", e)

        # ————————————————— reconnection strategy ———————————————————
        logging.info("🔄 reconnecting in %s s…", backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 30)         # cap at 30 s

if __name__ == "__main__":
    asyncio.run(main())
