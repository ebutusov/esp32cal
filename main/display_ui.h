#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

// Allocates the PSRAM framebuffer and initializes the e-paper driver.
// Must be called once before any other display_* function.
void display_init();

// Pushes the framebuffer to the display (panel must be powered on)
void display_update();

// Raw 4bpp framebuffer (EPD_WIDTH*EPD_HEIGHT/2 bytes), for downloading an image straight into it
uint8_t *display_framebuffer();
size_t display_framebuffer_size();

// Fills the framebuffer with white
void display_clear_framebuffer();

// Draws error text into the framebuffer (call display_update() afterwards)
void display_draw_error(const std::string &txt);

void display_show_maintenance_info(const std::string &ssid, const std::string &pass, const std::string &ip);
