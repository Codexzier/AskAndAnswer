# TFT-Test für den Arduino UNO Q

Dieser Branch (`claude/tft-test`) enthält **nur** einen Test für das 1.8"‑TFT
(ST7735, 160x128) vom [TftPictureViewer](https://github.com/Codexzier/TftPictureViewer)‑Shield.
Kein KI‑Chat, keine Spracherkennung, kein Python – der Sketch zeigt nur einen
animierten Text (Lauftext, hüpfender Ball, Bildzähler).

## Was der Test macht

Der UNO Q hat an der Stelle, wo beim UNO R3 der 6‑polige **ICSP**‑Stecker sitzt,
einen Stecker namens **JSPI**. Dort liegen beim UNO Q **andere Signale als an
D11/D13**. Viele TFT‑Shields holen ihre Datenleitungen aber vom ICSP‑Stecker.

Deshalb probiert der Test nacheinander drei Arten der Ansteuerung, je 12 Sekunden,
danach beginnt er wieder von vorn. Die Nummer steht groß oben links:

| Nr. | Ansteuerung | Datenleitungen |
|---|---|---|
| **1** | Hardware‑SPI | D11 (MOSI) / D13 (SCK) |
| **2** | Software‑SPI | D11 / D13 |
| **3** | Software‑SPI | JSPI‑Stecker (ICSP‑Position) |

Eine Methode **funktioniert**, wenn ihre Nummer zu sehen ist **und** sich die
Animation bewegt. Funktioniert eine Methode nicht, bleibt das Bild der vorherigen
Methode stehen oder das Display wird weiß.

**Auswertung:**

| Sichtbar bei | Bedeutung |
|---|---|
| 1 und 2 | Shield nutzt D11/D13, Hardware‑SPI klappt (schnellste Variante) |
| nur 2 | Shield nutzt D11/D13, aber Hardware‑SPI klappt nicht |
| nur 3 | Shield nutzt den ICSP/JSPI‑Stecker |
| keine | Strom, Reset‑Pin (D9), CS (D10), DC (D8) oder Display‑Variante prüfen |

Außerdem:

* Die **eingebaute LED blinkt**, solange der Sketch läuft. Blinkt sie nicht, wurde
  der Sketch nicht geladen oder ist abgestürzt.
* Die **Farbbalken** oben müssen rot, grün, blau, weiß, gelb sein. Sind Rot und Blau
  vertauscht oder ist am Rand Pixelmüll, in `sketch/sketch.ino` `TFT_VARIANT` auf
  `TFT_GREENTAB` oder `TFT_REDTAB` ändern.
* Unten stehen Bildzähler, Bilder pro Sekunde und Restzeit der aktuellen Methode –
  daran sieht man auch, wie schnell die jeweilige Methode ist.

## Verdrahtung (wie TftPictureViewer)

| Modul | Pin | UNO Q |
|---|---|---|
| TFT | CS | D10 |
| TFT | A0 / DC | D8 |
| TFT | RESET | D9 |
| TFT | SDA / MOSI | D11 **oder** JSPI (ICSP) |
| TFT | SCK | D13 **oder** JSPI (ICSP) |
| SD | CS | D4 (wird nur deaktiviert) |

## Installation

Im Ordner der bereits geklonten App den Branch wechseln:

```bash
cd ~/ArduinoApps/AskAndAnswer
```

```bash
git fetch origin
```

```bash
git checkout claude/tft-test
```

```bash
arduino-app-cli app restart ~/ArduinoApps/AskAndAnswer
```

(Oder in App Lab die App neu starten. Falls der Ordner noch `aouda` heißt, den
Pfad entsprechend anpassen.)

Zurück zum Sprachassistenten:

```bash
git checkout claude/epic-hopper-vpw9wo
```

Alternativ als eigene App in einem eigenen Ordner:

```bash
cd ~/ArduinoApps
```

```bash
git clone -b claude/tft-test https://github.com/Codexzier/AskAndAnswer.git TftTest
```

## Lizenzen

Der 5x7‑Font in `sketch/font5x7.h` und die ST7735‑Init‑Sequenz stammen aus der
Adafruit GFX bzw. Adafruit ST7735 Library (BSD‑Lizenz, Copyright Adafruit Industries).
