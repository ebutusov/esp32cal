# Image server

Two independent parts that communicate through a directory:

- `generator.py` reads Google Calendar events through the Calendar API (OAuth, read-only), keeps events from today
  onwards, renders them as an agenda into a 960x540 4bpp image (exactly 259200 bytes) and
  writes `image_YYYYmmdd_HHMMSS.bin` into the output directory (atomic write, old files
  pruned). If the download fails nothing is written, so the previous image stays.
  Needs Pillow, google-auth, google-auth-oauthlib.
- `server.py` serves the newest `image_*.bin` of that directory to the ESP32 e-paper
  client on every request. Standard library only.

```
python -m venv venv && . venv/bin/activate
pip install -r requirements.txt                       # generator only
python generator.py --auth                            # once: Google consent, writes token.json
python generator.py --out-dir images                  # generate once
python generator.py --out-dir images --interval 60    # regenerate every minute
python generator.py --out-dir images --png            # also write preview PNGs
python server.py --dir images --port 8080             # GET http://HOST:8080/image (or /)
```

Copy `config_template.json` to `config.json` (gitignored). Keys: `calendars` (list of calendar
IDs, default `["primary"]`; other IDs are in Google Calendar > Settings > calendar > "Integrate
calendar"), `days` (default 14) how far ahead to look, `client_secret` / `token` file paths
(relative to the config, defaults `client_secret.json` / `token.json`, both gitignored).
Use `--config PATH` for another location.

## Google Cloud setup (once)

1. https://console.cloud.google.com: create a project (e.g. "esp32cal").
2. APIs & Services > Library: enable **Google Calendar API**.
3. Google Auth Platform (the OAuth consent screen): Get started, set an app name and support
   email, Audience **External** (Internal only exists for Workspace accounts), contact email.
4. Data Access: add the scope `https://www.googleapis.com/auth/calendar.readonly`.
5. Audience: click **Publish app** (status "In production"). In "Testing" status refresh
   tokens expire after 7 days, so the generator would need `--auth` every week. No
   verification is needed for your own account; the consent page shows "Google hasn't
   verified this app" - Advanced > Go to ... (unsafe).
6. Clients > Create client > Application type **Desktop app** > Create, then download the JSON
   and save it as `server/client_secret.json`.
7. `python generator.py --auth` opens the consent page and saves `token.json` (refresh token).
   On a headless host: `python generator.py --auth --no-browser`, tunnel the redirect port
   from your PC with `ssh -L 8090:localhost:8090 host`, open the printed URL locally. Or
   run `--auth` on a PC and copy `token.json` to the server.

If the token is revoked (Google account > Security > Third-party access) or expires, the
generator logs `RefreshError ... run with --auth again` and keeps the previous image.

`server.py` returns 503 until the first image exists. The generator can also be run from
cron instead of `--interval`. Options: `--keep N` (default 5) sets how many images stay.

Set `url` in the device `config.json` to `http://<server-ip>:8080/image`.

## Format
Row-major, no padding, 2 pixels per byte. Per the driver (`epd_draw_pixel`),
the LEFT (even x) pixel is the LOW nibble, the right pixel the HIGH nibble.
Nibble 0x0 = black, 0xF = white. `pack_4bpp()` does `(gray>>4) | (right_gray & 0xF0)`.

Edit `render(events)` in `generator.py` to change the layout; it must return a 960x540 PIL image. It draws a 540x960 portrait page and rotates it counter-clockwise by `ROTATE` (90; use 270 for the other mounting direction).
