# esp32cal

A low-power **Google Calendar agenda on a 4.7" e-paper display**.

The firmware runs on a [LilyGO T5 4.7" e-paper S3](https://github.com/Xinyuan-LilyGO/LilyGo-EPD47) (ESP32-S3) and contains no calendar or rendering logic. Each time it wakes from deep sleep, it downloads a finished 960×540 grayscale image from a small server on your network, shows it, and goes back to sleep. All the layout work happens in Python on the server, so you can change the design without reflashing the device.

```
 Google Calendar API                    your LAN
        │  (OAuth, read-only)
        ▼
 ┌──────────────┐  image_*.bin  ┌─────────────┐   GET /image   ┌──────────────────┐
 │ generator.py │ ────────────▶ │  server.py  │ ◀───────────── │ ESP32-S3 + EPD47 │
 │ (Pillow)     │   directory   │ (stdlib)    │   raw 4bpp     │ wake → draw →    │
 └──────────────┘               └─────────────┘   259200 bytes │ deep sleep       │
                                                               └──────────────────┘
```

## Features

- **Deep-sleep driven:** the device wakes, makes one HTTP request, refreshes the panel and sleeps for a configurable number of minutes.
- **Server-side rendering:** `generator.py` draws a portrait agenda for the next N days from one or more Google calendars. Edit `render()` to make it look however you like.
- **No secrets in the firmware:** WiFi credentials, the server URL and the sleep interval live in `config.json` on the SPIFFS partition.
- **Maintenance mode:** pull GPIO 21 low and the device starts its own WiFi access point with a small web page for editing the configuration.
- **Error handling:** if the download fails or the image is invalid, the panel shows an error message. If WiFi fails, the device retries with one reboot and then sleeps instead of boot-looping.

## Repository layout

| Path | Contents |
| --- | --- |
| [main/](main/) | ESP-IDF application: wake flow, WiFi, HTTP client, maintenance web server, display |
| [components/epd_driver/](components/epd_driver/) | Local copy of the LilyGO ED047TC1 e-paper driver |
| [components/zlib/](components/zlib/) | Vendored zlib |
| [html/](html/) | Configuration web UI (`index.html` and its gzipped copy) and the `config.json` template |
| [server/](server/) | Python image generator and image server ([server/README.md](server/README.md)) |
| [partitions.csv](partitions.csv) | 4 MB factory app and about 12 MB of SPIFFS storage, no OTA |

## Hardware

- LilyGO T5 4.7" e-paper **S3** (ESP32-S3, 16 MB flash, octal PSRAM, ED047TC1 960×540 panel)
- Optional: a jumper or switch from **GPIO 21** to GND to enter maintenance mode

## Getting started

### 1. Run the server

You need Python 3, a Google account and a one-time Google Cloud OAuth setup. [server/README.md](server/README.md) walks through it step by step.

```sh
cd server
python -m venv venv && . venv/bin/activate
pip install -r requirements.txt
cp config_template.json config.json      # choose calendars and number of days
# save the OAuth client as client_secret.json (see server/README.md)
python generator.py --auth               # one-time consent, writes token.json

python generator.py --out-dir images --interval 60 &
python server.py --dir images --port 8080
```

`http://<server-ip>:8080/image` now returns the latest image. Add `--png` to the generator to also write preview PNGs.

### 2. Build and flash the firmware

This step needs [ESP-IDF](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/get-started/) installed, with `IDF_PATH` set. The project is developed against v6.1. The `mdns` and `cjson` components are fetched automatically by the IDF component manager.

```sh
idf.py set-target esp32s3
idf.py build
idf.py -p COMx flash monitor
```

> **Change the maintenance access-point password** before flashing. It is hardcoded as `AP_PASS` in [main/app_main.cpp](main/app_main.cpp).

### 3. Configure the device

The device reads `/spiffs/config.json`:

```json
{
  "ssid": "your-wifi",
  "password": "your-wifi-password",
  "url": "http://192.168.1.10:8080/image",
  "sleep": 20
}
```

`sleep` is in minutes. There are two ways to load the configuration.

**Option A: flash the filesystem image.** Create a `spiffs_image/` directory (it is gitignored). Copy `config.json`, based on [html/config_template.json](html/config_template.json), and [html/index.html.gz](html/index.html.gz) into it. Then run:

```sh
idf.py -p COMx storage-flash
```

`storage-flash` replaces the whole SPIFFS partition, including any `config.json` already on the device.

**Option B: use maintenance mode.** Flash the filesystem image once so that the web UI is on the device. After that:

1. Hold GPIO 21 low while the device boots.
2. Join the `CAL32` WiFi network. The password and the device's IP address are shown on the panel.
3. Open the IP address in a browser, enter your settings and click **Save**.
4. Release GPIO 21 and reset the device.

## Image format

The image is raw data with no header: exactly **259200 bytes** (960 × 540 / 2).

- Row-major, 4 bits per pixel, 2 pixels per byte, no padding
- Left (even x) pixel in the **low** nibble, right pixel in the **high** nibble
- `0x0` = black, `0xF` = white

This is the e-paper driver's own framebuffer layout, so the firmware copies the bytes straight into its buffer. Any program that produces this format can drive the display, not only the calendar generator.

## Debugging notes

- The console runs over the board's built-in USB Serial/JTAG. The USB port turns off during deep sleep, so `idf.py monitor` may need to reconnect after each wake.
- To debug with JTAG (OpenOCD, `board/esp32s3-builtin.cfg`), use maintenance mode, which keeps the device awake.

## License

[GPL-3.0](LICENSE). Vendored third-party components keep their own licences, listed below.

## Credits

- E-paper driver adapted from [Xinyuan-LilyGO/LilyGo-EPD47](https://github.com/Xinyuan-LilyGO/LilyGo-EPD47) (GPL-3.0)
- [zlib](https://zlib.net/) by Jean-loup Gailly and Mark Adler (zlib license)
- [DejaVu Sans](https://dejavu-fonts.github.io/) font, licence in [server/fonts/LICENSE-DejaVu.txt](server/fonts/LICENSE-DejaVu.txt)
- [Open Sans](https://fonts.google.com/specimen/Open+Sans) bitmap font for the on-device messages
