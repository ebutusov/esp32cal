# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Image-frame firmware for the LilyGO T5 4.7" e-paper S3 (ESP32-S3, 16MB flash, octal PSRAM). On each wake it downloads a ready-made 960x540 4bpp image (raw, exactly 259200 bytes) from a server over plain HTTP and shows it on the panel. Built with **ESP-IDF** (CMake, project `cal32_epd47`), ported from an Arduino/PlatformIO app that used to be a weather station (leftover: `.pio` in `.gitignore`). The server lives in `server/`.

## Code style
- Indent with tabs, never spaces. Tab width is 2.
- Match this when writing or editing any file.
- Put the opening brace in the same line as if/while statement

## Build / flash

Requires an ESP-IDF environment (`IDF_PATH` set, e.g. via the ESP-IDF PowerShell/CMD shell). There are no tests or linter.

- `idf.py build`
- `idf.py -p COMx flash monitor` — flashes bootloader, partition table and app only. The SPIFFS image (built from `spiffs_image/` via `spiffs_create_partition_image` in the top-level [CMakeLists.txt](CMakeLists.txt), deliberately without `FLASH_IN_PROJECT`) is flashed separately with `idf.py -p COMx storage-flash`, which also overwrites `config.json`.
- Target/flash/PSRAM/console settings live in [sdkconfig.defaults](sdkconfig.defaults) (`sdkconfig` is generated and gitignored). After editing defaults, delete `sdkconfig` and re-run `idf.py set-target esp32s3` / build for them to take effect.
- Partition table: [partitions.csv](partitions.csv) — 4MB factory app, ~12MB `storage` SPIFFS, no OTA.

## Runtime configuration (SPIFFS)

Config is not compiled in. `/spiffs/config.json` (keys `ssid`, `password`, `url` (image server, required), `sleep` in minutes; template in [html/config_template.json](html/config_template.json)) and the gzipped config web UI `index.html.gz` (source `html/index.html`) are stored on the SPIFFS partition. See [html/README.txt](html/README.txt): copy both into the SPIFFS source directory and flash the filesystem image. The `data/`, `spiffs_image/` and `main/secrets.h` (no longer used) are gitignored — never print or commit their contents.

## Architecture

Single-shot, deep-sleep-driven flow in [main/app_main.cpp](main/app_main.cpp) (`app_main` runs once per wake; `g_boot_counter` in RTC memory survives sleep):

1. `display_init()` then read GPIO 21 (`XPIN_MAINTENANCE`, pulled up). **Low = maintenance mode**: start WiFi SoftAP `CAL32`, mDNS, mount SPIFFS, start the HTTP server ([main/mserver.cpp](main/mserver.cpp), serves the SPIFFS files / config UI and accepts config uploads), show connection info on the panel, and return (httpd task keeps running; no sleep; returning from `app_main` is fine in ESP-IDF). Every path that draws must call `epd_poweron()` first (and `epd_clear()` for a fresh screen) — without it the panel stays blank with no error.
2. Normal mode: mount SPIFFS → parse `config.json` (cJSON, IDF `json` component) → connect WiFi STA ([main/net_wifi.cpp](main/net_wifi.cpp)) → `updateImage()` downloads the image from `url` straight into the framebuffer (`http_get_to_buffer` in [main/net_http_client.cpp](main/net_http_client.cpp); requires HTTP 200 and exactly 259200 bytes) → WiFi off → on failure the framebuffer is reset to white and an error text is drawn → power on EPD, clear, `display_update()` → `esp_deep_sleep_start()` for `sleep` minutes.
3. WiFi failure: draws an error (with poweron/clear/update) and `esp_restart()`s once; if the previous reset reason was already `ESP_RST_SW` it sleeps instead to avoid a reboot loop.

Key modules:
- [main/display_ui.cpp](main/display_ui.cpp) — PSRAM framebuffer (`g_framebuffer`, allocated in `display_init()`), exposed via `display_framebuffer()` / `display_framebuffer_size()` / `display_clear_framebuffer()`; only error and maintenance text are drawn (font `main/fonts/opensans12b.h`). Nothing reaches the panel until `display_update()`, so the panel must already be powered on.
- [server/](server/) — two independent Python parts sharing a directory (see [server/README.md](server/README.md)): `generator.py` (Pillow, icalendar, recurring-ical-events; fetches the Google Calendar secret ICS URL from gitignored `server/config.json` (template: `config_template.json`; never print the URL), `render(events)` draws the agenda and returns a 960x540 PIL image; writes `image_*.bin` atomically, prunes old ones, skips writing on fetch failure) and `server.py` (stdlib only; serves the newest `image_*.bin` at `GET /image`, 503 until one exists). Run: `python generator.py --out-dir images [--interval 60] [--png]` and `python server.py --dir images --port 8080`.
- Image format: row-major 4bpp, 2 pixels/byte, even-x (left) pixel in the LOW nibble, right pixel in the HIGH nibble; 0x0 = black, 0xF = white. Matches the driver's `epd_draw_pixel`, so the buffer is copied straight into the framebuffer.
- `components/epd_driver` — local copy of the LilyGO e-paper driver (I2S data bus, RMT pulses, ed047tc1 panel). `components/zlib` is vendored; `mdns` comes from the IDF component manager ([main/idf_component.yml](main/idf_component.yml)). New IDF dependencies must be added to `REQUIRES` in [main/CMakeLists.txt](main/CMakeLists.txt).

## Editor

IntelliSense uses the Microsoft C/C++ extension (cpptools), not clangd — the `clangd.*` entries in `.vscode/settings.json` are inert (the tracked `.clangd` is only a flag filter). `.vscode/c_cpp_properties.json` points it at `build/compile_commands.json`, so run `idf.py build` first if includes show red squiggles. The `.vscode` config files are gitignored.

## Debugging

Uses the ESP-IDF VS Code extension with OpenOCD over the built-in USB-JTAG (`idf.openOcdConfigs` = `board/esp32s3-builtin.cfg`). If `.vscode/launch.json` is a generic `cppdbg` stub, delete it and run "ESP-IDF: Add VS Code Configuration Folder" to regenerate it. On Windows the JTAG interface needs the WinUSB driver (Zadig). USB drops in deep sleep, so debug in maintenance mode (GPIO 21 low) or break early in `app_main`.

## Gotchas

- Some `esp_wifi_*` calls (e.g. `esp_wifi_set_max_tx_power`) return `ESP_ERR_WIFI_NOT_STARTED` if called before `esp_wifi_start()`; with `ESP_ERROR_CHECK` this aborts at boot (see `wifi_connect_sta` in [main/net_wifi.cpp](main/net_wifi.cpp)).

- Main task stack is raised to 12KB in `sdkconfig.defaults` because WiFi + HTTP + JSON config parsing all run on it (could likely be lowered now that weather parsing is gone; untested); lowering it caused a stack-overflow panic.
- Console is the built-in USB Serial/JTAG (`CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG`), matching the board's `ARDUINO_USB_MODE=1`. The USB-OTG CDC console (`CONFIG_ESP_CONSOLE_USB_CDC`) does not enumerate until the app starts, so boot output is missed.
- The COM port disappears during deep sleep (USB is powered down) and re-enumerates on every wake, so `idf.py monitor` may need to be restarted or reconnect; the app only stays awake for a few seconds per cycle, except in maintenance mode (GPIO 21 low).
