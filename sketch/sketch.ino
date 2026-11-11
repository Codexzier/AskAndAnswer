/*
  TFT-Test fuer den Arduino UNO Q

  Prueft, ob das 1.8" TFT (ST7735, 160x128) vom TftPictureViewer-Shield am
  UNO Q funktioniert. Es wird nur ein animierter Text angezeigt - kein Linux,
  keine Bridge, kein Python.

  Der Test probiert nacheinander (je 12 Sekunden, dann von vorn) drei Arten,
  das Display anzusteuern. Gross auf dem Display steht die Nummer der Methode:

    1  Hardware-SPI auf D11 (MOSI) / D13 (SCK)
    2  Software-SPI auf D11 / D13
    3  Software-SPI auf dem 6-poligen JSPI-Stecker (Position des ICSP-Steckers
       beim UNO R3). Beim UNO Q liegen dort ANDERE Signale als an D11/D13!

  Merke dir, bei welchen Nummern etwas zu sehen ist:
    * nur 1 und 2  -> Shield nutzt D11/D13  (in AOUDA: TFT_BUS_HW_SPI)
    * nur 3        -> Shield nutzt den ICSP-Stecker (in AOUDA: TFT_BUS_JSPI)
    * nur 2        -> Verdrahtung ok, aber Hardware-SPI klappt nicht
    * gar nichts   -> Strom, Reset-Pin oder Display-Variante pruefen

  Die eingebaute LED blinkt, solange der Sketch laeuft. Blinkt sie nicht,
  wurde der Sketch nicht geladen oder ist abgestuerzt.

  Verdrahtung (wie TftPictureViewer):
    TFT CS -> D10, TFT A0/DC -> D8, TFT RESET -> D9, SD-CS -> D4
*/

#include "tft_mini.h"

// ---------------------------------------------------------------------------
// Einstellungen
// ---------------------------------------------------------------------------
#define TFT_CS    10
#define TFT_DC     8
#define TFT_RST    9
#define SD_CS      4

// Display-Variante wie im TftPictureViewer (INITR_BLACKTAB).
// Falsche Farben oder ein Rand aus Pixelmuell -> TFT_GREENTAB / TFT_REDTAB
#define TFT_VARIANT   TFT_BLACKTAB
#define TFT_ROTATION  1                  // Querformat 160x128
#define TFT_SPI_HZ    8000000UL          // Hardware-SPI-Takt

// Arduino-Pinnummern beim UNO Q
#define PIN_MOSI   11   // D11 = PB15
#define PIN_SCK    13   // D13 = PB13
#define JSPI_MISO  22   // JSPI PC2
#define JSPI_MOSI  23   // JSPI PC3
#define JSPI_SCK   24   // JSPI PD1

const uint32_t METHOD_MS = 12000;        // Dauer pro Methode

// RGB565-Farben
#define BLACK    0x0000
#define WHITE    0xFFFF
#define GRAY     0x8410
#define RED      0xF800
#define GREEN    0x07E0
#define BLUE     0x001F
#define CYAN     0x07FF
#define MAGENTA  0xF81F
#define YELLOW   0xFFE0
#define ORANGE   0xFD20

const uint16_t RAINBOW[] = { RED, ORANGE, YELLOW, GREEN, CYAN, BLUE, MAGENTA };
const uint8_t RAINBOW_N = sizeof(RAINBOW) / sizeof(RAINBOW[0]);

// ---------------------------------------------------------------------------
// Drei Ansteuerungsarten
// ---------------------------------------------------------------------------
TftMini tftHw(TFT_CS, TFT_DC, TFT_RST, TFT_VARIANT, TFT_SPI_HZ);
TftMini tftSoft(TFT_CS, TFT_DC, TFT_RST, TFT_VARIANT, TFT_SPI_HZ);
TftMini tftJspi(TFT_CS, TFT_DC, TFT_RST, TFT_VARIANT, TFT_SPI_HZ);

struct Method {
  TftMini *tft;
  const char *line1;
  const char *line2;
};

const Method METHODS[] = {
  { &tftHw,   "Hardware-SPI",  "D11 / D13" },
  { &tftSoft, "Software-SPI",  "D11 / D13" },
  { &tftJspi, "Software-SPI",  "JSPI (ICSP)" },
};
const uint8_t METHOD_N = sizeof(METHODS) / sizeof(METHODS[0]);

