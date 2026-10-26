#!/usr/bin/env python3
"""Renders a Google Calendar agenda as a 960x540 4bpp e-paper image.

Events are read from the Google Calendar API with OAuth (read-only scope).
Authorize once with --auth: it opens the Google consent page and stores a
refresh token in token.json; later runs refresh the access token silently.
Each run writes a new file image_YYYYmmdd_HHMMSS.bin (atomically) and prunes
old ones. The web server (server.py) always serves the newest file. If the
calendar cannot be fetched, nothing is written and the previous image stays.

Third-party dependencies: Pillow, google-auth, google-auth-oauthlib.
"""
import argparse
import datetime
import glob
import json
import os
import sys
import time
import urllib.parse

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from PIL import Image, ImageDraw, ImageFont

WIDTH = 960
HEIGHT = 540
IMAGE_SIZE = WIDTH * HEIGHT // 2  # 259200
ROTATE = 90  # portrait canvas rotated counter-clockwise (90 or 270; 270 = the other mounting direction)
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
API = "https://www.googleapis.com/calendar/v3"
PREFIX = "image_"
SUFFIX = ".bin"

# Bundled font (see fonts/LICENSE-DejaVu.txt) so rendering is identical on every platform.
FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "DejaVuSans-Bold.ttf")


def load_font(size):
	return ImageFont.truetype(FONT_PATH, size)


def load_config(path):
	"""Read config.json; client_secret/token paths are relative to its directory."""
	with open(path, encoding="utf-8") as f:
		cfg = json.load(f)
	base = os.path.dirname(os.path.abspath(path))
	cfg.setdefault("days", 14)
	cfg.setdefault("calendars", ["primary"])
	cfg["client_secret"] = os.path.join(base, cfg.get("client_secret", "client_secret.json"))
	cfg["token"] = os.path.join(base, cfg.get("token", "token.json"))
	return cfg


def save_token(path, creds):
	write_atomic(path, creds.to_json().encode("utf-8"))


def authorize(cfg, port, open_browser):
	"""Interactive OAuth consent (Desktop app flow); stores the refresh token."""
	flow = InstalledAppFlow.from_client_secrets_file(cfg["client_secret"], SCOPES)
	# prompt=consent makes Google return a refresh token even on re-authorization
	creds = flow.run_local_server(port=port, open_browser=open_browser, prompt="consent")
	save_token(cfg["token"], creds)
	print("token saved to %s" % cfg["token"])


def load_credentials(cfg):
	if not os.path.exists(cfg["token"]):
		raise RuntimeError("%s not found, run with --auth first" % cfg["token"])
	creds = Credentials.from_authorized_user_file(cfg["token"], SCOPES)
	if not creds.valid:
		creds.refresh(Request())
		save_token(cfg["token"], creds)
	return creds


def parse_time(t):
	"""API start/end -> (date or aware local datetime, all_day)."""
	if "date" in t:
		return datetime.date.fromisoformat(t["date"]), True
	return datetime.datetime.fromisoformat(t["dateTime"]).astimezone(), False


def fetch_events(session, calendars, days):
	"""Return [(start, end, summary, all_day, location)] for today and the next days, sorted.

	Starts at today's local midnight, so events of the current day (even ones
	already started) are kept and earlier days are dropped. Recurring events are
	expanded by the API (singleEvents). All-day end dates are exclusive, as in ICS.
	"""
	today = datetime.datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
	params = {
		"timeMin": today.isoformat(),
		"timeMax": (today + datetime.timedelta(days=days)).isoformat(),
		"singleEvents": "true",
		"orderBy": "startTime",
		"maxResults": 250,
	}
	events = []
	for cal_id in calendars:
		url = "%s/calendars/%s/events" % (API, urllib.parse.quote(cal_id, safe=""))
		params.pop("pageToken", None)
		while True:
			r = session.get(url, params=params, timeout=20)
			r.raise_for_status()
			data = r.json()
			for item in data.get("items", []):
				if item.get("status") == "cancelled":
					continue
				start, all_day = parse_time(item["start"])
				end = parse_time(item["end"])[0] if "end" in item else start
				location = " ".join(item.get("location", "").split())
				events.append((start, end, item.get("summary", "(no title)"), all_day, location))
			if not data.get("nextPageToken"):
				break
			params["pageToken"] = data["nextPageToken"]
	# within a day: all-day first, then by start time
	events.sort(key=lambda e: (not e[3], 0 if e[3] else e[0].timestamp()))
	return events


