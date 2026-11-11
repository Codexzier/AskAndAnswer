// Minimaler ST7735-Treiber, siehe tft_mini.h
//
// Die Init-Tabellen entsprechen Adafruit_ST7735::initR() aus der
// "Adafruit ST7735 and ST7789 Library" (Copyright (c) Adafruit Industries,
// BSD License).

#include "tft_mini.h"
#include "font5x7.h"

// ST7735-Kommandos
#define ST_SWRESET  0x01
#define ST_SLPOUT   0x11
#define ST_NORON    0x13
#define ST_INVOFF   0x20
#define ST_DISPON   0x29
#define ST_CASET    0x2A
#define ST_RASET    0x2B
#define ST_RAMWR    0x2C
#define ST_MADCTL   0x36
#define ST_COLMOD   0x3A
#define ST_FRMCTR1  0xB1
#define ST_FRMCTR2  0xB2
#define ST_FRMCTR3  0xB3
#define ST_INVCTR   0xB4
#define ST_PWCTR1   0xC0
#define ST_PWCTR2   0xC1
#define ST_PWCTR3   0xC2
#define ST_PWCTR4   0xC3
#define ST_PWCTR5   0xC4
#define ST_VMCTR1   0xC5
#define ST_GMCTRP1  0xE0
#define ST_GMCTRN1  0xE1

#define MADCTL_MY   0x80
#define MADCTL_MX   0x40
#define MADCTL_MV   0x20
#define MADCTL_RGB  0x00
#define MADCTL_BGR  0x08

#define CMD_DELAY   0x80

// Format: Anzahl Kommandos, dann je Kommando: cmd, nargs(|CMD_DELAY), args, [delay]
static const uint8_t INIT_R1[] = {
  15,
  ST_SWRESET, CMD_DELAY, 150,
  ST_SLPOUT,  CMD_DELAY, 255,
  ST_FRMCTR1, 3, 0x01, 0x2C, 0x2D,
  ST_FRMCTR2, 3, 0x01, 0x2C, 0x2D,
  ST_FRMCTR3, 6, 0x01, 0x2C, 0x2D, 0x01, 0x2C, 0x2D,
  ST_INVCTR,  1, 0x07,
  ST_PWCTR1,  3, 0xA2, 0x02, 0x84,
  ST_PWCTR2,  1, 0xC5,
  ST_PWCTR3,  2, 0x0A, 0x00,
  ST_PWCTR4,  2, 0x8A, 0x2A,
  ST_PWCTR5,  2, 0x8A, 0xEE,
  ST_VMCTR1,  1, 0x0E,
  ST_INVOFF,  0,
  ST_MADCTL,  1, 0xC8,
  ST_COLMOD,  1, 0x05,
};

static const uint8_t INIT_R2_GREEN[] = {
  2,
  ST_CASET, 4, 0x00, 0x02, 0x00, 0x7F + 0x02,
  ST_RASET, 4, 0x00, 0x01, 0x00, 0x9F + 0x01,
};

static const uint8_t INIT_R2_RED[] = {
  2,
  ST_CASET, 4, 0x00, 0x00, 0x00, 0x7F,
  ST_RASET, 4, 0x00, 0x00, 0x00, 0x9F,
};

static const uint8_t INIT_R3[] = {
  4,
  ST_GMCTRP1, 16, 0x02, 0x1c, 0x07, 0x12, 0x37, 0x32, 0x29, 0x2d,
                  0x29, 0x25, 0x2B, 0x39, 0x00, 0x01, 0x03, 0x10,
  ST_GMCTRN1, 16, 0x03, 0x1d, 0x07, 0x06, 0x2E, 0x2C, 0x29, 0x2D,
                  0x2E, 0x2E, 0x37, 0x3F, 0x00, 0x00, 0x02, 0x10,
  ST_NORON,  CMD_DELAY, 10,
  ST_DISPON, CMD_DELAY, 100,
};

// Pixelpuffer: 8 Zeilen a 160 Pixel (RGB565, big endian)
static const size_t PIXBUF_BYTES = 160 * 8 * 2;
static uint8_t pixbuf[PIXBUF_BYTES];

TftMini::TftMini(uint8_t cs, uint8_t dc, int8_t rst, TftVariant variant, uint32_t spiHz)
  : _cs(cs), _dc(dc), _rst(rst), _variant(variant), _spiHz(spiHz) {}

void TftMini::useSoftSpi(int8_t mosi, int8_t sck, int8_t mosi2, int8_t sck2) {
  _soft = true;
  _mosi = mosi;
  _sck = sck;
  _mosi2 = mosi2;
  _sck2 = sck2;
}

void TftMini::beginTx() {
  if (!_soft) SPI.beginTransaction(SPISettings(_spiHz, MSBFIRST, SPI_MODE0));
  digitalWrite(_cs, LOW);
}

void TftMini::endTx() {
  digitalWrite(_cs, HIGH);
  if (!_soft) SPI.endTransaction();
}

