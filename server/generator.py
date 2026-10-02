#!/usr/bin/env python3
"""Renders a Google Calendar agenda as a 960x540 4bpp e-paper image.

The calendar is downloaded from a secret ICS URL (config.json, key "ics_url").
Each run writes a new file image_YYYYmmdd_HHMMSS.bin (atomically) and prunes
old ones. The web server (server.py) always serves the newest file. If the
calendar cannot be fetched, nothing is written and the previous image stays.

Third-party dependencies: Pillow, icalendar, recurring-ical-events.
"""
import argparse
import datetime
import glob
import json
import os
import subprocess
import sys
import time
import urllib.request

import icalendar
import recurring_ical_events
from PIL import Image, ImageDraw, ImageFont

WIDTH = 960
HEIGHT = 540
IMAGE_SIZE = WIDTH * HEIGHT // 2  # 259200
ROTATE = 90  # portrait canvas rotated counter-clockwise (90 or 270; 270 = the other mounting direction)
PREFIX = "image_"
SUFFIX = ".bin"

FONT_CANDIDATES = [
	"/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
	"/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
	"/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
	"/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
	"/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
	"/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
	"/Library/Fonts/Arial Bold.ttf",
	"C:/Windows/Fonts/arialbd.ttf",
]

# Text that must render without "missing glyph" boxes: accents, Latin Extended
# (Polish, Czech...), Cyrillic, Greek and the punctuation the layout uses.
COVERAGE_TEXT = "ąćęłńóśźżĄŁŻěščřžýáíéůúďťňüöäßñçéèêàøåÆ–—…’№Жщюя"

_font_paths = None
_notdef = {}


def _missing_glyph_mask(font):
	"""Bitmap the font draws for a codepoint it does not have (its .notdef box)."""
	if id(font) not in _notdef:
		_notdef[id(font)] = bytes(font.getmask("􏿿"))
	return _notdef[id(font)]


def has_glyphs(font, text=COVERAGE_TEXT):
	missing = _missing_glyph_mask(font)
	return all(bytes(font.getmask(ch)) != missing for ch in text)


def find_font_paths():
	"""Candidate TTFs, best first: known bold fonts, fontconfig's pick, any Sans/Bold TTF."""
	global _font_paths
	if _font_paths is None:
		paths = list(FONT_CANDIDATES)
		try:
			out = subprocess.run(["fc-match", "-f", "%{file}", "sans:bold"],
				capture_output=True, text=True, timeout=5).stdout.strip()
			if out:
				paths.append(out)
		except (OSError, subprocess.SubprocessError):
			pass
		found = glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)
		found.sort(key=lambda p: ("bold" not in p.lower(), "sans" not in p.lower(), p))
		_font_paths = paths + found
	return _font_paths


def load_font(size):
	fallback = None
	for p in find_font_paths():
		try:
			font = ImageFont.truetype(p, size)
		except OSError:
			continue
		if has_glyphs(font):
			return font
		fallback = fallback or font  # exists but lacks some glyphs
	if fallback:
		print("warning: no installed font covers all of the expected characters "
			"(install fonts-dejavu-core or fonts-noto)", file=sys.stderr)
		return fallback
	try:
		return ImageFont.load_default(size)  # Pillow >= 10.1, ASCII/Latin-1 only
	except TypeError:
		return ImageFont.load_default()


def load_config(path):
	with open(path, encoding="utf-8") as f:
		cfg = json.load(f)
	if not cfg.get("ics_url"):
		raise ValueError('%s: "ics_url" is required' % path)
	cfg.setdefault("days", 14)
	return cfg


def fetch_events(url, days):
	"""Return [(start, end, summary, all_day, location)] for today and the next days, sorted.

	Starts at today's local midnight, so events of the current day (even ones
	already started) are kept and earlier days are dropped.
	"""
	with urllib.request.urlopen(url, timeout=20) as r:
		cal = icalendar.Calendar.from_ical(r.read())
	today = datetime.datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
	events = []
	for ev in recurring_ical_events.of(cal).between(today, today + datetime.timedelta(days=days)):
		start = ev.get("DTSTART").dt
		end = ev.get("DTEND").dt if ev.get("DTEND") else start
		all_day = not isinstance(start, datetime.datetime)
		if not all_day:
			start = start.astimezone()
			end = end.astimezone()
		location = " ".join(str(ev.get("LOCATION", "")).split())
		events.append((start, end, str(ev.get("SUMMARY", "(no title)")), all_day, location))
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
		return "Today"
	if d == today + datetime.timedelta(days=1):
		return "Tomorrow"
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
	margin = 30
	head_font = load_font(30)
	row_font = load_font(24)
	loc_font = load_font(20)
	small = load_font(18)
	head_h, row_h, loc_h = 44, 34, 26
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
			label = "All day" if all_day else "%s–%s" % (start.strftime("%H:%M"), end.strftime("%H:%M"))
			d.text((margin, y), label, font=row_font, fill=60)
			x = margin + 160
			max_w = W - margin - x
			title = fit(d, title, row_font, max_w)
			d.text((x, y), title, font=row_font, fill=0)
			# location in a lighter gray on its own line below the title
			if location:
				d.text((x, y + row_h - 4), fit(d, location, loc_font, max_w), font=loc_font, fill=90)
			y += h
		y += 8

	if hidden:
		d.text((margin, H - 12), "+%d more" % hidden, font=small, fill=0, anchor="ls")
	d.text((W - margin, H - 12), "updated " + now.strftime("%H:%M"), font=small, fill=90, anchor="rs")
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
	data = pack_4bpp(render(fetch_events(cfg["ics_url"], cfg["days"])))
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
		help="JSON config with the secret calendar URL (default: config.json next to this script)")
	ap.add_argument("--png", action="store_true", help="also write a preview PNG next to each image")
	args = ap.parse_args()

	cfg = load_config(args.config)
	try:
		while True:
			try:
				print(generate(args.out_dir, max(1, args.keep), args.png, cfg), flush=True)
			except Exception as e:  # keep the previous image; never print the URL
				print("generate failed: %s: %s" % (type(e).__name__, str(e).replace(cfg["ics_url"], "<url>")),
					file=sys.stderr, flush=True)
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