def event_days(ev, today):
	"""Dates (>= today) an event is shown on; multi-day events repeat on each day."""
	start, end, _, all_day, _ = ev
	first = start if all_day else start.date()
	last = end if all_day else end.date()
	if all_day or (not all_day and end > start and end.time() == datetime.time(0)):
		last -= datetime.timedelta(days=1)  # DTEND is exclusive
	last = max(last, first)
	d = max(first, today)
	while d <= last:
		yield d
		d += datetime.timedelta(days=1)


def day_label(d, today):
	if d == today:
		return "Today " + d.strftime("%a %d %b")
	if d == today + datetime.timedelta(days=1):
		return "Tomorrow " + d.strftime("%a %d %b")
	return d.strftime("%a %d %b")


def fit(d, text, font, max_w):
	"""Truncate text with an ellipsis so it fits max_w pixels."""
	if d.textlength(text, font=font) <= max_w:
		return text
	while text and d.textlength(text + "…", font=font) > max_w:
		text = text[:-1]
	return text.rstrip() + "…"


def render(events):
	"""Return a 960x540 mode "L" image (0 = black, 255 = white): the agenda.

	The agenda is drawn in portrait (540x960) and rotated counter-clockwise by
	ROTATE degrees so the panel, mounted rotated, shows more rows.
	"""
	W, H = HEIGHT, WIDTH  # portrait canvas
	img = Image.new("L", (W, H), 255)
	d = ImageDraw.Draw(img)
	now = datetime.datetime.now().astimezone()
	today = now.date()
	margin = 20
	head_font = load_font(30)
	row_font = load_font(28)
	loc_font = load_font(20)
	small = load_font(18)
	head_h, row_h, loc_h, ev_gap = 44, 40, 26, 14
	bottom = H - 30

	# group per day
	days = {}
	for ev in events:
		for day in event_days(ev, today):
			days.setdefault(day, []).append(ev)

	if not days:
		d.text((W // 2, H // 2), "No upcoming events", font=head_font, fill=0, anchor="mm")

	y = margin
	hidden = 0
	for day in sorted(days):
		if y + head_h + row_h + loc_h > bottom:
			hidden += len(days[day])
			continue
		d.text((margin, y), day_label(day, today), font=head_font, fill=0)
		d.line((margin, y + head_h - 4, W - margin, y + head_h - 4), fill=0, width=2)
		y += head_h
		evs = days[day]
		for i, (start, end, title, all_day, location) in enumerate(evs):
			h = row_h + (loc_h if location else 0)
			if y + h > bottom:
				hidden += len(evs) - i
				break
			label = "All day" if all_day else "%s" % (start.strftime("%H:%M"))
			d.text((margin, y), label, font=row_font, fill=60)
			x = margin + 115
			max_w = W - margin - x
			title = fit(d, title, row_font, max_w)
			d.text((x, y), title, font=row_font, fill=0)
			# location in a lighter gray on its own line below the title
			if location:
				d.text((x, y + row_h - 6), fit(d, location, loc_font, max_w), font=loc_font, fill=90)
			y += h + ev_gap
		y += 8

	if hidden:
		d.text((margin, H - 12), "+%d more" % hidden, font=small, fill=0, anchor="ls")
	d.text((W - margin, H - 12), "updated " + now.strftime("%d/%m %H:%M"), font=small, fill=90, anchor="rs")
	return img.rotate(ROTATE, expand=True)


def pack_4bpp(img):
	"""Pack a mode "L" 960x540 image into the firmware's framebuffer format.

	Verified against components/epd_driver/src/epd_driver.c:
	  - epd_draw_pixel(): byte index = y * EPD_WIDTH / 2 + x / 2, row-major, no
	    row padding. Even x -> LOW nibble (color >> 4), odd x -> HIGH nibble
	    (color & 0xF0). So the LEFT pixel is the LOW nibble (not high!).
	    epd_copy_to_framebuffer() agrees (even index -> & 0x0F).
	  - Polarity: nibble 0x0 = black, 0xF = white (framebuffer is memset to
	    0xFF = white in display_ui.cpp; drawn with BLACK_ON_WHITE).
	So nibble = gray >> 4 and byte = left | (right << 4).
	"""
	if img.mode != "L":
		img = img.convert("L")
	if img.size != (WIDTH, HEIGHT):
		raise ValueError("image must be %dx%d" % (WIDTH, HEIGHT))
	px = img.tobytes()
	left = px[0::2]
	right = px[1::2]
	out = bytes(((l >> 4) & 0x0F) | (r & 0xF0) for l, r in zip(left, right))
	assert len(out) == IMAGE_SIZE
	return out


def unpack_4bpp(data):
	"""Inverse of pack_4bpp, returns a mode "L" image (nibble n -> n * 17)."""
	assert len(data) == IMAGE_SIZE
	px = bytearray(WIDTH * HEIGHT)
	px[0::2] = bytes((b & 0x0F) * 17 for b in data)
	px[1::2] = bytes((b >> 4) * 17 for b in data)
	return Image.frombytes("L", (WIDTH, HEIGHT), bytes(px))


def write_atomic(path, data):
	"""Write via a temp file + rename so readers never see a partial image."""
	tmp = path + ".tmp"
	with open(tmp, "wb") as f:
		f.write(data)
	os.replace(tmp, path)


def generate(out_dir, keep, png, cfg):
	os.makedirs(out_dir, exist_ok=True)
	session = AuthorizedSession(load_credentials(cfg))
	data = pack_4bpp(render(fetch_events(session, cfg["calendars"], cfg["days"])))
	name = PREFIX + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
	path = os.path.join(out_dir, name + SUFFIX)
	write_atomic(path, data)
	if png:
		unpack_4bpp(data).save(os.path.join(out_dir, name + ".png"))
	# prune: names sort chronologically
	old = sorted(glob.glob(os.path.join(out_dir, PREFIX + "*" + SUFFIX)))
	for p in old[:-keep]:
		os.remove(p)
		png_path = p[:-len(SUFFIX)] + ".png"
		if os.path.exists(png_path):
			os.remove(png_path)
	return path


def main():
	ap = argparse.ArgumentParser(description=__doc__)
	ap.add_argument("--out-dir", default="images", help="directory the images are written to")
	ap.add_argument("--interval", type=float, default=0, metavar="SEC",
		help="regenerate every SEC seconds (default: generate once and exit)")
	ap.add_argument("--keep", type=int, default=5, help="number of images to keep")
	ap.add_argument("--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"),
		help="JSON config (default: config.json next to this script)")
	ap.add_argument("--png", action="store_true", help="also write a preview PNG next to each image")
	ap.add_argument("--auth", action="store_true", help="authorize Google Calendar access (once) and exit")
	ap.add_argument("--auth-port", type=int, default=8090, help="local port for the OAuth redirect (default 8090)")
	ap.add_argument("--no-browser", action="store_true",
		help="with --auth: only print the consent URL (headless, use an SSH tunnel to --auth-port)")
	args = ap.parse_args()

	cfg = load_config(args.config)
	if args.auth:
		authorize(cfg, args.auth_port, not args.no_browser)
		return 0
	try:
		while True:
			try:
				print(generate(args.out_dir, max(1, args.keep), args.png, cfg), flush=True)
			except Exception as e:  # keep the previous image
				hint = "; run with --auth again" if isinstance(e, RefreshError) else ""
				print("generate failed: %s: %s%s" % (type(e).__name__, e, hint), file=sys.stderr, flush=True)
				if args.interval <= 0:
					return 1
			if args.interval <= 0:
				break
			time.sleep(args.interval)
	except KeyboardInterrupt:
		pass
	return 0


if __name__ == "__main__":
	sys.exit(main())
