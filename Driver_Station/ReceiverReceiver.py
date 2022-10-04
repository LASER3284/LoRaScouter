import argparse
import json
from typing import Dict, List, Union
import serial
import serial.tools.list_ports
import traceback
import signal   
import time
import sys

_SCOUTING_PACKET_EOF = b"\x00\xFF\x32\x84\xFF\x00"

def handleScoutingData(data: Dict[str, Dict[str, Union[List[Dict[str, Union[str, bool, int, float]]], str]]]):
    print(f"Received new scout data...")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="auto")
    parser.add_argument("--baud", default=9600, type=int)
    args = parser.parse_args()

    port = args.port

    while True:
        if args.port == "auto":
            while port == "auto":
                ports = list(serial.tools.list_ports.comports())
                if ports is None or len(ports) <= 0:
                    print(f"Unable to find COM port for serial device...")
                port = ports[0]
        
        print(f"Detected/found serial device on COM port: '{port}'")

        serial_device: serial.Serial = None # type: ignore
        while serial_device is None:
            try:
                serial_device = serial.Serial(port[0], args.baud, timeout=10.50)
                serial_device.isOpen()
            except IOError: # If the port is already opened, close it and open it again and then try again
                if serial_device is not None:
                    serial_device.close()
                    serial_device.open()
                print("COM port was already open, was closed and opened again!")
                time.sleep(5)

        print(f"Opened serial device on COM port...")

        try:
            while True:
                print(f"Waiting for serial data...")
                if serial_device.inWaiting():
                    data = serial_device.read_until(_SCOUTING_PACKET_EOF)
                    if data is None: 
                        continue
                    data = data.strip(_SCOUTING_PACKET_EOF)
                    hex_data = " ".join([hex(byte) for byte in data])
                    print(f"Received data (length: {len(data)}): {data} :: {hex_data}")
                    
                    json_data = json.loads(data.decode('ascii'))
                    handleScoutingData(json_data)
                time.sleep(1.25)
        except Exception:
            traceback.print_exc()
            continue



if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda x, y: sys.exit(0))

    main()