# Image server

Two independent parts that communicate through a directory:

- `generator.py` downloads a Google Calendar (secret ICS URL), keeps events from today
  onwards, renders them as an agenda into a 960x540 4bpp image (exactly 259200 bytes) and
  writes `image_YYYYmmdd_HHMMSS.bin` into the output directory (atomic write, old files
  pruned). If the download fails nothing is written, so the previous image stays.
  Needs Pillow, icalendar, recurring-ical-events.
- `server.py` serves the newest `image_*.bin` of that directory to the ESP32 e-paper
  client on every request. Standard library only.

```
python -m venv venv && . venv/bin/activate
pip install -r requirements.txt                       # generator only
python generator.py --out-dir images                  # generate once
python generator.py --out-dir images --interval 60    # regenerate every minute
python generator.py --out-dir images --png            # also write preview PNGs
python server.py --dir images --port 8080             # GET http://HOST:8080/image (or /)
```

Copy `config_template.json` to `config.json` (gitignored) and set `ics_url` to the calendar's
"Secret address in iCal format" (Google Calendar settings); `days` (default 14) is how far
ahead to look. Use `--config PATH` for another location.

`server.py` returns 503 until the first image exists. The generator can also be run from
cron instead of `--interval`. Options: `--keep N` (default 5) sets how many images stay.

Set `url` in the device `config.json` to `http://<server-ip>:8080/image`.

## Format
Row-major, no padding, 2 pixels per byte. Per the driver (`epd_draw_pixel`),
the LEFT (even x) pixel is the LOW nibble, the right pixel the HIGH nibble.
Nibble 0x0 = black, 0xF = white. `pack_4bpp()` does `(gray>>4) | (right_gray & 0xF0)`.

Edit `render(events)` in `generator.py` to change the layout; it must return a 960x540 PIL image. It draws a 540x960 portrait page and rotates it counter-clockwise by `ROTATE` (90; use 270 for the other mounting direction).