const char MARQUEE[] = "     +++ AOUDA - TFT-Test auf dem Arduino UNO Q +++ Gruesse an das Display! ";

uint8_t methodIndex = 0;
bool ledOn = false;

// ---------------------------------------------------------------------------
// Animation
// ---------------------------------------------------------------------------
void drawStatic(TftMini &tft, uint8_t index) {
  const Method &m = METHODS[index];
  tft.fillScreen(BLACK);

  // Farbbalken oben: zeigen, ob die Farben stimmen (rot, gruen, blau, weiss, gelb)
  const uint16_t bars[] = { RED, GREEN, BLUE, WHITE, YELLOW };
  for (int i = 0; i < 5; i++) tft.fillRect(i * 32, 0, 32, 6, bars[i]);

  // Grosse Nummer der Methode
  char number[2] = { (char)('1' + index), 0 };
  tft.drawText(4, 12, number, YELLOW, BLACK, 4, 0);
  tft.drawText(34, 14, m.line1, WHITE, BLACK, 1, 0);
  tft.drawText(34, 26, m.line2, CYAN, BLACK, 1, 0);

  // Rahmen um die Bewegungsflaeche
  tft.fillRect(0, 76, 160, 1, GRAY);
  tft.fillRect(0, 115, 160, 1, GRAY);
}

void runMethod(uint8_t index) {
  TftMini &tft = *METHODS[index].tft;
  tft.begin(TFT_ROTATION);
  drawStatic(tft, index);

  uint32_t start = millis();
  uint32_t frame = 0;
  int16_t ballX = 10, ballY = 80, dx = 3, dy = 2;
  const int16_t BALL = 8;

  while (millis() - start < METHOD_MS) {
    // 1) Lauftext (Zeichen fuer Zeichen), doppelte Groesse
    const uint8_t visible = 13;   // 13 Zeichen x 12 Pixel = 156 Pixel
    const uint16_t len = sizeof(MARQUEE) - 1;
    char window[visible + 1];
    for (uint8_t i = 0; i < visible; i++) window[i] = MARQUEE[(frame + i) % len];
    window[visible] = 0;
    tft.drawText(2, 44, window, RAINBOW[(frame / 4) % RAINBOW_N], BLACK, 2, 156);

    // 2) Huepfender Ball
    tft.fillRect(ballX, ballY, BALL, BALL, BLACK);
    ballX += dx;
    ballY += dy;
    if (ballX <= 0 || ballX + BALL >= 160) { dx = -dx; ballX += 2 * dx; }
    if (ballY <= 78 || ballY + BALL >= 114) { dy = -dy; ballY += 2 * dy; }
    tft.fillRect(ballX, ballY, BALL, BALL, RAINBOW[frame % RAINBOW_N]);

    // 3) Statuszeile: Bilder pro Sekunde und Restzeit
    uint32_t elapsed = millis() - start;
    uint32_t remaining = elapsed < METHOD_MS ? (METHOD_MS - elapsed) / 1000 : 0;
    uint32_t fps10 = elapsed ? (frame * 10000UL) / elapsed : 0;
    char status[48];
    snprintf(status, sizeof(status), "Bild %4lu  %2lu.%lu fps  %2lus",
             (unsigned long)frame, (unsigned long)(fps10 / 10), (unsigned long)(fps10 % 10),
             (unsigned long)remaining);
    tft.drawText(2, 119, status, GRAY, BLACK, 1, 156);

    // Lebenszeichen: eingebaute LED (active-low) umschalten
    ledOn = !ledOn;
    digitalWrite(LED_BUILTIN, ledOn ? LOW : HIGH);

    frame++;
  }
}

// ---------------------------------------------------------------------------
// Setup / Loop
// ---------------------------------------------------------------------------
void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);

  // SD-Karte auf dem Shield deaktivieren, damit sie die Datenleitungen nicht stoert
  pinMode(SD_CS, OUTPUT);
  digitalWrite(SD_CS, HIGH);
  pinMode(JSPI_MISO, INPUT);

  tftSoft.useSoftSpi(PIN_MOSI, PIN_SCK);
  tftJspi.useSoftSpi(JSPI_MOSI, JSPI_SCK);
}

void loop() {
  runMethod(methodIndex);
  methodIndex = (methodIndex + 1) % METHOD_N;
}