// SPI Mode 0 per digitalWrite: Daten anlegen, Takt hoch (Display liest), Takt runter
void TftMini::softWrite(const uint8_t *buf, size_t len) {
  int lastBit = -1;
  for (size_t i = 0; i < len; i++) {
    uint8_t b = buf[i];
    for (uint8_t mask = 0x80; mask; mask >>= 1) {
      int bit = (b & mask) ? HIGH : LOW;
      if (bit != lastBit) {
        digitalWrite(_mosi, bit);
        if (_mosi2 >= 0) digitalWrite(_mosi2, bit);
        lastBit = bit;
      }
      digitalWrite(_sck, HIGH);
      if (_sck2 >= 0) digitalWrite(_sck2, HIGH);
      digitalWrite(_sck, LOW);
      if (_sck2 >= 0) digitalWrite(_sck2, LOW);
    }
  }
}

void TftMini::writeCommand(uint8_t cmd) {
  digitalWrite(_dc, LOW);
  if (_soft) softWrite(&cmd, 1);
  else SPI.transfer(cmd);
  digitalWrite(_dc, HIGH);
}

void TftMini::writeData(const uint8_t *data, size_t len) {
  if (_soft) {
    softWrite(data, len);
    return;
  }
  uint8_t tmp[16];
  while (len > 0) {
    size_t n = len < sizeof(tmp) ? len : sizeof(tmp);
    memcpy(tmp, data, n);
    SPI.transfer(tmp, n);
    data += n;
    len -= n;
  }
}

void TftMini::sendCommand(uint8_t cmd, const uint8_t *data, size_t len) {
  beginTx();
  writeCommand(cmd);
  if (len) writeData(data, len);
  endTx();
}

void TftMini::runInitList(const uint8_t *p) {
  uint8_t count = *p++;
  while (count--) {
    uint8_t cmd = *p++;
    uint8_t nargs = *p++;
    bool withDelay = nargs & CMD_DELAY;
    nargs &= ~CMD_DELAY;
    sendCommand(cmd, p, nargs);
    p += nargs;
    if (withDelay) {
      uint16_t ms = *p++;
      if (ms == 255) ms = 500;
      delay(ms);
    }
  }
}

void TftMini::begin(uint8_t rotation) {
  pinMode(_cs, OUTPUT);
  pinMode(_dc, OUTPUT);
  digitalWrite(_cs, HIGH);
  digitalWrite(_dc, HIGH);
  if (_soft) {
    const int8_t pins[4] = { _mosi, _sck, _mosi2, _sck2 };
    for (int8_t pin : pins) {
      if (pin < 0) continue;
      pinMode(pin, OUTPUT);
      digitalWrite(pin, LOW);
    }
  } else {
    SPI.begin();
  }

  if (_rst >= 0) {
    pinMode(_rst, OUTPUT);
    digitalWrite(_rst, HIGH);
    delay(100);
    digitalWrite(_rst, LOW);
    delay(100);
    digitalWrite(_rst, HIGH);
    delay(200);
  }

  runInitList(INIT_R1);
  if (_variant == TFT_GREENTAB) {
    runInitList(INIT_R2_GREEN);
    _colstart = 2;
    _rowstart = 1;
  } else {
    runInitList(INIT_R2_RED);
    _colstart = 0;
    _rowstart = 0;
  }
  runInitList(INIT_R3);

  // Rotation (wie Adafruit_ST7735::setRotation)
  uint8_t rgb = (_variant == TFT_BLACKTAB) ? MADCTL_RGB : MADCTL_BGR;
  uint8_t madctl;
  switch (rotation & 3) {
    case 0:
      madctl = MADCTL_MX | MADCTL_MY | rgb;
      _width = 128; _height = 160; _xstart = _colstart; _ystart = _rowstart;
      break;
    case 1:
      madctl = MADCTL_MY | MADCTL_MV | rgb;
      _width = 160; _height = 128; _xstart = _rowstart; _ystart = _colstart;
      break;
    case 2:
      madctl = rgb;
      _width = 128; _height = 160; _xstart = _colstart; _ystart = _rowstart;
      break;
    default:
      madctl = MADCTL_MX | MADCTL_MV | rgb;
      _width = 160; _height = 128; _xstart = _rowstart; _ystart = _colstart;
      break;
  }
  sendCommand(ST_MADCTL, &madctl, 1);
}

void TftMini::setWindow(int16_t x, int16_t y, int16_t w, int16_t h) {
  uint16_t x0 = x + _xstart, x1 = x + w - 1 + _xstart;
  uint16_t y0 = y + _ystart, y1 = y + h - 1 + _ystart;
  uint8_t ca[4] = { (uint8_t)(x0 >> 8), (uint8_t)x0, (uint8_t)(x1 >> 8), (uint8_t)x1 };
  uint8_t ra[4] = { (uint8_t)(y0 >> 8), (uint8_t)y0, (uint8_t)(y1 >> 8), (uint8_t)y1 };
  writeCommand(ST_CASET);
  writeData(ca, 4);
  writeCommand(ST_RASET);
  writeData(ra, 4);
  writeCommand(ST_RAMWR);
}

