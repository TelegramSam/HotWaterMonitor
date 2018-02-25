#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include "ArduinoJson.h"
#include <OneWire.h>
#include <DallasTemperature.h>
#include <Adafruit_NeoPixel.h>

#define ONE_WIRE_BUS D4
#define TEMPERATURE_PRECISION 12

#define FLOW_PIN D6

#define LED_PIN RX

#define SUFFICIENT_FLOW_LITERS 0.3
#define SUFFICIENT_FLOW_MEASUREMENT_COUNT 24 // 4 minutes, 10 sec intervals
#define SPECIFIC_HEAT_OF_WATER 4.186

#define REPORTING_INTERVAL_SECONDS 10

// start config
#define WATTAGE 3300
#define HEAT_EFFICIENCY 0.85 //85?

char *ssid="--yourssid--";
char *password="--yourpassword--";

char* api_key="--yourapikey--";
char* api_path="https://--yourhost--.execute-api.us-east-1.amazonaws.com/prod/HotWater_Update";
// end config

unsigned long reporting_interval_millis = REPORTING_INTERVAL_SECONDS * 1000;

// setup neopixel interface
Adafruit_NeoPixel pixels = Adafruit_NeoPixel(1, LED_PIN, NEO_GRB + NEO_KHZ800);

// Setup a oneWire instance to communicate with any OneWire devices (not just Maxim/Dallas temperature ICs)
OneWire oneWire(ONE_WIRE_BUS);

// Pass our oneWire reference to Dallas Temperature. 
DallasTemperature sensors(&oneWire);

// arrays to hold device addresses
DeviceAddress output_thermometer_address;
DeviceAddress input_thermometer_address;

HTTPClient http;

StaticJsonBuffer<200> jsonBuffer;
JsonObject& iot_bundle = jsonBuffer.createObject();
JsonObject& iot_bundle_state = iot_bundle.createNestedObject("state");
JsonObject& iot_bundle_state_reported = iot_bundle_state.createNestedObject("reported");

unsigned long last_report_millis = 0; 

unsigned int consecutive_sufficient_flow_measurements;
float measured_input_c = 16.1;
float min_input_c;
float measured_output_c = 33.1; 
float max_output_c;

float liter_deficit = 0;
float liter_degree_deficit = 0;
float liter_degrees_per_second = (WATTAGE * HEAT_EFFICIENCY) / (SPECIFIC_HEAT_OF_WATER * 1000);

volatile unsigned int flow_count;

// ICACHE_RAM_ATTR: see ISR under Other causes of crashes:
//    https://github.com/esp8266/Arduino/blob/master/doc/faq/a02-my-esp-crashes.rst

void ICACHE_RAM_ATTR flow_counter(){
  flow_count += 1;
}

uint32_t color_status_ok = pixels.Color(0,150,0);
uint32_t color_status_warning = pixels.Color(255,165,0);
uint32_t color_status_error = pixels.Color(150,0,0);


void set_status_led(uint32_t c){
  Serial.println("setting color");
  // updating the neopixel color will briefly suspend the interrupts needed for flow meter counting. 
  // We keep updating to a minimum to reduce the chance of a problem.
  pixels.setPixelColor(0, c);
  pixels.show(); // This sends the updated pixel color to the hardware.
}

// function to print a device address
void printAddress(DeviceAddress deviceAddress)
{
  for (uint8_t i = 0; i < 8; i++)
  {
    // zero pad the address if necessary
    if (deviceAddress[i] < 16) Serial.print("0");
    Serial.print(deviceAddress[i], HEX);
  }
}

void setup() {
  Serial.begin(115200);
  delay(10);

  // This initializes the NeoPixel library.
  pixels.begin(); 
  set_status_led(color_status_warning);

  // Start up the library
  sensors.begin();
  // autodetect addresses of sensors
  if (!sensors.getAddress(input_thermometer_address, 0)) Serial.println("Unable to find address for Device 0"); 
  if (!sensors.getAddress(output_thermometer_address, 1)) Serial.println("Unable to find address for Device 1"); 

  // set the resolution to 12 bit
  sensors.setResolution(input_thermometer_address, TEMPERATURE_PRECISION);
  sensors.setResolution(output_thermometer_address, TEMPERATURE_PRECISION);

  //switch the sensors if we detected wrong
  sensors.requestTemperatures();
  float inputC = sensors.getTempC(input_thermometer_address);
  float outputC = sensors.getTempC(output_thermometer_address);
  if(inputC > outputC){
    Serial.println("switching temp sensors");
    // probably reversed. Switch addresses
    if (!sensors.getAddress(input_thermometer_address, 1)) Serial.println("Unable to find address for Device 0"); 
    if (!sensors.getAddress(output_thermometer_address, 0)) Serial.println("Unable to find address for Device 1"); 
  }

  Serial.print("Input Temp Address: ");
  printAddress(input_thermometer_address);
  Serial.println();
  
  Serial.print("Output Temp Address: ");
  printAddress(output_thermometer_address);
  Serial.println();

  // set up flow pulse counter
  flow_count = 0;
  attachInterrupt(digitalPinToInterrupt(FLOW_PIN), flow_counter, RISING);

  // Connect to WAP
  Serial.print("Connecting to ");
  Serial.println(ssid);
  WiFi.hostname("ESP_HotWater");
  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("");
  Serial.println("WiFi connected");
  Serial.println("IP address: ");
  Serial.println(WiFi.localIP());

  iot_bundle_state_reported["device_id"] = ESP.getChipId();
  Serial.print("device_id: ");
  Serial.println(ESP.getChipId());
  
  set_status_led(color_status_ok);
}

