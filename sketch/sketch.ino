/*
  AOUDA - Sprachassistent fuer den Arduino UNO Q
  Sketch fuer den Mikrocontroller (STM32U585)

  Der Mikrocontroller steuert nur das 1.8" TFT (ST7735, 160x128) auf dem
  Shield aus dem TftPictureViewer. Spracherkennung, KI-Chat und Aufnahme
  laufen auf der Linux-Seite (python/main.py). Python ruft ueber die Bridge
  diese einfachen Zeichenfunktionen auf; Layout, Zeilenumbruch und Blaettern
  erledigt Python.

  Bridge-Funktionen (alle per provide_safe, laufen also im loop()-Thread):
    ui_ping()                                   -> "AOUDA-TFT <B>x<H>"
    ui_clear(color)
    ui_rect(x, y, w, h, color)
    ui_text(x, y, text, fg, bg, scale, fillWidth)

  Verdrahtung (wie TftPictureViewer):
    TFT CS -> D10, TFT A0/DC -> D8, TFT RESET -> D9,
    SDA/MOSI -> D11, SCK -> D13, SD-CS -> D4 (wird nur deaktiviert)
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
#define TFT_SPI_HZ    12000000UL        // 12 MHz, bei Bildfehlern verringern

// RGB565-Farben
#define COLOR_BLACK   0x0000
#define COLOR_WHITE   0xFFFF
#define COLOR_CYAN    0x07FF
#define COLOR_GRAY    0x8410

TftMini tft(TFT_CS, TFT_DC, TFT_RST, TFT_VARIANT, TFT_SPI_HZ);

// ---------------------------------------------------------------------------
// Bridge-Funktionen
// ---------------------------------------------------------------------------
String ui_ping() {
  return String("AOUDA-TFT ") + tft.width() + "x" + tft.height();
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
void showBootScreen() {
  tft.fillScreen(COLOR_BLACK);
  tft.drawText(32, 36, "AOUDA", COLOR_CYAN, COLOR_BLACK, 3, 0);
  tft.drawText(8, 72, "Sprachassistent", COLOR_WHITE, COLOR_BLACK, 1, 0);
  tft.drawText(8, 100, "Warte auf Linux...", COLOR_GRAY, COLOR_BLACK, 1, 0);
}

void setup() {
  // SD-Karte auf dem Shield deaktivieren, damit sie den SPI-Bus nicht stoert
  pinMode(SD_CS, OUTPUT);
  digitalWrite(SD_CS, HIGH);

  tft.begin(TFT_ROTATION);
  showBootScreen();

  Bridge.begin();
  Bridge.provide_safe("ui_ping", ui_ping);
  Bridge.provide_safe("ui_clear", ui_clear);
  Bridge.provide_safe("ui_rect", ui_rect);
  Bridge.provide_safe("ui_text", ui_text);
}

void loop() {
  // Die Bridge-Aufrufe werden nach jedem loop()-Durchlauf abgearbeitet.
  delay(2);
}
