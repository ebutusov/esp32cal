#!/usr/bin/env python3
"""Serves a 960x540 4bpp e-paper image for the ESP32 client.

Only third-party dependency: Pillow.
"""
import argparse
import datetime
import glob
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image, ImageDraw, ImageFont

WIDTH = 960
HEIGHT = 540
IMAGE_SIZE = WIDTH * HEIGHT // 2  # 259200

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


class Handler(BaseHTTPRequestHandler):
	def do_GET(self):
		if self.path.split("?")[0] not in ("/", "/image"):
			self.send_error(404)
			return
		body = pack_4bpp(render())
		self.send_response(200)
		self.send_header("Content-Type", "application/octet-stream")
		self.send_header("Content-Length", str(len(body)))
		self.end_headers()
		self.wfile.write(body)


def main():
	ap = argparse.ArgumentParser(description=__doc__)
	ap.add_argument("--host", default="0.0.0.0")
	ap.add_argument("--port", type=int, default=8080)
	ap.add_argument("--dump", metavar="out.png", help="write round-tripped PNG and exit")
	ap.add_argument("--dump-raw", metavar="out.bin", help="write raw 4bpp data and exit")
	args = ap.parse_args()

	if args.dump or args.dump_raw:
		data = pack_4bpp(render())
		if args.dump_raw:
			with open(args.dump_raw, "wb") as f:
				f.write(data)
		if args.dump:
			unpack_4bpp(data).save(args.dump)
		print("%d bytes" % len(data))
		return 0

	srv = ThreadingHTTPServer((args.host, args.port), Handler)
	print("serving http://%s:%d/image" % (args.host, args.port))
	try:
		srv.serve_forever()
	except KeyboardInterrupt:
		pass
	return 0


if __name__ == "__main__":
	sys.exit(main())