void TftMini::writeBuffer(uint8_t *buf, size_t len) {
  if (_soft) softWrite(buf, len);
  else SPI.transfer(buf, len);
}

void TftMini::fillRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t color) {
  if (x < 0) { w += x; x = 0; }
  if (y < 0) { h += y; y = 0; }
  if (x + w > _width) w = _width - x;
  if (y + h > _height) h = _height - y;
  if (w <= 0 || h <= 0) return;

  uint32_t total = (uint32_t)w * h * 2;
  uint8_t hi = color >> 8, lo = color & 0xFF;

  beginTx();
  setWindow(x, y, w, h);
  while (total > 0) {
    size_t n = total < PIXBUF_BYTES ? total : PIXBUF_BYTES;
    for (size_t i = 0; i < n; i += 2) {   // jedes Mal neu fuellen (SPI liest zurueck)
      pixbuf[i] = hi;
      pixbuf[i + 1] = lo;
    }
    writeBuffer(pixbuf, n);
    total -= n;
  }
  endTx();
}

void TftMini::fillScreen(uint16_t color) {
  fillRect(0, 0, _width, _height, color);
}

// Wandelt UTF-8 in Glyph-Indizes um. Unbekannte Zeichen werden zu '?'.
uint8_t TftMini::decodeGlyphs(const char *s, uint8_t *out, uint8_t maxOut) {
  uint8_t n = 0;
  const uint8_t *p = (const uint8_t *)s;
  while (*p && n < maxOut) {
    uint32_t cp;
    uint8_t c = *p;
    if (c < 0x80) {
      cp = c; p += 1;
    } else if ((c & 0xE0) == 0xC0 && p[1]) {
      cp = ((uint32_t)(c & 0x1F) << 6) | (p[1] & 0x3F); p += 2;
    } else if ((c & 0xF0) == 0xE0 && p[1] && p[2]) {
      cp = ((uint32_t)(c & 0x0F) << 12) | ((uint32_t)(p[1] & 0x3F) << 6) | (p[2] & 0x3F); p += 3;
    } else if ((c & 0xF8) == 0xF0 && p[1] && p[2] && p[3]) {
      cp = '?'; p += 4;
    } else {
      cp = '?'; p += 1;
    }

    uint8_t g;
    if (cp >= FONT_ASCII_FIRST && cp <= FONT_ASCII_LAST) g = cp - FONT_ASCII_FIRST;
    else if (cp == 0xE4) g = FONT_EXTRA_AE_LOWER;
    else if (cp == 0xF6) g = FONT_EXTRA_OE_LOWER;
    else if (cp == 0xFC) g = FONT_EXTRA_UE_LOWER;
    else if (cp == 0xC4) g = FONT_EXTRA_AE_UPPER;
    else if (cp == 0xD6) g = FONT_EXTRA_OE_UPPER;
    else if (cp == 0xDC) g = FONT_EXTRA_UE_UPPER;
    else if (cp == 0xDF) g = FONT_EXTRA_SZ;
    else if (cp == 0xB0) g = FONT_EXTRA_DEGREE;
    else g = '?' - FONT_ASCII_FIRST;
    out[n++] = g;
  }
  return n;
}

int16_t TftMini::drawText(int16_t x, int16_t y, const char *utf8, uint16_t fg,
                          uint16_t bg, uint8_t scale, int16_t fillWidth) {
  if (scale < 1) scale = 1;
  if (scale > 4) scale = 4;
  if (x < 0 || y < 0 || x >= _width || y >= _height) return 0;

  uint8_t glyphs[160 / FONT_ADV + 1];
  uint8_t n = decodeGlyphs(utf8, glyphs, sizeof(glyphs));

  const int16_t cellW = FONT_ADV * scale;
  int16_t w = n * cellW;
  if (fillWidth > w) w = fillWidth;
  if (x + w > _width) w = _width - x;
  int16_t h = FONT_H * scale;
  if (y + h > _height) h = _height - y;
  if (w <= 0 || h <= 0) return 0;

  const uint8_t fgHi = fg >> 8, fgLo = fg & 0xFF;
  const uint8_t bgHi = bg >> 8, bgLo = bg & 0xFF;
  const int16_t rowsPerChunk = PIXBUF_BYTES / (w * 2);

  beginTx();
  setWindow(x, y, w, h);
  int16_t row = 0;
  while (row < h) {
    int16_t rows = h - row;
    if (rows > rowsPerChunk) rows = rowsPerChunk;
    size_t i = 0;
    for (int16_t r = row; r < row + rows; r++) {
      uint8_t bit = 1 << (r / scale);
      for (int16_t c = 0; c < w; c++) {
        int16_t gi = c / cellW;
        int16_t gx = (c % cellW) / scale;
        bool on = gi < n && gx < FONT_W && (FONT5X7[glyphs[gi] * FONT_W + gx] & bit);
        pixbuf[i++] = on ? fgHi : bgHi;
        pixbuf[i++] = on ? fgLo : bgLo;
      }
    }
    writeBuffer(pixbuf, i);
    row += rows;
  }
  endTx();
  return w;
}
