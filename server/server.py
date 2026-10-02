#!/usr/bin/env python3
"""Serves the newest image from a directory to the ESP32 client.

The images are produced by generator.py (image_*.bin, 259200 bytes each). The
newest file is looked up on every request, so a regenerated image is picked up
immediately. Standard library only.
"""
import argparse
import glob
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

IMAGE_SIZE = 960 * 540 // 2  # 259200


def latest_image(directory):
	"""Path of the newest image_*.bin (by modification time), or None."""
	files = glob.glob(os.path.join(directory, "image_*.bin"))
	if not files:
		return None
	return max(files, key=os.path.getmtime)


class Handler(BaseHTTPRequestHandler):
	directory = "images"

	def do_GET(self):
		if self.path.split("?")[0] not in ("/", "/image"):
			self.send_error(404)
			return
		# the file may be pruned between lookup and open; retry once
		for _ in range(2):
			path = latest_image(self.directory)
			if path is None:
				self.send_error(503, "no image generated yet")
				return
			try:
				with open(path, "rb") as f:
					body = f.read()
				break
			except OSError:
				body = None
		if body is None or len(body) != IMAGE_SIZE:
			self.send_error(500, "bad image")
			return
		self.send_response(200)
		self.send_header("Content-Type", "application/octet-stream")
		self.send_header("Content-Length", str(len(body)))
		self.end_headers()
		self.wfile.write(body)


def main():
	ap = argparse.ArgumentParser(description=__doc__)
	ap.add_argument("--host", default="0.0.0.0")
	ap.add_argument("--port", type=int, default=8080)
	ap.add_argument("--dir", default="images", help="directory written by generator.py")
	args = ap.parse_args()

	Handler.directory = args.dir
	srv = ThreadingHTTPServer((args.host, args.port), Handler)
	print("serving newest image from %s at http://%s:%d/image" % (args.dir, args.host, args.port))
	try:
		srv.serve_forever()
	except KeyboardInterrupt:
		pass
	return 0


if __name__ == "__main__":
	sys.exit(main())
