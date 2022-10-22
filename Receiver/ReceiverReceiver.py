import argparse
import hashlib
import json
from typing import Dict, List, Union
import serial
import serial.tools.list_ports
import traceback
import signal   
import time
import os
import csv
import sys

_SCOUTING_PACKET_EOF = b"\x00\xFF\x32\x84\xFF\x00"
_COMBINED_SCOUTING_JSON = "./combined_scouts.json"
_COMBINED_SCOUTING_CSV = "./combined_scouts.csv"

def handleScoutingData(data: Dict[str, Dict[str, Union[List[Dict[str, Union[str, bool, int, float]]], str]]]):
    print(f"Received new scout data...")
    combined_scouts: Dict[str, Dict[str, Union[List[Dict[str, Union[str, bool, int, float]]], str]]] = {"teams": {}}
    if os.path.exists(_COMBINED_SCOUTING_JSON):
        with open(_COMBINED_SCOUTING_JSON, "r+") as f:
            combined_scouts = json.load(f)

    for team, scouts in data['teams'].items():
        for scout in scouts:
            scout_hash = hashlib.md5(json.dumps(scout).encode('utf-8')).hexdigest()
            if team in combined_scouts["teams"]:
                hashes = [hashlib.md5(json.dumps(s).encode('ascii')).hexdigest() for s in combined_scouts["teams"][team]]
                # It looks like we already have this match data scouted, skip it
                if scout_hash in hashes:
                    continue
            
                combined_scouts["teams"][team].append(scout) # type: ignore
            else:
                combined_scouts["teams"].update({ team : [scout]}) # type: ignore
    
    if "template" not in combined_scouts and "template" in data:
        combined_scouts["template"] = data["template"]

    with open(_COMBINED_SCOUTING_JSON, "w+") as f:
        json.dump(combined_scouts, f, indent=4)

    with open(_COMBINED_SCOUTING_CSV, "w+", newline='', encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(['Team Number', *[value for value in combined_scouts["template"].values()]])
        
        for team, scouts in combined_scouts['teams'].items():
            for scout in scouts:
                # This is mainly just to guarantee that the CSV rows have the same order as the header.
                # In theory, it always should, but it can't really hurt.
                ordered_values = [scout[x] for x in combined_scouts["template"].keys()] # type: ignore
                writer.writerow([team, *ordered_values])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="auto")
    parser.add_argument("--baud", default=9600, type=int)
    parser.add_argument("--timeout", default=35.00, type=float)

    parser.add_argument("--import-file", type=str, default=None)
    args = parser.parse_args()

    # Change what we're doing based on the import flag
    if args.import_file is not None:
        if not os.path.exists(args.import_file):
            raise Exception(f"Unable to find file at {args.import_file}!!")
        with open(args.import_file, "r+") as file:
            data = json.load(file)
            handleScoutingData(data)
        
        return

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
                serial_device = serial.Serial(port[0], args.baud, timeout=args.timeout)
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
                    if len(data) <= len(_SCOUTING_PACKET_EOF):
                        continue
                    
                    data = data.strip(_SCOUTING_PACKET_EOF)
                    hex_data = " ".join([hex(byte) for byte in data])
                    print(f"Received data (length: {len(data)}): {data} :: {hex_data}")
                    
                    if not data.endswith(_SCOUTING_PACKET_EOF):
                        print(f"Received malformed data... Missing packet EOF")
                        continue

                    json_data = json.loads(data.decode('ascii'))
                    handleScoutingData(json_data)
                time.sleep(1.25)
        except Exception:
            traceback.print_exc()
            continue



if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda x, y: sys.exit(0))

    main()