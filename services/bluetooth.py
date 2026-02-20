import asyncio
import logging
import struct
import uuid
import os
from datetime import datetime, timezone
from pathlib import Path

from bleak import BleakClient, BleakScanner
from sqlalchemy.orm import Session

from calibrate import calibrate
from CONSTANTS import A, B, C, GAS_READING
from logger import DataLoggerCSV
from backend.src.data_processing.analyzer import BreathingPatternAnalyzer
from backend.src.data_processing.edb import engine
from backend.src.models.events import Anomaly

logger = logging.getLogger(__name__)

# Constants and Buffers
BUFFER_ANALYZER = 100
BUFFER_STREAM = 1

# Helper function to convert full bluetooth uuid to short 16-bit hex if possible
def convertUUIDtoShortID(uuid_str):
    if "-" in uuid_str:
        if uuid_str.lower().endswith("-0000-1000-8000-00805f9b34fb"):
            return uuid_str[4:8]
    return uuid_str

# Helper to build the 26-byte trachsense config packet
def build_config_packet(duration=3600, alert_level=1):
    packet = bytearray(26)
    packet[0] = 2 # mode
    duration_bytes = struct.pack("<I", duration)
    packet[1:5] = duration_bytes
    alert_bytes = struct.pack("<H", alert_level)
    packet[11:13] = alert_bytes
    packet[24] = 13 # cr
    packet[25] = 10 # lf
    return packet

# Helper to parse trachsense data packets
def parse_packet(data):
    if len(data) < 8:
        return None
    timestamp_raw = struct.unpack("<I", data[0:4])[0]
    timestamp_s = timestamp_raw / 100000.0
    on_val = data[5] + (data[4] << 8)
    off_val = data[7] + (data[6] << 8)
    diff = on_val - off_val
    return {
        "time": timestamp_s,
        "on": on_val,
        "off": off_val,
        "diff": diff
    }

import queue

