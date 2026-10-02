#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

// GET url and read the body directly into dst. Succeeds (returns 1) only if the
// status is 200, content-length == expected and exactly `expected` bytes were
// received; otherwise returns 0 (dst may be partially written).
int http_get_to_buffer(const char *url, uint8_t *dst, size_t expected, int timeout_ms = 20000);
