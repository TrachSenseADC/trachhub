import asyncio
from bleak import BleakScanner, BleakClient
import sys
from plot import plot_live_co2
from calibrate import calibrate
from CONSTANTS import A, B, C, GAS_READING
from logger import DataLoggerCSV


diff_logger = DataLoggerCSV("diff.csv")

# helper to convert full bluetooth uuid to short 16-bit hex if possible
def convertUUIDtoShortID(uuid_str):
    if "-" in uuid_str:
        # check if it matches the bluetooth base uuid
        if uuid_str.lower().endswith("-0000-1000-8000-00805f9b34fb"):
            return uuid_str[4:8]
    return uuid_str

# helper to build the 26-byte trachsense config packet
def build_config_packet(duration=3600, alert_level=1):
    packet = bytearray(26)
    packet[0] = 2 # mode
    
    # duration (bytes 1-4, uint32)
    import struct
    duration_bytes = struct.pack("<I", duration) # little-endian uint32
    packet[1:5] = duration_bytes
    
    # alert level (bytes 11-12, uint16)
    alert_bytes = struct.pack("<H", alert_level) # little-endian uint16
    packet[11:13] = alert_bytes
    
    # cr lf (bytes 24-25)
    packet[24] = 13 # cr
    packet[25] = 10 # lf
    
    return packet

# helper to parse trachsense data packets
def parse_packet(data):
    if len(data) < 8:
        return None
    import struct
    # timestamp (4 bytes, little-endian uint32, divided by 100000.0)
    timestamp_raw = struct.unpack("<I", data[0:4])[0]
    timestamp_s = timestamp_raw / 100000.0
    
    # on/off values (swapped endian-ness in the protocol)
    on_val = data[5] + (data[4] << 8)
    off_val = data[7] + (data[6] << 8)
    diff = on_val - off_val
    
    return {
        "time": timestamp_s,
        "on": on_val,
        "off": off_val,
        "diff": diff
    }

# helper to print data from notifications
def notification_handler(sender, data):
    # print(f"\n[RECEIVE] notification from {sender}", flush=True)
    sender_id = str(sender)
    if hasattr(sender, 'uuid'):
        sender_id = convertUUIDtoShortID(sender.uuid)
    
    parsed = parse_packet(data)
    if parsed:
        diff = parsed['diff']
        calibrated = calibrate(A, B, C, diff, GAS_READING)
        diff_logger.log({
            "time": parsed['time'],
            "on": parsed['on'],
            "off": parsed['off'],
            "diff": parsed['diff'],
        })
        plot_live_co2(calibrated)
        print(f"[{parsed['time']:.3f}s] on={parsed['on']} off={parsed['off']} diff={parsed['diff']}", flush=True)
    else:
        print(f"data from {sender_id}: {list(data)}", flush=True)

async def run():
    print("scanning for bluetooth devices...")
    devices = await BleakScanner.discover()
    
    if not devices:
        print("no devices found.")
        return

    # list found devices
    for i, device in enumerate(devices):
        print(f"{i}: {device.name or 'unknown'} ({device.address})")

    # get user choice
    try:
        selection = int(input("\nenter the number of the device to connect: "))
        if selection < 0 or selection >= len(devices):
            print("invalid selection.")
            return
    except ValueError:
        print("invalid input.")
        return

    target_device = devices[selection]
    print(f"connecting to {target_device.name or 'unknown'} ({target_device.address})...")

    async with BleakClient(target_device.address) as client:
        print(f"connected: {client.is_connected}")
        
        # list services and characteristics
        print("\ndiscovering services and characteristics:")
        write_char = None
        for service in client.services:
            short_service_id = convertUUIDtoShortID(service.uuid)
            print(f"\nservice: {short_service_id} (full: {service.uuid})")
            for char in service.characteristics:
                short_char_id = convertUUIDtoShortID(char.uuid)
                print(f"  characteristic: {short_char_id}, properties: {char.properties}")
                
                # store the first writable characteristic found (often where start commands go)
                if ("write" in char.properties or "write-without-response" in char.properties) and not write_char:
                    write_char = char

                # subscribe to notify/indicate characteristics
                if "notify" in char.properties or "indicate" in char.properties:
                    print(f"    subscribing to {short_char_id}...")
                    await client.start_notify(char.uuid, notification_handler)

        # dynamically find trachsense characteristics
        chars_by_short = {}
        for service in client.services:
            for char in service.characteristics:
                short_id = convertUUIDtoShortID(char.uuid)
                chars_by_short[short_id] = char

        # mapping for trachsense protocol
        # fff4: notify (streaming)
        # fff1: command ("S"/"E")
        # fff3: config (26-byte packet)
        
        streaming_char = chars_by_short.get("fff4")
        command_char   = chars_by_short.get("fff1")
        config_char    = chars_by_short.get("fff3")

        # allow manual start sequence
        if streaming_char:
            use_protocol = input(f"\ntrachsense device detected (fff4). start data stream sequence? (y/n): ").strip().lower()
            if use_protocol == 'y':
                try:
                    # 1. build and send config packet
                    if config_char:
                        print(f"sending 26-byte config packet to fff3 ({config_char.uuid})...")
                        config_packet = build_config_packet()
                        await client.write_gatt_char(config_char.uuid, config_packet, response=True)
                    else:
                        print("fff3 (config char) not found. skipping config step...")
                    
                    # 2. send start command 'S'
                    if command_char:
                        print(f"sending start command 'S' to fff1 ({command_char.uuid})...")
                        await client.write_gatt_char(command_char.uuid, b"S", response=True)
                        print("data stream triggered.")
                    else:
                        print("fff1 (command char) not found. cannot start stream.")
                        
                except Exception as e:
                    print(f"failed to start stream: {e}")
        else:
            # allow manual write fallback if not a recognized trachsense device
            print("\nno trachsense streaming char (fff4) found or skipping protocol.")
            cmd_hex = input("enter hex command to write (or leave empty to skip): ").strip()
            if cmd_hex:
                target_char_id = input("enter short ID to write to: ").strip()
                target_char = chars_by_short.get(target_char_id)
                if target_char:
                    try:
                        await client.write_gatt_char(target_char.uuid, bytes.fromhex(cmd_hex), response=True)
                        print("write successful.")
                    except Exception as e:
                        print(f"failed: {e}")

        print("\nreading data. press ctrl+c to stop.", flush=True)
        try:
            count = 0
            while True:
                await asyncio.sleep(1)
                count += 1
                if count % 5 == 0:
                    print(f"waiting for data... (active for {count}s)", flush=True)
        except KeyboardInterrupt:
            print("\nstopping...")
            # send stop command 'E'
            if command_char:
                try:
                    print(f"sending stop command 'E' to fff1...")
                    await client.write_gatt_char(command_char.uuid, b"E", response=True)
                except:
                    pass

            # stop notifications
            for char in chars_by_short.values():
                if "notify" in char.properties:
                    try:
                        await client.stop_notify(char.uuid)
                    except:
                        pass
            print("disconnected.")

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
