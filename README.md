# AOUDA – Sprachassistent für den Arduino UNO Q

Eine Arduino‑App für den **Arduino UNO Q** mit **UNO Media Carrier** (Mikrofon)
und dem **1.8" TFT‑Shield mit SD‑Karte** aus dem
[TftPictureViewer](https://github.com/Codexzier/TftPictureViewer).

| Sprachbefehl | Funktion |
|---|---|
| **„AOUDA, ich habe eine Frage“** | AOUDA hört zu und beantwortet die Frage mit einer **lokalen KI**. Kann die KI die Frage nicht beantworten oder braucht sie aktuelle Daten, **sucht sie im Internet**. |
| **„AOUDA, starte Aufnahme“** | Nimmt bis zu **10 Minuten** auf, zeigt dabei live den erkannten Text und erstellt danach das **Transkript**. |
| **„AOUDA, stoppe Aufnahme“** | Beendet die Aufnahme vorzeitig. |

Frage, Antwort, Live‑Text und Transkript erscheinen auf dem TFT. Lange Texte
werden automatisch seitenweise durchgeblättert.

## Funktionsweise

```
Mikrofon (Media Carrier)
   │ 16 kHz Audio
   ▼
Linux (Qualcomm QRB2210) ── python/main.py
   ├─ Vosk (offline, Echtzeit)       Weckwort, Frage, Live-Diktat
   ├─ arduino:llm Brick              Qwen 3.5 0.8B (llama.cpp, < 1 GB RAM)
   ├─ Internetsuche                  DuckDuckGo (ddgs), Wikipedia als Fallback
   └─ Aufnahme                       data/recordings/*.wav + *.txt
   │ Bridge (RPC)
   ▼
Mikrocontroller (STM32U585) ── sketch/sketch.ino
   └─ TFT ST7735 160x128              eigener schlanker Treiber, nur SPI.h
```

* **Lokale KI:** `llamacpp:Qwen3.5-0.8B-Q4_0` über die offizielle
  `arduino:llm`‑Brick. Modelldatei ca. 484 MB; mit `LLAMA_ARG_CTX_SIZE=4096`
  (in `app.yaml`) bleibt der llama.cpp‑Server unter 1 GB Arbeitsspeicher.
* **Internetsuche:** Fragen mit „heute“, „aktuell“, „Wetter“, Preisen, Jahreszahlen
  usw. werden direkt gesucht. Sonst antwortet zuerst das lokale Modell; antwortet es
  mit `SUCHE: …` oder ist es erkennbar unsicher („weiß ich nicht“), werden die
  Suchergebnisse geholt und das Modell antwortet damit. Die Quelle steht in der
  Fußzeile.
* **Display:** Die Adafruit‑Bibliotheken ziehen Abhängigkeiten (BusIO, seesaw, SD)
  nach, deren Unterstützung im Zephyr‑Core des UNO Q nicht gesichert ist. Der Sketch
  bringt deshalb einen eigenen kleinen ST7735‑Treiber mit (gleiche Init‑Sequenz wie
  `Adafruit_ST7735::initR`, 5x7‑Font mit ä ö ü ß °).

### Geht Speech‑to‑Text in Echtzeit?

**Ja.** Vosk erkennt die Sprache, während gesprochen wird: vorläufiger Text
erscheint nach wenigen hundert Millisekunden (gelb), fertige Sätze nach einer kurzen
Sprechpause (weiß). Das kleine deutsche Modell (`vosk-model-small-de-0.15`,
ca. 45 MB, 200–300 MB RAM) schafft das auf einem Kern des UNO Q. Man sieht es bei der
Frage und während der Aufnahme direkt auf dem TFT.

Die Vosk‑Erkennung ist schnell, aber nicht perfekt (keine Satzzeichen, kleines
Vokabular). Für genauere Transkripte kann nach der Aufnahme zusätzlich
**faster‑whisper** laufen (siehe [Konfiguration](#konfiguration)) – das dauert auf
dem UNO Q aber ungefähr so lange wie die Aufnahme selbst.

## Hardware

* Arduino UNO Q (2 GB oder 4 GB)
* Arduino UNO Media Carrier, Mikrofon am Mikrofon/Kopfhörer‑Klinkenanschluss
  (alternativ ein USB‑Mikrofon)
* 1.8" TFT‑Shield (ST7735, 160x128) mit SD‑Kartenleser – Verdrahtung wie beim
  TftPictureViewer:

| Modul    | Pin        | UNO Q |
|----------|------------|-------|
| TFT      | CS         | D10   |
| TFT      | A0 / DC    | D8    |
| TFT      | RESET      | D9    |
| TFT + SD | SDA / MOSI | D11   |
| TFT + SD | SCK        | D13   |
| SD       | MISO       | D12   |
| SD       | CS         | D4 (wird nur deaktiviert) |

> **Wichtig beim UNO Q:** Der 6‑polige Stecker **JSPI** (dort, wo beim UNO R3 der
> ICSP‑Stecker sitzt) führt beim UNO Q **nicht** dieselben Signale wie D11/D13.
> Viele 1,8"‑TFT‑Shields holen MOSI/SCK aber vom ICSP‑Stecker – auf dem UNO R3
> fällt das nicht auf, auf dem UNO Q bleibt das Display dann leer. Der Sketch
> steuert deshalb standardmäßig **beide** Anschlüsse gleichzeitig per Software‑SPI
> an (`TFT_BUS_BOTH`). Das funktioniert immer, ein kompletter Bildaufbau dauert
> aber ca. 1 s. Wenn du weißt, dass dein Shield D11/D13 nutzt, stelle in
> `sketch/sketch.ino` `TFT_BUS` auf `TFT_BUS_HW_SPI` (deutlich schneller).

## Installation (per Git direkt auf dem UNO Q)

Arduino‑Apps liegen auf dem Board unter `/home/arduino/ArduinoApps/`. Das
Repository ist direkt eine App (`app.yaml`, `python/`, `sketch/` im Hauptordner).

1. Auf dem UNO Q ein Terminal öffnen (SSH oder im Einplatinen‑Modus) und das
   Repository klonen:

   ```bash
   cd ~/ArduinoApps
   ```

   ```bash
   git clone -b claude/epic-hopper-vpw9wo https://github.com/Codexzier/AskAndAnswer.git
   ```

2. App starten – entweder in **Arduino App Lab** unter „Meine Apps“ → *AOUDA
   Sprachassistent* → **Start**, oder ohne App Lab im Terminal:

   ```bash
   arduino-app-cli app start ~/ArduinoApps/AskAndAnswer
   ```

   Beim ersten Start werden der Sketch kompiliert und geflasht, die
   Python‑Pakete installiert und das KI‑Modell (ca. 484 MB) geladen. Danach lädt
   die App das Vosk‑Sprachmodell (ca. 45 MB, Fortschritt auf dem TFT).

3. Ausgaben/Fehler ansehen:

   ```bash
   arduino-app-cli app logs ~/ArduinoApps/AskAndAnswer
   ```

4. Aktualisieren:

   ```bash
   cd ~/ArduinoApps/AskAndAnswer && git pull
   ```

   ```bash
   arduino-app-cli app restart ~/ArduinoApps/AskAndAnswer
   ```

Falls das KI‑Modell nicht automatisch geladen wird:

```bash
arduino-app-cli model install llamacpp:Qwen3.5-0.8B-Q4_0
```

Falls kein Mikrofon gefunden wird: prüfen, ob der Media Carrier aktiviert ist
(`arduino-linux-config carrier show`, aktivieren siehe
`arduino-linux-config carrier --help`) und ob das Mikrofon erscheint (`arecord -l`).

## Bedienung

### Bildschirmaufbau

```
┌────────────────────────────┐
│ AOUDA ist bereit           │  Kopfzeile (Modus)
│ Sprachbefehle:             │
│ AOUDA, ich habe eine       │  weiß = Befehl verfügbar
│   Frage                    │
│ AOUDA, starte Aufnahme     │  grün = Befehl erkannt
│ AOUDA, stoppe Aufnahme     │  grau = nur während einer Aufnahme
│   (nur während Aufnahme)   │
│ > auto ich habe            │  Fußzeile: was gerade gehört wird
├────────────────────────────┤
│ CPU 14% RAM 63% Mic -32dB  │  Statuszeile
│ ████████████░░░░░░░░░░░░░░ │  Mikrofonpegel
└────────────────────────────┘
```

* **Befehlsübersicht:** Wird ein Sprachbefehl erkannt, wechselt sein Satz von
  **weiß auf grün** und die Fußzeile zeigt z. B. „Erkannt: Aufnahme starten“.
  Nach 0,8 s wechselt der Bildschirm. Während der Aufnahme steht
  „AOUDA, stoppe Aufnahme“ weiß in der Fußzeile und wird beim Erkennen grün.
* **Fußzeile:** `> …` zeigt live, was die Spracherkennung gerade hört.
  `? …` heißt: gehört, aber nicht als Befehl erkannt. „? nicht verstanden“
  heißt: Sprache erkannt, aber nichts Passendes.
* **Statuszeile:** CPU‑Last und RAM‑Belegung des ganzen Boards (grün / gelb ab
  50 % bzw. 70 % / rot ab 80 % bzw. 85 %) und der Mikrofonpegel in dBFS. Der
  Balken ganz unten zeigt den Pegel von -60 dB (leer) bis 0 dB (voll): grau =
  leise, **grün = Sprache** (ab -42 dB), rot = Übersteuerung (ab -3 dB).
  Bewegt sich der Balken beim Sprechen nicht, kommt kein Ton vom Mikrofon an.
* Antworten und Transkripte bleiben 60 s stehen (lange Texte werden
  durchgeblättert), danach erscheint wieder die Befehlsübersicht.

### Ablauf

1. Nach dem Start zeigt das TFT **„AOUDA ist bereit“** mit allen Sprachbefehlen.
2. **„AOUDA, ich habe eine Frage“** → der Satz wird grün → Kopfzeile *Deine
   Frage?* → Frage stellen. Nach 1,5 s Pause wird die Frage abgeschickt. Der
   Antworttext erscheint, während die KI ihn erzeugt. Lange Antworten werden
   durchgeblättert (`1/3`, `2/3`, …).
3. **„AOUDA, starte Aufnahme“** → der Satz wird grün → rote Kopfzeile `REC 00:12 / 10:00` mit
   Fortschrittsbalken und Live‑Text. Ende mit **„AOUDA, stoppe Aufnahme“** oder
   automatisch nach 10 Minuten. Danach wird das Transkript angezeigt.

Aufnahmen und Transkripte liegen in `~/ArduinoApps/AskAndAnswer/data/recordings/`
(`aufnahme_JJJJMMTT_HHMMSS.wav` und `.txt`).

### Wenn das Display nichts anzeigt

Direkt nach dem Flashen zeigt der Sketch **ohne Python** ein Testbild: oben fünf
Farbbalken (rot, grün, blau, weiß, gelb), darunter „AOUDA“, der verwendete Bus und
„Warte auf Linux…“.

| Was du siehst | Ursache / Lösung |
|---|---|
| Hintergrundbeleuchtung aus | Shield bekommt keinen Strom (5V/3.3V/GND) oder sitzt nicht richtig |
| Weiß, kein Testbild | Sketch läuft nicht (App‑Log prüfen, Sketch kompiliert?) oder Signale kommen nicht an (Pins prüfen) |
| Testbild mit falschen Farben / Rand | `TFT_VARIANT` auf `TFT_GREENTAB` oder `TFT_REDTAB` stellen |
| Testbild ok, bleibt bei „Warte auf Linux…“ | Python‑Teil läuft nicht: `arduino-app-cli app logs ~/ArduinoApps/AskAndAnswer` |

Im Log steht beim Start `TFT: AOUDA-TFT 160x128 Soft-SPI D11/D13+JSPI`, wenn
Python den Sketch erreicht, sonst `TFT: nicht erreichbar`.

### Tipps zum Weckwort „AOUDA“

„AOUDA“ ist kein deutsches Wort. Die Erkennung arbeitet deshalb standardmäßig mit
einer festen Grammatik aus Wörtern, die das Sprachmodell kennt und die wie „Auda“
klingen (z. B. „auto“, „audi“, „oda“) – kombiniert mit dem Befehlssatz. Zusätzlich
wird der Text phonetisch (Kölner Phonetik) und unscharf verglichen.

* Zuerst auf den Pegelbalken achten: Er muss beim Sprechen grün werden. Bleibt er
  grau, ist das Mikrofon zu leise oder das falsche Gerät ausgewählt (`mic_device`).
* Wird ein Satz nicht als Befehl erkannt, steht er mit `?` in der Fußzeile und im
  Log (`Gehoert: '...'`). Steht dahinter eine Zahl in Klammern, war die Konfidenz
  zu niedrig (→ `min_confidence` senken).
* Taucht dort eine andere Schreibweise auf, diese in `wake_words` in
  `python/config.py` ergänzen.
* Klappt es gar nicht, `wake_mode` auf `"free"` stellen (freie Erkennung +
  unscharfer Vergleich) oder `min_confidence` senken.

## Konfiguration

Die Standardwerte stehen in [`python/config.py`](python/config.py) und können dort
geändert werden (oder per Umgebungsvariable):

| Einstellung | Umgebungsvariable | Standard | Bedeutung |
|---|---|---|---|
| `mic_device` | `AOUDA_MIC` | `0` | `0` = erstes Mikrofon, `jack:1` = Klinke am Media Carrier, `usb:1` = USB‑Mikrofon |
| `wake_mode` | `AOUDA_WAKE_MODE` | `grammar` | `grammar` oder `free` |
| `wake_words` | `AOUDA_WAKE_WORDS` | siehe Datei | Schreibweisen von „AOUDA“ (kommagetrennt) |
| `min_confidence` | `AOUDA_MIN_CONFIDENCE` | `0.55` | Mindest‑Konfidenz eines Befehls |
| `question_pause_s` | `AOUDA_QUESTION_PAUSE` | `1.5` | Sprechpause, nach der die Frage abgeschickt wird |
| `web_search` | `AOUDA_WEB_SEARCH` | `true` | Internetsuche erlauben |
| `record_max_s` | `AOUDA_RECORD_MAX` | `600` | maximale Aufnahmedauer (Sekunden) |
| `transcribe_engine` | `AOUDA_TRANSCRIBE` | `vosk` | `vosk` (Echtzeit) oder `whisper` |
| `whisper_model` | `AOUDA_WHISPER_MODEL` | `base` | `tiny`, `base`, `small` … |
| `page_seconds` | `AOUDA_PAGE_SECONDS` | `7` | Anzeigedauer pro Seite |
| `confirm_s` | `AOUDA_CONFIRM_SECONDS` | `0.8` | so lange bleibt ein erkannter Befehl grün stehen |
| `result_hold_s` | `AOUDA_RESULT_SECONDS` | `60` | Anzeigedauer von Antwort/Transkript, danach Befehlsübersicht |

Für `whisper` zusätzlich in `python/requirements.txt` die Zeile
`faster-whisper==1.2.1` aktivieren.

Display‑Variante, Pins und SPI‑Takt stehen oben in
[`sketch/sketch.ino`](sketch/sketch.ino) (`TFT_VARIANT` = `TFT_BLACKTAB` wie im
TftPictureViewer; bei falschen Farben `TFT_GREENTAB` oder `TFT_REDTAB`).

## Speicherbedarf (ungefähr)

| Komponente | RAM |
|---|---|
| llama.cpp mit Qwen 3.5 0.8B Q4_0, 4096 Token Kontext | ca. 0,6–0,8 GB |
| Vosk small‑de (2 Erkenner) | ca. 0,3 GB |
| Python‑App | ca. 0,1 GB |
| optional faster‑whisper `base` (nur während der Transkription) | ca. 0,3 GB |

## Entwicklung / Tests

Die Logik (Befehlserkennung, Display‑Layout, KI‑Ablauf, Aufnahme) lässt sich ohne
Hardware testen; die Arduino‑Module werden dabei durch Attrappen ersetzt:

```bash
pip install pytest numpy
```

```bash
python -m pytest tests
```

## Lizenzen

Der 5x7‑Font in `sketch/font5x7.h` und die ST7735‑Init‑Sequenz stammen aus der
Adafruit GFX bzw. Adafruit ST7735 Library (BSD‑Lizenz, Copyright Adafruit
Industries).
