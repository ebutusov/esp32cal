# Image server

Two independent parts that communicate through a directory:

- `generator.py` renders the 960x540 4bpp image (exactly 259200 bytes) and writes
  `image_YYYYmmdd_HHMMSS.bin` into the output directory (atomic write, old files pruned).
  Needs Pillow.
- `server.py` serves the newest `image_*.bin` of that directory to the ESP32 e-paper
  client on every request. Standard library only.

```
python -m venv venv && . venv/bin/activate
pip install -r requirements.txt                       # Pillow, generator only
python generator.py --out-dir images                  # generate once
python generator.py --out-dir images --interval 60    # regenerate every minute
python generator.py --out-dir images --png            # also write preview PNGs
python server.py --dir images --port 8080             # GET http://HOST:8080/image (or /)
```

`server.py` returns 503 until the first image exists. The generator can also be run from
cron instead of `--interval`. Options: `--keep N` (default 5) sets how many images stay.

Set `url` in the device `config.json` to `http://<server-ip>:8080/image`.

## Format
Row-major, no padding, 2 pixels per byte. Per the driver (`epd_draw_pixel`),
the LEFT (even x) pixel is the LOW nibble, the right pixel the HIGH nibble.
Nibble 0x0 = black, 0xF = white. `pack_4bpp()` does `(gray>>4) | (right_gray & 0xF0)`.

Edit `render()` in `generator.py` to change the content; it must return a 960x540 PIL image.
