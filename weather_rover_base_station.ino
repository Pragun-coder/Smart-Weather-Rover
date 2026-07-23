#include <SPI.h>
#include <nRF24L01.h>
#include <RF24.h>


RF24 radio(3,10);

const byte address[6]="00001";



struct SensorData
{
  float temp;
  float hum;

  int rain;
  int soil;

  float lat;
  float lng;
};


SensorData data;

char text[32];



void setup()
{

  Serial.begin(9600);


  radio.begin();

  radio.openWritingPipe(address);

  radio.openReadingPipe(1,address);

  radio.setPALevel(RF24_PA_LOW);

  radio.setDataRate(RF24_250KBPS);

  radio.startListening();


  Serial.println("UNO READY");

}



void loop()
{


// ================= RECEIVE SENSOR DATA =================

if(radio.available())
{

  radio.read(&data,sizeof(data));


  Serial.print(data.temp);

  Serial.print(",");


  Serial.print(data.hum);

  Serial.print(",");


  Serial.print(data.rain);

  Serial.print(",");


  Serial.print(data.soil);

  Serial.print(",");


  Serial.print(data.lat,6);

  Serial.print(",");


  Serial.println(data.lng,6);

}



// ================= RECEIVE COMMAND FROM PYTHON =================

if(Serial.available())
{

String cmd=Serial.readStringUntil('\n');

cmd.trim();


memset(text,0,sizeof(text));

cmd.toCharArray(text,sizeof(text));



radio.stopListening();


bool ok=radio.write(

&text,

sizeof(text)

);



radio.startListening();



Serial.print("CMD:");

Serial.print(cmd);

Serial.print(" -> ");


if(ok)

Serial.println("SENT");

else

Serial.println("FAILED");



delay(20);

}


}


