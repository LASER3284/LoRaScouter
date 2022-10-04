# Radio Scouter

This is the official code release for our [LoRa](https://lora-alliance.org/) based scouting system. The goal of this project was to create a wireless (and hotspot/wireless data free) communication setup that does not interfere with the *FIRST®* rules for wireless interference with their FMS system.

## How Does It Work?

The main setup is like so:
- The stands (scouters) have modified versions of SUPERCILEX's [Robot-Scouter](https://github.com/SUPERCILEX/Robot-Scouter) app installed onto their phones (or a school/team provided device). The main difference is that our fork of it adds in a custom export feature that exports all scouting data to one JSON file.
- These stands then plug into a laptop running in the stands running the `SenderSender.py` python script inside the `Sender` folder.
  * This script uses [ADB](https://developer.android.com/studio/command-line/adb) in order to pull the exported JSON file from the scouting devices. 
  * Then it combines all of this scouting data into one JSON file that is minified and sent via serial to the main LoRa sender device.
    - This data is sent in one buffer and includes an EOF marker of `0x00 0xFF 0x32 0x84 0xFF 0x00` (This was picked because it should be fairly unique, it could probably be shortened down).
- The main LoRa sender device is a [BSFrance LoRa32u4 II](/LoRa32u4-lora32u4ii-documents/Datasheet_LoRa32u4II_1.1.pdf) device
  * This is a simple program setup using the Arduino IDE and the [arduino-LoRa](https://github.com/sandeepmistry/arduino-LoRa) Arduino library.
  * This script reads from the built-in Serial interface (which has a maximum input buffer size of 64 bytes) until it receives the EOF marker as mentioned before.
  * Under the hood, this chip communicates with a SX1276 transceiver, which in LoRa mode, has a specific 256 byte buffer. But due to extra data in the LoRa protocol, a few extra bytes are used due to headers. Due to this, each packet is cut to a length of 128 + header size (you could improve this amount by calculating the size of the header for each packet). 
    - The original serial data gets split into 128 chunks, with a 500ms delay between each LoRa packet.
- Then, attached to your driver station (or wherever), this data is received by another BSFrance LoRa32u4 II module running the `Receiver/Receiver.ino` Arduino program.
   * This script more or less operates in the same process as the sender, but in reverse; This script practically just sends the data to the host PC via Serial as soon as it receives it (usually every other 500ms).
- This driver station/pit laptop is running the `Driver_Station/ReceiverReceiver.py` (you'll notice a trend with the naming), which automatically monitors the serial port.
   * NOTE: If you decide to attach this to your driver station laptop, please note that under the rules, you *cannot* have any form of wireless communication at the field itself. It's advised to just unplug the LoRa module from your laptop entirely.
   * This python script automatically monitors the serial ports (at 9600 baud rate), reading data until it sees that same EOF structure from earlier.
   * Then this JSON data can be custom processed and loaded through the power of LoRa!
