#include <SPI.h>
#include <LoRa.h>


//LoR32u4II 868MHz or 915MHz (black board)
#define SCK     15
#define MISO    14
#define MOSI    16
#define SS      8
#define RST     4
#define DI0     7
#define BAND    868E6  // 915E6
#define PABOOST true 


void setup() {
  Serial.begin(9600);
  while (!Serial);

  Serial.println("LoRa Sender");
  LoRa.setPins(SS, RST, DI0);
  if (!LoRa.begin(BAND, PABOOST)) {
    Serial.println("Starting LoRa failed!");
    while (1);
  }
  
  LoRa.enableCrc();
}

void loop() {
  if (Serial.available() > 0) { 
    Serial.println("Received packet... Sending packet...");
    LoRa.beginPacket();
    while(Serial.available() > 0) {
      LoRa.write(Serial.read());
    }
    LoRa.endPacket();
  }
}
