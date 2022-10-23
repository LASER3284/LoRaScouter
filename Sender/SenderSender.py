import os
import argparse
import time
import traceback
import logging
import json
import threading
import serial
import hashlib
import serial.tools.list_ports
from typing import Any, Dict, List, Union
from ppadb.client import Client as AdbClient

_ARGUMENTS_PROMPT = f"Enter a command to run\n\t- `send`: Send the data to the LoRa to send to the pits\n\t- `save`: Save the full scouting data for importing onto the receiver station.\n\t- `wipe`: Wipe all cached device data\n\t- `clear`: Clear all total known event data\n\t- `exit`: Exit the scouting program...\n"
_SCOUTING_EOF = b"\xFF\x32\x84\xFF"

class BackgroundADBWatcher(threading.Thread):
    """A simple background task that monitors ADB devices on the USB and updates the scouting dictionary."""

    perDeviceScoutingData: Dict[str, Dict[str, Dict[str, Any]]] = {}
    metricMapping: Dict[str, str] = {}

    def __init__(self, client: AdbClient, export_path: str, cache_path: str = "./scouting_cache.json"):
        super().__init__()
    
        self.perDeviceScoutingData = {}
        self.client = client
        self.export_path = export_path
        self.cache_path = cache_path

        self.event_lock = threading.Lock()
        self._stop_event = threading.Event()

        self.cachedScoutingData: List[str] = []
        if os.path.exists(self.cache_path):
            with open(self.cache_path, "r") as f:
                data = json.load(f)
                self.cachedScoutingData = data['cache']
                self.metricMapping = data['template']

    """Runs the task that monitors ADB devices"""
    def run(self, *args, **kwargs):
        found_devices: List[str] = []
        while not self.stopped():
            try:
                devices = self.client.devices()

                with self.event_lock:
                    for device in devices:
                        # If we've already found the device, just skip printing info on it
                        if device.serial not in found_devices:
                            print(f"Discovered device: {device.serial}")
                            found_devices.append(device.serial)

                        result = device.shell(f'cat \"{self.export_path}\"').strip()
                        
                        # Make sure that we have the event lock so we can properly update the JSON
                        try:
                            self.perDeviceScoutingData.update({ device.serial : json.loads(result) })
                        except ValueError:
                            # json.loads(...) will throw a value error if the JSON is malformed or if the JSON doesn't exist
                            continue
                    # Remove the device if it gets disconnected
                    for serial in found_devices:
                        if serial not in [d.serial for d in devices]:
                            found_devices.remove(serial)
                
                time.sleep(1.5)
            except RuntimeError as err:
                # We have to do the funky cast to a string in order to actually get the error message.
                # It's kinda wonky but lol python
                if ("The remote computer refused the network connection" in str(err)):
                    yn = input(f"ADB is not running... Please start ADB or type Y: ").strip()
                    if yn.lower() == "y":
                        os.system(f"adb start-server")
                    else:
                        time.sleep(5)
                else:
                    # Just sit and wait for a bit after an exception
                    traceback.print_exc()
                    time.sleep(1.5)
            except:
                # See above comment
                traceback.print_exc()
                time.sleep(1.5)

    def saveToDisk(self) -> bool:
       # Acquire the lock so that way we can make sure we merge everything properly
        with self.event_lock:
            # { "teams": { "Team": [{"metric": "value"}], "template": { "metric_id" : "metric_name" } }
            combinedScoutingData: Dict[str, Dict[str, Union[List[Dict[str, Union[str, bool, int, float]]], str]]] = {
                "teams": {},
                "template": {}
            }

            if os.path.exists(os.path.join(os.path.dirname(self.cache_path), "saved_scouts.json")):
                combinedScoutingData = json.load(open(os.path.join(os.path.dirname(self.cache_path), "saved_scouts.json")))
                self.metricMapping = combinedScoutingData["template"] # type: ignore

            for idx, (device_serial, spare) in enumerate(self.perDeviceScoutingData.items()):
                print(f"[{idx+1}] Combining Scouting Data...")
                for team, scouts in spare['teams'].items():
                    print(f"\t[{idx+1}] Handling Team #{team}")

                    shortened_team_scout: List[Dict[str, Union[str, bool, int, float]]] = []
                    
                    for scout in scouts:
                        shortened_match_scout: Dict[str, Union[str, bool, int, float]] = {}
                        metric_count = len(list(scout['metrics'].items()))
                        # We need to use the metric ID so that way it doesn't overwrite in the JSON
                        for metric_id, metric in scout['metrics'].items():
                            # Technically this is playing it risky because the metric ID isn't deterministic
                            # For now, lets use this solution, the chances of a complete overlap are very low.
                            metric_id = metric_id[:metric_count // 2]

                            # Force metrics with the same name to have the same metric id
                            if metric['name'] in self.metricMapping.values():
                                metric_id = list(self.metricMapping.keys())[list(self.metricMapping.values()).index(metric['name'])]
                            # Add the metric ID to the metric mapping if it's not there
                            elif metric_id not in self.metricMapping.keys():
                                self.metricMapping.update({ metric_id : metric['name']})
                            # Update the match scout with the metric ID to value
                            # This is mainly to remove various junk that I don't care about
                            shortened_match_scout.update({ metric_id : metric['value'] })
                        
                        # We need to check the shortened match scout due to the way the file is saved
                        scout_hash = hashlib.md5(json.dumps(shortened_match_scout).encode('ascii')).hexdigest()
                        duplicated = False

                        for t, t_s in combinedScoutingData['teams'].items():
                            hashes = [hashlib.md5(json.dumps(s).encode('ascii')).hexdigest() for s in t_s]
                            if scout_hash in hashes:
                                duplicated = True
                                break
                        if duplicated:
                            continue
                        
                        # Add the match scout to the team scout list
                        shortened_team_scout.append(shortened_match_scout)
                                            
                    # If the team hasn't already been scouted by another device, *add* it to the dictionary
                    # If the team has been scouted by another device, append to that team's scout list rather than overwriting the dictionary.
                    if team not in combinedScoutingData['teams']:
                        combinedScoutingData['teams'].update({team : shortened_team_scout})
                    else:
                        combinedScoutingData['teams'][team] += shortened_team_scout  # type: ignore
            
            combinedScoutingData['template'] = metricMapping # type: ignore

            with open(os.path.join(os.path.dirname(self.cache_path), "saved_scouts.json"), "w+") as f:
                json.dump(combinedScoutingData, f, indent=4)

        return True

    def sendViaSerial(self) -> bool:
        # Acquire the lock so that way we can make sure we merge everything properly
        with self.event_lock:
            # { "teams": { "Team": [{"metric": "value"}], "template": { "metric_id" : "metric_name" } }
            combinedScoutingData: Dict[str, Dict[str, Union[List[Dict[str, Union[str, bool, int, float]]], str]]] = {
                "teams": {},
                "template": {}
            }
            
            for idx, (device_serial, spare) in enumerate(self.perDeviceScoutingData.items()):
                print(f"[{idx+1}] Combining Scouting Data...")
                for team, scouts in spare['teams'].items():
                    print(f"\t[{idx+1}] Handling Team #{team}")

                    shortened_team_scout: List[Dict[str, Union[str, bool, int, float]]] = []
                    
                    for scout in scouts:
                        scout_hash = hashlib.md5(json.dumps(scout).encode('ascii')).hexdigest()
                        if scout_hash in self.cachedScoutingData:
                            continue

                        shortened_match_scout: Dict[str, Union[str, bool, int, float]] = {}
                        metric_count = len(list(scout['metrics'].items()))
                        # We need to use the metric ID so that way it doesn't overwrite in the JSON
                        for metric_id, metric in scout['metrics'].items():
                            # Technically this is playing it risky because the metric ID isn't deterministic
                            # For now, lets use this solution, the chances of a complete overlap are very low.
                            metric_id = metric_id[:metric_count // 2]

                            # Force metrics with the same name to have the same metric id
                            if metric['name'] in self.metricMapping.values():
                                metric_id = list(self.metricMapping.keys())[list(self.metricMapping.values()).index(metric['name'])]
                            # Add the metric ID to the metric mapping if it's not there
                            elif metric_id not in self.metricMapping.keys():
                                self.metricMapping.update({ metric_id : metric['name']})
                            
                            # Convert lists (stopwatches) to strings for better parsing (and OTA space)
                            if isinstance(metric['value'], list):
                                metric['value'] = ",".join([str(v) for v in metric['value']])

                            # Update the match scout with the metric ID to value
                            # This is mainly to remove various junk that we don't care about
                            shortened_match_scout.update({ metric_id : metric['value'] })
                        
                        # Add the match scout to the team scout list
                        shortened_team_scout.append(shortened_match_scout)
                        
                        self.cachedScoutingData.append(scout_hash)
                    
                    # If the team hasn't already been scouted by another device, *add* it to the dictionary
                    # If the team has been scouted by another device, append to that team's scout list rather than overwriting the dictionary.
                    if team not in combinedScoutingData['teams']:
                        combinedScoutingData['teams'].update({team : shortened_team_scout})
                    else:
                        combinedScoutingData['teams'][team] += shortened_team_scout  # type: ignore
            
            combinedScoutingData['template'] = self.metricMapping # type: ignore

        # Do this once we release the lock so the wipe method can actually wipe
        self.wipe()

        if len(combinedScoutingData['template']) == 0 or all([len(match_scouts) == 0 for team, match_scouts in combinedScoutingData['teams'].items()]):
            print(f"No new data received since last clear... Skipping data send...")
            return True

        for team, match_scouts in list(combinedScoutingData['teams'].items()):
            if len(match_scouts) <= 0:
                combinedScoutingData['teams'].pop(team)

        print(f"Finding LoRa serial device...")
        # Now we need to send the JSON data to the serial device connected (LoRa Sender).
        ports = []

        while ports is None or len(ports) <= 0:
            ports = list(serial.tools.list_ports.comports())
            for idx, port in enumerate(ports):
                # Make sure to ignore Android/SAMSUNG devices... 
                if "Feather 32u4" not in str(port):
                    ports.pop(idx)
        ports = sorted(ports, key=lambda p: str(p))
        port = ports[0]

        print(f"Detected serial device on port: '{port}'...")
        serial_device = serial.Serial(port[0], 9600, timeout=15.0)
        
        # The separators argument makes sure that the final output JSON is ideally very slim
        # (aka it strips off extra whitespace on lists and key/value pairs).
        json_dump = json.dumps(combinedScoutingData, separators=(',', ':'))
        
        packet = json_dump.encode('utf-8').strip(b"\x00") + _SCOUTING_EOF
        
        print(f"Packet Size: {len(packet)}")

        step = 128
        for i in range(0, len(packet), step):
            print(f"\t[{i // step}] Sending split serial packet...")
            serial_device.write(packet[i:i+step])
            serial_device.read_until(_SCOUTING_EOF)
        print(f"Serial data sent...")        
        with open(self.cache_path, "w+") as f:
            json.dump({
                'cache': self.cachedScoutingData,
                'template': self.metricMapping
            }, f, indent=4)

        return True

    def wipe(self) -> bool:
        # Acquire the lock so it gets deleted properly
        with self.event_lock:
            self.perDeviceScoutingData = {}
            time.sleep(0.5)
        return True

    def clear(self) -> bool:
        # Once again, grab the event lock so that way we can safely delete the cache
        with self.event_lock:
            self.cachedScoutingData.clear()
            with open(self.cache_path, "w+") as f:
                json.dump({
                    'cache': self.cachedScoutingData,
                    'template': self.metricMapping
                }, f, indent=4)
        return True

    def stop(self):
        self._stop_event.set()

    def stopped(self):
        return self._stop_event.is_set()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5037)
    parser.add_argument("--debug", action="store_true", default=False)
    parser.add_argument("--device-path", type=str, default="/storage/emulated/0/Download/Robot Scouter/RadioScout.json")

    args = parser.parse_args()

    if args.debug:
        print(f"Setting ppadb to debug mode...")
        logging.getLogger("ppadb").setLevel(logging.DEBUG)


    print(f"Initializing ADB Client...")
    client = AdbClient(host=args.host, port=args.port)

    try:
        client.devices()
    except RuntimeError as err:
        # We have to do the funky cast to a string in order to actually get the error message.
        # It's kinda wonky but lol python
        if ("The remote computer refused the network connection" in str(err)):
            yn = input(f"ADB is not running... Please start ADB or type Y: ").strip()
            if yn.lower() == "y":
                os.system(f"adb start-server")
            else:
                return
    
    # Start the background task that repeatedly monitors all devices attached.
    backgroundWatcher: BackgroundADBWatcher = BackgroundADBWatcher(client=client, export_path=args.device_path)
    backgroundWatcher.start()
    
    command: str = input(_ARGUMENTS_PROMPT).lower()

    while command != "exit":
        if command == "send":
            backgroundWatcher.sendViaSerial()
        elif command == "save":
            backgroundWatcher.saveToDisk()
        elif command == "wipe":
            backgroundWatcher.wipe()
        elif command == "clear":
            backgroundWatcher.clear()
        else:
            print(f"Unknown command... Please try again")
            time.sleep(0.25)
        
        command = input(_ARGUMENTS_PROMPT).lower()


    print(f"Stopping background watcher thread...")
    backgroundWatcher.stop()
    backgroundWatcher.join(timeout=5)

if __name__ == "__main__":
    # We need to run the main thread asynchronously so that way we can poll each device on the USB bus individually.
    main()