void report(){

  noInterrupts();
  //START Critical
  unsigned int interval_flow_count = flow_count;
  flow_count = 0;
  //END Critical
  interrupts();

  float elapsed_seconds = (millis() - last_report_millis)/1000.0;

  last_report_millis = millis(); //update timer for next update.
  
  float liters_used = (interval_flow_count / 477.0); 

  // filter out very small sensor movements. The volume at such a low flow isn't accurate anyway
  if (interval_flow_count < 4){
    interval_flow_count = 0;
  }

  

  sensors.requestTemperatures();

  float input_temp_c = sensors.getTempC(input_thermometer_address);
  float output_temp_c = sensors.getTempC(output_thermometer_address);

  // Calculate replenishment effect since last interval.

  //track min and max water temps
  if(liters_used >= SUFFICIENT_FLOW_LITERS){
    consecutive_sufficient_flow_measurements += 1;
    min_input_c = min(min_input_c, input_temp_c);
    max_output_c = max(max_output_c, output_temp_c);
  } else {
    consecutive_sufficient_flow_measurements = 0;
    // default values. 24c is a good middle ground.
    min_input_c = 24;
    max_output_c = 24;
  }
  // if good data for a new input and output values is present, save that data
  if(consecutive_sufficient_flow_measurements >= SUFFICIENT_FLOW_MEASUREMENT_COUNT){
    measured_input_c = min_input_c;
    measured_output_c = max_output_c;
    Serial.print("new measured temperature values: ");
    Serial.print(measured_input_c);
    Serial.print(" - ");
    Serial.println(measured_output_c);

    // TODO: Need to prevent a second shower from setting  lower heat point. Timer since heat point set for 24 hours, or until it reaches full temperature?
    
  }

  //update balance with water used
  liter_deficit -= liters_used;
  liter_degree_deficit -= liters_used * (measured_output_c - measured_input_c);
  Serial.print("degree difference: ");
  Serial.println(measured_output_c - measured_input_c);

  //update balance with water heated
  if (liter_deficit < 0){
    //how many liters can we heat in the elapsed seconds?
    float liters_heated = (liter_degrees_per_second / (measured_output_c - measured_input_c)) * elapsed_seconds;
    liter_deficit += min(liters_heated, liter_deficit * -1);
    
    float liter_degree_delta = min(liter_degrees_per_second * elapsed_seconds, liter_degree_deficit * -1);
    liter_degree_deficit += liter_degree_delta;
    Serial.print("liter degrees per second: ");
    Serial.println(liter_degrees_per_second);
    Serial.print("elapsed seconds ");
    Serial.println(elapsed_seconds);
    Serial.print("liters replaced: ");
    Serial.println(liter_deficit);
  }

  // update bundle with data to report
  iot_bundle_state_reported["liters_used"] = liters_used;
  iot_bundle_state_reported["input_degrees_c"] = input_temp_c;
  iot_bundle_state_reported["output_degrees_c"] = output_temp_c;
  iot_bundle_state_reported["liter_deficit"] = liter_deficit;
  iot_bundle_state_reported["measured_input_c"] = measured_input_c;
  iot_bundle_state_reported["measured_output_c"] = measured_output_c;

  char shadow_string[300];
  iot_bundle.printTo((char*)shadow_string, iot_bundle.measureLength() + 1);

  // send data
  HTTPClient http;
  http.begin(api_path, "3013cd0ed90c2f942f13e85b9dc41d5630e200e0"); //second arg is the fingerprint of the aws api gateway cert.
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", api_key);
  int httpcode = http.POST(shadow_string);
  //http.writeToStream(&Serial);
  //String payload = http.getString();
  if(httpcode == -1){
    Serial.println("report failed!");
    set_status_led(color_status_warning);
  } else {
    Serial.println("success");
    set_status_led(color_status_ok);
  }
  http.end();

}


void loop(){
  if (millis() - last_report_millis  >= reporting_interval_millis) {
    report();
  }
  yield();
}

