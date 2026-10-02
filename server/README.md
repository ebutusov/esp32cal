# Image server

Serves a 960x540, 4bpp raw image (exactly 259200 bytes) to the ESP32 e-paper client.

    python -m venv venv && . venv/bin/activate
    pip install -r requirements.txt
    python server.py --port 8080            # GET http://HOST:8080/image (or /)
    python server.py --dump out.png --dump-raw out.bin   # offline inspection

Set `url` in the device `config.json` to `http://<server-ip>:8080/image`.

## Format
Row-major, no padding, 2 pixels per byte. Per the driver (`epd_draw_pixel`),
the LEFT (even x) pixel is the LOW nibble, the right pixel the HIGH nibble.
Nibble 0x0 = black, 0xF = white. `pack_4bpp()` does `(gray>>4) | (right_gray & 0xF0)`.

Edit `render()` to change the content; it must return a 960x540 PIL image.
