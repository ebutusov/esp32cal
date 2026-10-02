#include "display_ui.h"

#include <cstring>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_system.h"

#include "epd_driver.h"

#include "fonts/opensans12b.h"

static const char *TAG = "display";

static uint8_t *g_framebuffer = NULL;
static GFXfont *g_current_font = (GFXfont *)&OpenSans12B;

static void setFont(const GFXfont &font) {
	g_current_font = (GFXfont *)&font;
}

static void textAt(uint16_t x, uint16_t y, const char *text) {
	int32_t cur_x = x, cur_y = y;
	writeln(g_current_font, text, &cur_x, &cur_y, g_framebuffer);
}

static void textAt(uint16_t x, uint16_t y, const std::string &text) {
	textAt(x, y, text.c_str());
}

void display_draw_error(const std::string &txt) {
	setFont(OpenSans12B);
	textAt(150, 200, txt);
}

void display_show_maintenance_info(const std::string &ssid, const std::string &pass, const std::string &ip) {
	setFont(OpenSans12B);
	textAt(60, 100, "*** MAINTENANCE MODE *** ");
	textAt(20, 120, "SSID: " + ssid + " PASS: " + pass);
	textAt(105, 140, "IP:" + ip);
}

void display_init() {
	g_framebuffer = (uint8_t *)heap_caps_calloc(1, EPD_WIDTH * EPD_HEIGHT / 2, MALLOC_CAP_SPIRAM);
	if (!g_framebuffer) {
		ESP_LOGE(TAG, "framebuffer allocation failed !!!");
		while (1) {
			vTaskDelay(pdMS_TO_TICKS(1000));
		}
	}
	display_clear_framebuffer();

	// keep the delays to avoid brownout
	epd_init();
	vTaskDelay(pdMS_TO_TICKS(100));
}

uint8_t *display_framebuffer() {
	return g_framebuffer;
}

size_t display_framebuffer_size() {
	return EPD_WIDTH * EPD_HEIGHT / 2;
}

void display_clear_framebuffer() {
	memset(g_framebuffer, 0xFF, EPD_WIDTH * EPD_HEIGHT / 2);
}

void display_update() {
	epd_draw_grayscale_image(epd_full_screen(), g_framebuffer);
}
