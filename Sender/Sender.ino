#include <SPI.h>
#include <LoRa.h>


//LoR32u4II 868MHz or 915MHz (black board)
#define SCK     15
#define MISO    14
#define MOSI    16
#define SS      8
#define RST     4
#define DI0     7
#define BAND    915E6
#define PABOOST true 

int counter = 0;

String data = "";
String serialEOF = "\x00\xFF\x32\x84\xFF\x00";

void setup() {
  Serial.begin(9600);

  while (!Serial);
  Serial.println("LoRa Sender");
  LoRa.setPins(SS,RST,DI0);
  
  if (!LoRa.begin(BAND,PABOOST)) {
    Serial.println("Starting LoRa failed!");
    while (1);
  }

  LoRa.enableCrc();

  // Set a timeout of 5 seconds.
  Serial.setTimeout(5000);
}

void loop() {

  if(Serial.available() > 0) {
    // This pretty much builds up the packet until the data ends with the standard EOF
    while(Serial.available()) {
      data += ((char)Serial.read());
    }
  }

  if(data.indexOf(serialEOF) != -1) {
    Serial.print("Received data: '");
    Serial.print(data);
    Serial.println("'");

    int dataIdx = 0;
    int split_count = (data.length() / 128) + (data.length() % 128 > 1 ? 1 : 0);

    for(int packet_count = 0; packet_count < split_count; packet_count++) { 
      Serial.print("Transmitting packet #");
      Serial.println(packet_count);
        
      LoRa.beginPacket();
        
      for(int i = 0; i < 128; i++) {
        if(dataIdx <= data.length()) {
          LoRa.write(data.charAt(dataIdx));
          dataIdx++;
        }
      }
        
      LoRa.endPacket();
        
      delay(500);      
    }

    data = "";

    while(Serial.available()) {
      Serial.read();
    }
  }
}