class BluetoothManager:
    def __init__(self, websocket_server=None, debug_mode=False, db_available=False, anomalous_mode=False):
        self.client = None
        self.device_address = None
        self.is_connected = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 2
        self._lock = None # initialized on first use
        self.last_data_time = None
        
        self.websocket_server = websocket_server
        self.debug_mode = debug_mode
        self.db_available = db_available
        self.anomalous_mode = anomalous_mode
        
        self.device_state = {
            "bluetooth_connected": False,
            "device_data": None,
            "last_bluetooth_connection": None,
            "reconnection_attempts": 0,
        }
        
        self.analyzer = BreathingPatternAnalyzer(
            buffer_size=BUFFER_ANALYZER, batch_size=BUFFER_ANALYZER
        )
        self.batch_100 = []
        self.chunk_50 = []
        self.diff_logger = None
        
        self.in_anomaly = False
        self.anomaly_start = None
        self.anomaly_end = None
        self.current_state = "normal breathing"
        self.is_streaming = False
        self.stream_task = None
        
        self.data_queue = queue.Queue()
        self._loop = None  # the event loop where bleak client lives

    async def connect(self, address):
        # capture the loop that bleak will run on
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            try:
                if self.client and self.is_connected:
                    await self.client.disconnect()

                self.device_address = address
                
                if address == "EMULATOR" and self.debug_mode:
                    logger.info("routing connection to internal emulator (idle)...")
                    self.is_connected = True
                    self.reconnect_attempts = 0
                    self.last_data_time = datetime.now()
                    now_iso = self.last_data_time.isoformat()
                    self.device_state["bluetooth_connected"] = True
                    self.device_state["last_bluetooth_connection"] = now_iso
                    
                    # initialize session logger - project root
                    log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "diff.csv")
                    logger.info(f"initializing session logger at: {log_path}")
                    if self.anomalous_mode:
                        logger.info("anomalous mode enabled")
                    self.diff_logger = DataLoggerCSV(log_path)

                    logger.info(f"connected to device: {address}")
                    if self.websocket_server:
                        asyncio.create_task(self.websocket_server.broadcast_data({
                            "type": "bluetooth_status",
                            "bluetooth_connected": True,
                            "device_address": address,
                            "timestamp": now_iso
                        }))
                    return True

                self.client = BleakClient(
                    address, disconnected_callback=self.handle_disconnect
                )
                await self.client.connect()
                
                services = self.client.services
                chars_by_short = {}
                for service in services:
                    for char in service.characteristics:
                        short_id = convertUUIDtoShortID(char.uuid)
                        chars_by_short[short_id] = char
                        logger.info(f"discovered: {short_id} ({char.uuid})")

                stream_char = chars_by_short.get("fff4")
                config_char = chars_by_short.get("fff3")
                cmd_char    = chars_by_short.get("fff1")

                if stream_char:
                    logger.info(f"subscribing to {stream_char.uuid}")
                    await self.client.start_notify(stream_char.uuid, self.notification_handler)
                    
                    try:
                        if config_char:
                            logger.info(f"sending config to {config_char.uuid}")
                            packet = build_config_packet()
                            await self.client.write_gatt_char(config_char.uuid, packet, response=True)
                        
                    except Exception as gatt_err:
                        logger.warning(f"gatt handshake warning (non-fatal): {gatt_err}")

                logger.info("bluetooth connection sequence finished.")
                
                self.is_connected = True
                self.reconnect_attempts = 0
                self.last_data_time = datetime.now()
                self.device_state["bluetooth_connected"] = True
                self.device_state["last_bluetooth_connection"] = datetime.now().isoformat()
                logger.info(f"connected to device: {address}")
                
                # reinitialize logger for this session - use project root
                log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "diff.csv")
                logger.info(f"initializing session logger at: {log_path}")
                self.diff_logger = DataLoggerCSV(log_path)
                
                if self.websocket_server:
                    asyncio.create_task(self.websocket_server.broadcast_data({
                        "type": "bluetooth_status",
                        "bluetooth_connected": True,
                        "device_address": address,
                        "timestamp": datetime.now().isoformat()
                    }))

                asyncio.create_task(self.monitor_connection())
                return True
            except Exception as e:
                logger.error(f"failed to connect: {e}")
                self.is_connected = False
                self.device_state["bluetooth_connected"] = False
                return False

    def notification_handler(self, sender, data):
        if not self.is_streaming:
            return
        try:
            parsed = parse_packet(data)
            if not parsed:
                return
            
            value = parsed["diff"]
            calibrated_co2 = calibrate(A, B, C, value, GAS_READING)
            # Log every reading for now to debug missing values
            logger.info(f"data received: diff={value} | co2={calibrated_co2:.2f}")
            
            if self.diff_logger:
                try:
                    self.diff_logger.log({
                        "time": parsed["time"],
                        "on": parsed["on"],
                        "off": parsed["off"],
                        "diff": parsed["diff"]
                    })
                except Exception as e:
                    logger.error(f"logging error: {e}")
            
            # enqueue for main thread plotting
            self.data_queue.put(calibrated_co2)
            
            now = datetime.now(tz=timezone.utc)

            self.batch_100.append(value)
            if len(self.batch_100) == BUFFER_ANALYZER:
                self.analyzer.update_data(self.batch_100)
                self.current_state = self.analyzer.detect_pattern()
                self.batch_100.clear()

                if self.current_state != "normal breathing":
                    if not self.in_anomaly:
                        self.in_anomaly = True
                        self.anomaly_start = now
                        self.anomaly_end = None
                        logger.info(f"anomaly started: {self.current_state}")

                else:
                    if self.in_anomaly:
                        self.in_anomaly = False
                        self.anomaly_end = now
                        duration = (self.anomaly_end - self.anomaly_start).total_seconds()
                        severity = ("high" if duration > 30 else "medium" if duration > 10 else "low")

                        logger.info(f"anomaly ended: {duration:.2f} s (sev={severity})")
                        if self.db_available:
                            try:
                                with Session(engine) as session:
                                    anomaly = Anomaly(
                                        uuid=str(uuid.uuid4()),
                                        title=self.current_state.lower(),
                                        start_time=self.anomaly_start,
                                        end_time=self.anomaly_end,
                                        note="auto-logged via ble stream",
                                        duration=duration,
                                        severity=severity,
                                    )
                                    session.add(anomaly)
                                    session.commit()
                                    logger.info(f"anomaly logged to database: {self.current_state}")
                            except Exception as e:
                                logger.error(f"failed to log anomaly to database: {e}")
                        else:
                            logger.info(f"anomaly detected (console only): {self.current_state} for {duration:.2f}s")

            self.chunk_50.append(value)
            if len(self.chunk_50) == BUFFER_STREAM:
                payload = {
                    "type": "sensor_chunk",
                    "timestamp": now.isoformat(),
                    "values": self.chunk_50.copy(),
                    "bluetooth_connected": self.is_connected,
                }
                if self.in_anomaly:
                    payload["anomaly"]      = {"start": self.anomaly_start.isoformat()}
                    payload["anomaly_type"] = self.current_state

                if self.anomaly_end is not None:
                    payload["anomaly"] = {
                        "start": self.anomaly_start.isoformat(),
                        "end":   self.anomaly_end.isoformat(),
                    }
                    self.anomaly_start = None
                    self.anomaly_end = None

                if self.websocket_server:
                    asyncio.get_running_loop().create_task(
                        self.websocket_server.broadcast_data(payload)
                    )

                self.chunk_50.clear()

            self.device_state["device_data"] = value
            self.last_data_time = datetime.now()

        except Exception as e:
            logger.error(f"error in notification handler: {e}")

    def handle_disconnect(self, client):
        logger.warning("device disconnected, attempting to reconnect...")
        
        try:
            for service in client.services:
                for char in service.characteristics:
                    if convertUUIDtoShortID(char.uuid) == "fff1":
                        asyncio.get_running_loop().create_task(
                            client.write_gatt_char(char.uuid, b"E", response=True)
                        )
                        break
        except:
            pass

        self.is_connected = False
        self.device_state["bluetooth_connected"] = False
        
        if self.websocket_server:
            try:
                asyncio.create_task(self.websocket_server.broadcast_data({
                    "type": "bluetooth_status",
                    "bluetooth_connected": False,
                    "timestamp": datetime.now().isoformat()
                }))
            except Exception as e:
                logger.error(f"failed to broadcast disconnect status: {e}")
        
        if self.diff_logger:
            try:
                self.diff_logger.close()
                self.diff_logger = None
                logger.info("session logger closed.")
            except Exception as e:
                logger.error(f"error closing logger: {e}")
        
        if not self._lock.locked():
            asyncio.create_task(self.attempt_reconnect())

    async def run_mock_stream(self):
        logger.info("virtual emulator: data stream task started")
        from trachsense_emulator import TrachSenseEmulator
        emulator = TrachSenseEmulator()
        
        loop_count = 0
        try:
            while self.is_connected and self.is_streaming and self.device_address == "EMULATOR":
                # cycle anomalies if enabled (every 200 packets / ≈20 seconds)
                if self.anomalous_mode:
                    if loop_count == 200:
                        emulator.pattern = "flatline"
                        logger.warning("simulating anomaly: flatline (decannulation)")
                    elif loop_count == 400:
                        emulator.pattern = "normal"
                        logger.info("simulating recovery: normal breathing")
                    elif loop_count == 600:
                        emulator.pattern = "blockage"
                        logger.warning("simulating anomaly: blockage")
                    elif loop_count == 800:
                        emulator.pattern = "normal"
                        logger.info("simulating recovery: normal breathing")
                        loop_count = 0 # restart cycle
                
                packet, on, off, diff = emulator.generate_packet()
                self.notification_handler(None, packet)
                await asyncio.sleep(0.1)
                loop_count += 1
        except asyncio.CancelledError:
            logger.warning("virtual emulator: task cancelled")
        except Exception as e:
            logger.error(f"virtual emulator error: {e}")
        finally:
            logger.info(f"virtual emulator: stream halted")

    async def stream_supervisor(self):
        """manages emulator stream lifecycle outside request scope."""
        while True:
            try:
                # only manage emulator in debug mode to mirror real device behavior
                if self.debug_mode and self.device_address == "EMULATOR":
                    should_run = self.is_connected and self.is_streaming
                    running = self.stream_task is not None and not self.stream_task.done()

                    if should_run and not running:
                        logger.info("virtual emulator: starting stream loop")
                        self.stream_task = asyncio.create_task(self.run_mock_stream())

                    if not should_run and running:
                        logger.info("virtual emulator: stopping stream loop")
                        self.stream_task.cancel()
                        try:
                            await self.stream_task
                        except asyncio.CancelledError:
                            pass
                        finally:
                            self.stream_task = None

                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                # shutdown: ensure any emulator task is stopped
                if self.stream_task and not self.stream_task.done():
                    self.stream_task.cancel()
                    try:
                        await self.stream_task
                    except asyncio.CancelledError:
                        pass
                break
            except Exception as e:
                logger.error(f"stream supervisor error: {e}")
                await asyncio.sleep(1)

    async def attempt_reconnect(self):
        while (
            not self.is_connected
            and self.reconnect_attempts < self.max_reconnect_attempts
        ):
            try:
                self.reconnect_attempts += 1
                self.device_state["reconnection_attempts"] = self.reconnect_attempts
                logger.info(f"reconnection attempt {self.reconnect_attempts}")

                await self.connect(self.device_address)
                if self.is_connected:
                    logger.info("successfully reconnected")
                    break
            except Exception as e:
                logger.error(f"reconnection failed: {e}")
                await asyncio.sleep(self.reconnect_delay)

    async def monitor_connection(self):
        while True:
            if self.is_connected and self.client:
                try:
                    await self.client.get_services()
                    self.last_data_time = datetime.now()
                except Exception as e:
                    logger.error(f"connection check failed: {e}")
                    self.is_connected = False
                    self.device_state["bluetooth_connected"] = False
                    await self.attempt_reconnect()
            await asyncio.sleep(5)

    def get_status(self):
        return {
            **self.device_state,
            "system_time": datetime.now().isoformat(),
            "db_connected": self.db_available,
            "bluetooth_manager_status": {
                "connected": self.is_connected,
                "last_data_time": (
                    self.last_data_time.isoformat()
                    if self.last_data_time
                    else None
                ),
                "reconnection_attempts": self.reconnect_attempts,
            },
        }

    async def start_stream(self):
        """Sends the 'S' (Start) command to the device and initializes logging."""
        if not self.is_connected:
            return False
            
        self.is_streaming = True
        logger.info("user requested stream start.")

        if self.device_address == "EMULATOR" and self.debug_mode:
            logger.info("virtual emulator: will run via supervisor")
            return True

        try:
            # Find the command characteristic (fff1)
            for service in self.client.services:
                for char in service.characteristics:
                    if convertUUIDtoShortID(char.uuid) == "fff1":
                        logger.info(f"sending start command 's' to {char.uuid}")
                        await self.client.write_gatt_char(char.uuid, b"S", response=True)
                        return True
            logger.warning("command characteristic fff1 not found")
            return False
        except Exception as e:
            logger.error(f"failed to send start command: {e}")
            return False

    async def stop_stream(self):
        """Sends the 'E' (End/Stop) command to the device."""
        self.is_streaming = False
        
        if not self.is_connected:
            return False

        try:
            for service in self.client.services:
                for char in service.characteristics:
                    if convertUUIDtoShortID(char.uuid) == "fff1":
                        logger.info(f"sending stop command 'e' to {char.uuid}")
                        await self.client.write_gatt_char(char.uuid, b"E", response=True)
                        return True
            return False
        except Exception as e:
            logger.error(f"failed to send stop command: {e}")
            return False

async def run_bluetooth_scan(debug_mode=False):
    logger.info("starting bluetooth scan...")
    try:
        # 5 second timeout for scan
        devices = await BleakScanner.discover(timeout=5.0)
    except Exception as e:
        logger.error(f"scan failed: {e}")
        devices = []
    results = [
        {
            "name": dev.name or "Unknown Device",
            "address": dev.address,
        }
        for dev in devices
    ]
    if debug_mode:
        results.append({
            "name": "TrachSense Emulator (VIRTUAL)",
            "address": "EMULATOR"
        })
    return results
