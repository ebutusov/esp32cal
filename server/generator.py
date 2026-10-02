#!/usr/bin/env python3
"""Renders the 960x540 4bpp e-paper image and writes it to an output directory.

Each run writes a new file image_YYYYmmdd_HHMMSS.bin (atomically) and prunes
old ones. The web server (server.py) always serves the newest file.

Only third-party dependency: Pillow.
"""
import argparse
import datetime
import glob
import os
import sys
import time

from PIL import Image, ImageDraw, ImageFont

WIDTH = 960
HEIGHT = 540
IMAGE_SIZE = WIDTH * HEIGHT // 2  # 259200
PREFIX = "image_"
SUFFIX = ".bin"

FONT_CANDIDATES = [
	"/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
	"/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
	"/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
	"/Library/Fonts/Arial Bold.ttf",
	"C:/Windows/Fonts/arialbd.ttf",
]


def load_font(size):
	paths = FONT_CANDIDATES + glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)
	for p in paths:
		try:
			return ImageFont.truetype(p, size)
		except OSError:
			continue
	try:
		return ImageFont.load_default(size)  # Pillow >= 10.1
	except TypeError:
		return ImageFont.load_default()


def render():
	"""Return a 960x540 mode "L" image (0 = black, 255 = white). Replace freely."""
	img = Image.new("L", (WIDTH, HEIGHT), 255)
	d = ImageDraw.Draw(img)
	now = datetime.datetime.now()

	d.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), outline=0, width=4)

	big = load_font(150)
	mid = load_font(44)
	d.text((WIDTH // 2, 150), now.strftime("%H:%M"), font=big, fill=0, anchor="mm")
	d.text((WIDTH // 2, 270), now.strftime("%A, %d %B %Y"), font=mid, fill=40, anchor="mm")

	# test shapes (asymmetric so orientation/nibble order errors are visible)
	d.rectangle((40, 330, 160, 400), fill=0)
	d.ellipse((190, 330, 310, 400), outline=0, width=4)
	d.polygon([(340, 400), (400, 330), (460, 400)], fill=100)
	d.line((490, 400, 600, 330), fill=0, width=3)
	d.text((40, 300), "L", font=load_font(30), fill=0, anchor="ls")
	d.text((WIDTH - 40, 300), "R", font=load_font(30), fill=0, anchor="rs")

	# 16-step grayscale bar: step i -> 4bpp nibble i (0 = black ... 15 = white)
	x0, y0, w, h = 40, 430, 880, 70
	step = w // 16
	for i in range(16):
		g = i * 17
		d.rectangle((x0 + i * step, y0, x0 + (i + 1) * step - 1, y0 + h), fill=g)
	d.rectangle((x0, y0, x0 + 16 * step, y0 + h), outline=0, width=1)
	return img


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


def generate(out_dir, keep, png):
	os.makedirs(out_dir, exist_ok=True)
	data = pack_4bpp(render())
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
	ap.add_argument("--png", action="store_true", help="also write a preview PNG next to each image")
	args = ap.parse_args()

	try:
		while True:
			print(generate(args.out_dir, max(1, args.keep), args.png), flush=True)
			if args.interval <= 0:
				break
			time.sleep(args.interval)
	except KeyboardInterrupt:
		pass
	return 0


if __name__ == "__main__":
	sys.exit(main())
