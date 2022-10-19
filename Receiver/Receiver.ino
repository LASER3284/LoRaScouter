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


void setup() {
  Serial.begin(9600);
  while (!Serial);

  Serial.println("LoRa Receiver");
  LoRa.setPins(SS, RST, DI0);
  if (!LoRa.begin(BAND, PABOOST)) {
    Serial.println("Starting LoRa failed!");
    while (1);
  }

  LoRa.onReceive(onReceive);
  LoRa.receive();
  
  LoRa.enableCrc();
}

void loop() {

}

void onReceive(int packetSize) {
  // Read packet and then send out the packet via serial
  for (int i = 0; i < packetSize; i++) {
    Serial.write((char)LoRa.read());
  }
}