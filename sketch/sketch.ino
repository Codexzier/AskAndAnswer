/*
  AOUDA - Sprachassistent fuer den Arduino UNO Q
  Sketch fuer den Mikrocontroller (STM32U585)

  Der Mikrocontroller steuert nur das 1.8" TFT (ST7735, 160x128) auf dem
  Shield aus dem TftPictureViewer. Spracherkennung, KI-Chat und Aufnahme
  laufen auf der Linux-Seite (python/main.py). Python ruft ueber die Bridge
  diese einfachen Zeichenfunktionen auf; Layout, Zeilenumbruch und Blaettern
  erledigt Python.

  Bridge-Funktionen (alle per provide_safe, laufen also im loop()-Thread):
    ui_ping()                                   -> "AOUDA-TFT <B>x<H> <Bus>"
    ui_clear(color)
    ui_rect(x, y, w, h, color)
    ui_text(x, y, text, fg, bg, scale, fillWidth)

  Verdrahtung (wie TftPictureViewer):
    TFT CS -> D10, TFT A0/DC -> D8, TFT RESET -> D9,
    SDA/MOSI -> D11, SCK -> D13, SD-CS -> D4 (wird nur deaktiviert)

  ACHTUNG UNO Q: Der 6-polige JSPI-Stecker (Position des ICSP-Steckers beim
  UNO R3) fuehrt NICHT dieselben Signale wie D11/D13. Viele TFT-Shields holen
  MOSI/SCK vom ICSP-Stecker. Standardmaessig (TFT_BUS_BOTH) werden deshalb
  beide Anschluesse gleichzeitig per Software-SPI angesteuert.

  Beim Start zeigt der Sketch sofort ein Testbild (Farbbalken + "AOUDA"),
  unabhaengig von Linux/Python. Bleibt das Display dunkel oder weiss, liegt
  es an Verdrahtung, Stromversorgung oder TFT_VARIANT - nicht an Python.
*/

#include <Arduino_RouterBridge.h>
#include "tft_mini.h"

// ---------------------------------------------------------------------------
// Pins und Display
// ---------------------------------------------------------------------------
#define TFT_CS    10
#define TFT_DC     8
#define TFT_RST    9
#define SD_CS      4

// Display-Variante wie im TftPictureViewer (INITR_BLACKTAB).
// Bei falschen Farben/Randpixeln TFT_GREENTAB oder TFT_REDTAB probieren.
#define TFT_VARIANT   TFT_BLACKTAB
#define TFT_ROTATION  1                 // Querformat 160x128
#define TFT_SPI_HZ    12000000UL        // 12 MHz, nur fuer TFT_BUS_HW_SPI

// Wo kommen MOSI/SCK am Shield an?
//   TFT_BUS_BOTH    Software-SPI auf D11/D13 UND JSPI/ICSP gleichzeitig (Standard,
//                   funktioniert immer, ein Bildaufbau dauert knapp 1 s)
//   TFT_BUS_HW_SPI  Hardware-SPI auf D11/D13 (schnell), wenn das Shield D11/D13 nutzt
//   TFT_BUS_JSPI    Software-SPI nur auf dem JSPI/ICSP-Stecker
#define TFT_BUS_BOTH    0
#define TFT_BUS_HW_SPI  1
#define TFT_BUS_JSPI    2
#define TFT_BUS         TFT_BUS_BOTH

// Arduino-Pinnummern des JSPI-Steckers beim UNO Q (Index in digital-pin-gpios)
#define JSPI_MISO  22   // PC2
#define JSPI_MOSI  23   // PC3
#define JSPI_SCK   24   // PD1

// RGB565-Farben
#define COLOR_BLACK   0x0000
#define COLOR_WHITE   0xFFFF
#define COLOR_CYAN    0x07FF
#define COLOR_GRAY    0x8410
#define COLOR_RED     0xF800
#define COLOR_GREEN   0x07E0
#define COLOR_BLUE    0x001F
#define COLOR_YELLOW  0xFFE0

TftMini tft(TFT_CS, TFT_DC, TFT_RST, TFT_VARIANT, TFT_SPI_HZ);

// ---------------------------------------------------------------------------
// Bridge-Funktionen
// ---------------------------------------------------------------------------
const char *busName() {
  switch (TFT_BUS) {
    case TFT_BUS_HW_SPI: return "HW-SPI D11/D13";
    case TFT_BUS_JSPI:   return "Soft-SPI JSPI";
    default:             return "Soft-SPI D11/D13+JSPI";
  }
}

String ui_ping() {
  return String("AOUDA-TFT ") + tft.width() + "x" + tft.height() + " " + busName();
}

void ui_clear(int color) {
  tft.fillScreen((uint16_t)color);
}

void ui_rect(int x, int y, int w, int h, int color) {
  tft.fillRect(x, y, w, h, (uint16_t)color);
}

void ui_text(int x, int y, String text, int fg, int bg, int scale, int fillWidth) {
  tft.drawText(x, y, text.c_str(), (uint16_t)fg, (uint16_t)bg, (uint8_t)scale, fillWidth);
}

// ---------------------------------------------------------------------------
// Setup / Loop
// ---------------------------------------------------------------------------
// Testbild: Farbbalken oben pruefen Farben (rot, gruen, blau) und die
// Display-Variante (Balken muessen buendig am Rand sitzen).
void showBootScreen() {
  tft.fillScreen(COLOR_BLACK);
  const uint16_t bars[] = { COLOR_RED, COLOR_GREEN, COLOR_BLUE, COLOR_WHITE, COLOR_YELLOW };
  for (int i = 0; i < 5; i++) tft.fillRect(i * 32, 0, 32, 10, bars[i]);
  tft.drawText(32, 30, "AOUDA", COLOR_CYAN, COLOR_BLACK, 3, 0);
  tft.drawText(8, 64, "Sprachassistent", COLOR_WHITE, COLOR_BLACK, 1, 0);
  tft.drawText(8, 80, busName(), COLOR_GRAY, COLOR_BLACK, 1, 0);
  tft.drawText(8, 104, "Warte auf Linux...", COLOR_GRAY, COLOR_BLACK, 1, 0);
}

void setup() {
  // SD-Karte auf dem Shield deaktivieren, damit sie den SPI-Bus nicht stoert
  pinMode(SD_CS, OUTPUT);
  digitalWrite(SD_CS, HIGH);

#if TFT_BUS == TFT_BUS_BOTH
  tft.useSoftSpi(11, 13, JSPI_MOSI, JSPI_SCK);   // D11/D13 + JSPI
  pinMode(JSPI_MISO, INPUT);
#elif TFT_BUS == TFT_BUS_JSPI
  tft.useSoftSpi(JSPI_MOSI, JSPI_SCK);
  pinMode(JSPI_MISO, INPUT);
#endif
  tft.begin(TFT_ROTATION);
  showBootScreen();

  Bridge.begin();
  Monitor.begin();
  Monitor.print("AOUDA TFT bereit, Bus: ");
  Monitor.println(busName());
  Bridge.provide_safe("ui_ping", ui_ping);
  Bridge.provide_safe("ui_clear", ui_clear);
  Bridge.provide_safe("ui_rect", ui_rect);
  Bridge.provide_safe("ui_text", ui_text);
}

void loop() {
  // Die Bridge-Aufrufe werden nach jedem loop()-Durchlauf abgearbeitet.
  delay(2);
}
