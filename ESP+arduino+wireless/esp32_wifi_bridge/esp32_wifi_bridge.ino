// ================================================================
//  ESP32 WiFi-to-Serial Bridge  —  v1.0
//  Board : ESP32 DevKit V1 (ESP32-WROOM-32)
//
//  PURPOSE:
//    Sits between the Laptop (Python) and Arduino Mega.
//    Receives UDP packets over WiFi and forwards them
//    byte-for-byte to Arduino Mega via hardware Serial2.
//    Also forwards Arduino responses back to the laptop via UDP.
//
//  DATA FLOW:
//    PS4 Controller → Laptop (Python)
//         → WiFi UDP (port 4210) → THIS ESP32
//         → Serial2 (GPIO 16/17) → Arduino Mega
//
//  FEATURES:
//    • WiFi Station mode — joins your mobile hotspot
//    • UDP listener on port 4210 (low latency, ~1 ms)
//    • Transparent serial bridge — no packet modification
//    • ArduinoOTA — upload code wirelessly after first USB flash
//    • Status LED on GPIO 2 (onboard blue LED)
//        Fast blink (200 ms) = WiFi connected + receiving data
//        Slow blink (1000 ms) = waiting for WiFi or data
//    • Prints IP address to Serial Monitor on boot
//    • Auto-reconnect if WiFi drops
//
//  WIRING (ESP32 → Arduino Mega):
//    ESP32 GPIO 27 (TX2) → Mega pin 18 (RX1)
//    ESP32 GPIO 26 (RX2) → Mega pin 19 (TX1)
//    ESP32 GND           → Mega GND
//
//  FIRST UPLOAD:
//    1. Connect ESP32 via USB to your PC
//    2. Arduino IDE → Tools → Board → "ESP32 Dev Module"
//    3. Tools → Port → select the COM port
//    4. Upload this sketch
//    5. Open Serial Monitor at 115200 baud
//    6. Turn on your mobile hotspot
//    7. Note the IP address printed (e.g., 192.168.X.X)
//    8. Enter that IP in ps4_to_arduino_wifi.py
//
//  SUBSEQUENT UPLOADS (OTA):
//    1. ESP32 must be powered and connected to the same WiFi
//    2. Arduino IDE → Tools → Port → select "esp32-r1-car"
//    3. Upload — no USB cable needed!
//
//  Requirements:
//    Arduino IDE with ESP32 board support installed
//    (Board: ESP32 Dev Module)
// ================================================================

#include <ArduinoOTA.h>
#include <WiFi.h>
#include <WiFiUdp.h>

// ================================================================
//  ⚠️  CHANGE THESE TO YOUR MOBILE HOTSPOT CREDENTIALS  ⚠️
// ================================================================
const char *WIFI_SSID = "Galaxy A15";    // ← your mobile hotspot name
const char *WIFI_PASSWORD = "123456789"; // ← your mobile hotspot password
// ================================================================

// ================================================================
//  CONFIG
// ================================================================
#define UDP_PORT 4210          // port Python sends to
#define SERIAL2_BAUD 115200    // must match Arduino Mega Serial1
#define SERIAL_MON_BAUD 115200 // USB serial monitor for debug
#define LED_PIN 2              // onboard blue LED (ESP32 DevKit V1)

// Serial2 pins on ESP32 DevKit V1  (boot-safe, OTA-compatible)
#define SERIAL2_RX_PIN 26 // GPIO 26 = RX2  (was 16, caused OTA boot issues)
#define SERIAL2_TX_PIN 27 // GPIO 27 = TX2  (was 17, changed to match)

// Timing
#define WIFI_RETRY_MS 500    // retry interval for WiFi connection
#define LED_FAST_MS 200      // blink rate when active
#define LED_SLOW_MS 1000     // blink rate when idle
#define DATA_TIMEOUT_MS 2000 // consider "idle" if no UDP data for this long
#define SERIAL_FWD_MS 50     // how often to check Arduino serial for responses

// Buffer sizes
#define UDP_BUF_SIZE 64     // max UDP packet size (our packets are ~20 bytes)
#define SERIAL_BUF_SIZE 256 // buffer for Arduino serial responses

// ================================================================
//  GLOBAL STATE
// ================================================================
WiFiUDP udp;

// Track the last sender so we can forward Arduino responses back
IPAddress lastSenderIP;
uint16_t lastSenderPort = 0;

