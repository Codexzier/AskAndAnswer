// Minimaler ST7735-Treiber (1.8" TFT, 160x128) fuer den Arduino UNO Q.
//
// Warum ein eigener Treiber? Die Adafruit-Bibliotheken ziehen weitere
// Abhaengigkeiten (BusIO, seesaw, SD) nach, deren Unterstuetzung fuer den
// Zephyr-Core des UNO Q nicht gesichert ist. Dieser Treiber braucht nur SPI.h
// und digitalWrite() und nutzt dieselbe Init-Sequenz wie Adafruit_ST7735
// (initR), damit das Shield aus dem TftPictureViewer unveraendert passt.
//
// Zephyr fuehrt jeden SPI.transfer() als eigene Transaktion aus. Deshalb
// werden Pixel immer zeilenweise in einem Puffer gesammelt und am Stueck
// gesendet.
//
// Zwei Betriebsarten fuer die Datenleitungen:
//  * Hardware-SPI: schnell, aber nur auf D11 (MOSI) / D13 (SCK).
//  * Software-SPI: per digitalWrite auf frei waehlbaren Pins, optional auf
//    zwei Pin-Paaren gleichzeitig. Beim UNO Q liegen am 6-poligen
//    JSPI-Stecker (dort, wo beim UNO R3 der ICSP-Stecker sitzt) NICHT dieselben
//    Signale wie an D11/D13. Viele TFT-Shields holen SPI aber vom ICSP-Stecker.
//    Mit beiden Pin-Paaren funktioniert das Shield in jedem Fall.

#pragma once
#include <Arduino.h>
#include <SPI.h>

// Varianten wie bei Adafruit: INITR_BLACKTAB, INITR_GREENTAB, INITR_REDTAB
enum TftVariant : uint8_t {
  TFT_BLACKTAB = 0,
  TFT_GREENTAB = 1,
  TFT_REDTAB   = 2,
};

class TftMini {
public:
  TftMini(uint8_t cs, uint8_t dc, int8_t rst, TftVariant variant, uint32_t spiHz);

  // Software-SPI statt Hardware-SPI verwenden (vor begin() aufrufen).
  // mosi2/sck2 = zweites Pin-Paar, das parallel angesteuert wird (-1 = keins).
  void useSoftSpi(int8_t mosi, int8_t sck, int8_t mosi2 = -1, int8_t sck2 = -1);
  bool softSpi() const { return _soft; }

  // rotation wie bei Adafruit (1 = Querformat 160x128)
  void begin(uint8_t rotation);

  int16_t width() const { return _width; }
  int16_t height() const { return _height; }

  void fillScreen(uint16_t color);
  void fillRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t color);

  // Zeichnet UTF-8-Text (ASCII + ae/oe/ue/ss/Grad) im 5x7-Font.
  // scale vergroessert den Font (1 = 6x8 Pixel pro Zeichen).
  // fillWidth > 0: der Hintergrund wird bis zu dieser Breite (ab x) gefuellt,
  // so ueberschreibt eine neue Zeile die alte ohne vorheriges Loeschen.
  // Rueckgabe: Breite des gezeichneten Bereichs in Pixeln.
  int16_t drawText(int16_t x, int16_t y, const char *utf8, uint16_t fg,
                   uint16_t bg, uint8_t scale, int16_t fillWidth);

private:
  void beginTx();
  void endTx();
  void writeCommand(uint8_t cmd);
  void writeData(const uint8_t *data, size_t len);
  void sendCommand(uint8_t cmd, const uint8_t *data, size_t len);
  void runInitList(const uint8_t *list);
  void setWindow(int16_t x, int16_t y, int16_t w, int16_t h);
  void writeBuffer(uint8_t *buf, size_t len);   // Puffer wird ueberschrieben!
  void softWrite(const uint8_t *buf, size_t len);

  static uint8_t decodeGlyphs(const char *utf8, uint8_t *out, uint8_t maxOut);

  uint8_t _cs, _dc;
  int8_t _rst;
  TftVariant _variant;
  uint32_t _spiHz;
  int16_t _width = 128, _height = 160;
  int16_t _xstart = 0, _ystart = 0;
  uint8_t _colstart = 0, _rowstart = 0;
  bool _soft = false;
  int8_t _mosi = -1, _sck = -1, _mosi2 = -1, _sck2 = -1;
};
