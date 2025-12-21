import time
import struct
import random
import math

class TrachSenseEmulator:
    """
    emulates the trachsense 8-byte data protocol over bluetooth.
    used for testing the dashboard and logging without real hardware.
    """
    
    def __init__(self):
        self.start_time = time.time()
        self.pattern = "normal" # normal, shallow, rapid, anomaly, blockage, flatline
        
    def generate_packet(self):
        """
        builds an 8-byte packet matching the trachsense protocol:
        [0-3]: timestamp (uint32, units of 1/100000s)
        [4-5]: on_val (uint16, big-endian)
        [6-7]: off_val (uint16, big-endian)
        """
        # calculate elapsed time in protocol units
        elapsed_s = time.time() - self.start_time
        timestamp_raw = int(elapsed_s * 100000)
        
        # simulate breathing signal (sinusoidal)
        # on_val increases when breathing in, off_val is relatively steady
        freq = self.get_frequency()
        amplitude = self.get_amplitude()
        
        # base signal + oscillation
        base = 2000
        variation = amplitude * math.sin(2 * math.pi * freq * elapsed_s)
        
        on_val = int(base + variation)
        off_val = int(base - variation * 0.1) # slight inverse oscillation for realism
        
        # packing: <I is little-endian uint32, >H is big-endian uint16
        # note: parse_packet in app.py manually reconstructs on/off from bytes
        # so we pack them in the order app.py expects: data[4]<<8 + data[5]
        packet = bytearray(8)
        
        # timestamp (little endian uint32)
        packet[0:4] = struct.pack("<I", timestamp_raw)
        
        # on_val (big endian uint16 manually mapped to 4,5)
        packet[4] = (on_val >> 8) & 0xFF
        packet[5] = on_val & 0xFF
        
        # off_val (big endian uint16 manually mapped to 6,7)
        packet[6] = (off_val >> 8) & 0xFF
        packet[7] = off_val & 0xFF
        
        return packet, on_val, off_val, on_val - off_val

    def get_frequency(self):
        if self.pattern == "rapid": return 0.8
        if self.pattern == "shallow": return 0.4
        if self.pattern == "blockage": return 0.6 # slightly faster but very weak
        return 0.3 # normal

    def get_amplitude(self):
        if self.pattern == "shallow": return 50
        if self.pattern == "anomaly": return 500 # huge spike
        if self.pattern == "blockage": return 15 # very low RMS
        if self.pattern == "flatline": return 0 # decannulation
        return 200 # normal

    def run(self, interval=0.1):
        print(f"starting trachsense emulation (mode: {self.pattern})")
        print("press ctrl+c to stop\n")
        print(f"{'time':<10} | {'on':<6} | {'off':<6} | {'diff':<6}")
        print("-" * 40)
        
        try:
            while True:
                packet, on, off, diff = self.generate_packet()
                elapsed = time.time() - self.start_time
                print(f"{elapsed:>8.3f}s | {on:>6} | {off:>6} | {diff:>6}", end='\r')
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\nemulation stopped.")

if __name__ == "__main__":
    emulator = TrachSenseEmulator()
    # allow selecting pattern via arg or simple prompt if interactive
    import sys
    if len(sys.argv) > 1:
        emulator.pattern = sys.argv[1]
    
    emulator.run()