unsigned long lastDataTime = 0;
unsigned long lastLEDTime = 0;
bool ledState = false;
bool wifiConnected = false;

// Statistics
unsigned long packetCount = 0;
unsigned long lastStatsTime = 0;

// ================================================================
//  connectWiFi()
//  Connects to the mobile hotspot. Blocks until connected.
//  Prints status updates to Serial Monitor.
// ================================================================
void connectWiFi() {
  Serial.println();
  Serial.println("================================================");
  Serial.print("[WiFi] Connecting to: ");
  Serial.println(WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.disconnect(); // Clear previous config to ensure clean start
  delay(500);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long startAttemptTime = millis();
  int dots = 0;

  // Wait up to 20 seconds for connection
  while (WiFi.status() != WL_CONNECTED &&
         millis() - startAttemptTime < 20000UL) {
    delay(WIFI_RETRY_MS);
    Serial.print(".");
    dots++;
    if (dots % 40 == 0)
      Serial.println();

    // Blink LED slowly while connecting
    ledState = !ledState;
    digitalWrite(LED_PIN, ledState);
  }

  if (WiFi.status() == WL_CONNECTED) {
    wifiConnected = true;
    digitalWrite(LED_PIN, HIGH); // LED solid ON = WiFi connected
    ledState = true;
    Serial.println();
    Serial.println("[WiFi] ✓ Connected!");
    Serial.print("[WiFi] IP Address : ");
    Serial.println(WiFi.localIP());
    Serial.print("[WiFi] Signal     : ");
    Serial.print(WiFi.RSSI());
    Serial.println(" dBm");
  } else {
    wifiConnected = false;
    Serial.println();
    Serial.print("[WiFi] ✗ Failed to connect. Status Code: ");
    Serial.println(WiFi.status());

    switch (WiFi.status()) {
    case WL_NO_SSID_AVAIL:
      Serial.println("[HINT] SSID not found. Is the hotspot turned ON?");
      break;
    case WL_CONNECT_FAILED:
      Serial.println(
          "[HINT] Connection failed. Check if your phone allows new devices.");
      break;
    case WL_DISCONNECTED:
      Serial.println("[HINT] Wrong password OR phone dropped connection.");
      break;
    default:
      Serial.println("[HINT] Ensure 'Maximize Compatibility' (2.4GHz) is ON in "
                     "hotspot settings.");
      break;
    }
    Serial.println("================================================");
  }
  Serial.println();
}

// ================================================================
//  setupOTA()
//  Configures ArduinoOTA for wireless firmware uploads.
// ================================================================
void setupOTA() {
  ArduinoOTA.setHostname("esp32-r1-car");

  ArduinoOTA.onStart([]() {
    String type =
        (ArduinoOTA.getCommand() == U_FLASH) ? "Firmware" : "Filesystem";
    Serial.println("[OTA] Uploading " + type + "...");
  });

  ArduinoOTA.onEnd(
      []() { Serial.println("\n[OTA] ✓ Upload complete! Rebooting..."); });

  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    Serial.printf("[OTA] Progress: %u%%\r", (progress / (total / 100)));
  });

  ArduinoOTA.onError([](ota_error_t error) {
    Serial.printf("[OTA] Error[%u]: ", error);
    if (error == OTA_AUTH_ERROR)
      Serial.println("Auth Failed");
    else if (error == OTA_BEGIN_ERROR)
      Serial.println("Begin Failed");
    else if (error == OTA_CONNECT_ERROR)
      Serial.println("Connect Failed");
    else if (error == OTA_RECEIVE_ERROR)
      Serial.println("Receive Failed");
    else if (error == OTA_END_ERROR)
      Serial.println("End Failed");
  });

  ArduinoOTA.begin();
  Serial.println("[OTA] ✓ OTA Ready — hostname: esp32-r1-car");
}

// ================================================================
//  blinkLED()
//  Solid ON = WiFi connected,  Blinking = not connected
// ================================================================
void blinkLED() {
  if (wifiConnected) {
    // Solid ON when connected to WiFi
    if (!ledState) {
      ledState = true;
      digitalWrite(LED_PIN, HIGH);
    }
  } else {
    // Blink when not connected
    if (millis() - lastLEDTime >= LED_SLOW_MS) {
      lastLEDTime = millis();
      ledState = !ledState;
      digitalWrite(LED_PIN, ledState);
    }
  }
}

// ================================================================
//  printBanner()
// ================================================================
void printBanner() {
  Serial.println();
  Serial.println("================================================");
  Serial.println("  ESP32 WiFi-to-Serial Bridge  v1.0");
  Serial.println("  R1 Mecanum Car — Wireless Controller");
  Serial.println("================================================");
  Serial.println("  WiFi  → UDP port 4210 → Serial2 → Arduino Mega");
  Serial.println("  OTA   → hostname: esp32-r1-car");
  Serial.println("================================================");
  Serial.println();
}

// ================================================================
//  SETUP
// ================================================================
void setup() {
  // USB Serial for debug output
  Serial.begin(SERIAL_MON_BAUD);

  // Hardware Serial2 for Arduino Mega communication
  Serial2.begin(SERIAL2_BAUD, SERIAL_8N1, SERIAL2_RX_PIN, SERIAL2_TX_PIN);

  // LED
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  printBanner();

  // Connect to WiFi (blocks until connected)
  connectWiFi();

  // Start UDP listener
  udp.begin(UDP_PORT);
  Serial.print("[UDP]  ✓ Listening on port ");
  Serial.println(UDP_PORT);

  // Setup OTA
  setupOTA();

  Serial.println();
  Serial.println("================================================");
  Serial.print("  READY — Tell Python to send to: ");
  Serial.print(WiFi.localIP());
  Serial.print(":");
  Serial.println(UDP_PORT);
  Serial.println("================================================");
  Serial.println();

  lastDataTime = millis();
  lastStatsTime = millis();
}

// ================================================================
//  LOOP
// ================================================================
void loop() {

  // ── Handle OTA ──────────────────────────────────────────
  ArduinoOTA.handle();

  // ── Check WiFi connection ───────────────────────────────
  if (WiFi.status() != WL_CONNECTED) {
    if (wifiConnected) {
      Serial.println("[WiFi] ✗ Connection lost! Reconnecting...");
      wifiConnected = false;
    }
    connectWiFi();
    udp.begin(UDP_PORT); // restart UDP after reconnect
  }

  // ── Receive UDP packets → Forward to Arduino Serial2 ───
  int packetSize = udp.parsePacket();
  if (packetSize > 0 && packetSize < UDP_BUF_SIZE) {
    char buf[UDP_BUF_SIZE];
    int len = udp.read(buf, UDP_BUF_SIZE - 1);
    buf[len] = '\0';

    // Remember sender for responses
    lastSenderIP = udp.remoteIP();
    lastSenderPort = udp.remotePort();

    // Forward to Arduino Mega via Serial2 — transparent bridge
    Serial2.write((uint8_t *)buf, len);

    lastDataTime = millis();
    packetCount++;
  }

  // ── Read Arduino Serial2 responses → Forward back via UDP ──
  // (for PONG, debug messages, etc.)
  if (Serial2.available()) {
    char serialBuf[SERIAL_BUF_SIZE];
    int idx = 0;

    // Read all available bytes (non-blocking)
    unsigned long readStart = millis();
    while (Serial2.available() && idx < SERIAL_BUF_SIZE - 1) {
      serialBuf[idx++] = Serial2.read();
      // Small timeout to allow multi-byte messages to arrive
      if (!Serial2.available()) {
        delay(1);
      }
      // Don't spend more than 5ms reading
      if (millis() - readStart > 5)
        break;
    }
    serialBuf[idx] = '\0';

    // Print to USB Serial Monitor for debug
    Serial.print(serialBuf);

    // Forward back to laptop via UDP (if we have a sender)
    if (lastSenderPort != 0 && idx > 0) {
      udp.beginPacket(lastSenderIP, lastSenderPort);
      udp.write((uint8_t *)serialBuf, idx);
      udp.endPacket();
    }
  }

  // ── Status LED ──────────────────────────────────────────
  blinkLED();

  // ── Print stats every 10 seconds ────────────────────────
  if (millis() - lastStatsTime >= 10000UL) {
    lastStatsTime = millis();
    Serial.print("[STATS] Packets received: ");
    Serial.print(packetCount);
    Serial.print("  |  WiFi RSSI: ");
    Serial.print(WiFi.RSSI());
    Serial.print(" dBm  |  Free heap: ");
    Serial.print(ESP.getFreeHeap());
    Serial.println(" bytes");
  }

  // Tiny delay to prevent watchdog issues
  delay(1);
}
