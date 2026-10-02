#include <cstdio>
#include <string>

#include <ArduinoJson.h>

#include "driver/gpio.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_sleep.h"
#include "esp_spiffs.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mdns.h"

#include "display_ui.h"
#include "epd_driver.h"
#include "mserver.h"
#include "net_wifi.h"
#include "net_http_client.h"

static const char *TAG = "weather32";

#define XPIN_MAINTENANCE GPIO_NUM_21

static uint64_t CONF_SLEEP_TIME = 20ULL * 60ULL * 1000000ULL;

RTC_DATA_ATTR static int g_boot_counter = 0;

static bool mount_spiffs()
{
	esp_vfs_spiffs_conf_t conf = {
			.base_path = "/spiffs",
			.partition_label = "storage",
			.max_files = 5,
			.format_if_mount_failed = false,
	};
	esp_err_t ret = esp_vfs_spiffs_register(&conf);
	if (ret != ESP_OK)
	{
		ESP_LOGE(TAG, "Failed to initialize FS! (%s)", esp_err_to_name(ret));
		return false;
	}
	return true;
}

static void goToSleep()
{
	wifi_stop();
	vTaskDelay(pdMS_TO_TICKS(50));
	epd_poweroff_all();
	vTaskDelay(pdMS_TO_TICKS(50));
	ESP_LOGI(TAG, "Going to sleep...");
	esp_sleep_enable_timer_wakeup(CONF_SLEEP_TIME);
	esp_deep_sleep_start();
}

// Downloads the image into the framebuffer, shows it (or an error) on the panel.
static void updateImage(const std::string &url)
{
	bool ok = false;
	if (url.empty())
	{
		ESP_LOGE(TAG, "No url configured");
	}
	else
	{
		ok = http_get_to_buffer(url.c_str(), display_framebuffer(), display_framebuffer_size(), 20000) != 0;
	}

	wifi_stop(); // save battery
	vTaskDelay(pdMS_TO_TICKS(50));

	if (!ok)
	{
		// don't leave a half-written image in the framebuffer
		display_clear_framebuffer();
		display_draw_error(url.empty() ? "No server url configured" : "Failed to download image :(");
	}

	epd_poweron();
	vTaskDelay(pdMS_TO_TICKS(50));
	epd_clear();
	display_update();
}

extern "C" void app_main(void)
{
	g_boot_counter++;
	std::string ESP_HOST_NAME = "esp-test47";

	ESP_LOGI(TAG, "Image station starting...");

	display_init();
	ESP_LOGI(TAG, "Display setup done.");

	gpio_config_t maint_pin_cfg = {
			.pin_bit_mask = 1ULL << XPIN_MAINTENANCE,
			.mode = GPIO_MODE_INPUT,
			.pull_up_en = GPIO_PULLUP_ENABLE,
			.pull_down_en = GPIO_PULLDOWN_DISABLE,
			.intr_type = GPIO_INTR_DISABLE,
	};
	gpio_config(&maint_pin_cfg);

	int bt21 = gpio_get_level(XPIN_MAINTENANCE);
	ESP_LOGI(TAG, "*** GPIO 21 STATE is: %d", bt21);

	if (gpio_get_level(XPIN_MAINTENANCE) == 0)
	{
		ESP_LOGI(TAG, "*** ENTERING MAINTENANCE MODE ***");

		wifi_stack_init();

		if (mdns_init() != ESP_OK)
		{
			ESP_LOGE(TAG, "Error setting up MDNS responder!");
		}
		else
		{
			mdns_hostname_set("esp32");
			ESP_LOGI(TAG, "mDNS responder started");
		}

		const std::string AP_SSID = "WEATHER32";
		const std::string AP_PASS = "weather123456789";

		ESP_LOGI(TAG, "Starting AP, SSID: %s, PASS: %s", AP_SSID.c_str(), AP_PASS.c_str());
		std::string ap_ip = wifi_start_softap(AP_SSID, AP_PASS);

		if (!mount_spiffs())
		{
			ESP_LOGE(TAG, "Failed to initialize FS!");
		}

		ESP_LOGI(TAG, "Starting http server...");
		setupServer();

		// same panel power sequence as updateImage(); without it nothing is drawn
		epd_poweron();
		vTaskDelay(pdMS_TO_TICKS(50));
		epd_clear();
		display_show_maintenance_info(AP_SSID, AP_PASS, ap_ip);
		display_update();
		epd_poweroff(); // e-paper keeps the image without power
		return;					// httpd runs its own task - nothing left for app_main to do
	}

	if (!mount_spiffs())
	{
		goToSleep(); // no return
	}

	FILE *file = fopen("/spiffs/config.json", "r");
	if (!file)
	{
		ESP_LOGE(TAG, "Failed to open file for reading");
		goToSleep(); // no return
	}

	std::string CONF_WIFI_SSID;
	std::string CONF_WIFI_PASSWORD;
	std::string CONF_IMAGE_URL;

	char buf[1024];
	size_t n = fread(buf, 1, sizeof(buf) - 1, file);
	buf[n] = '\0';
	fclose(file);

	StaticJsonDocument<1024> doc;
	DeserializationError error = deserializeJson(doc, buf, n);
	if (error)
	{
		ESP_LOGW(TAG, "Failed to read file, using default configuration");
	}
	else
	{
		CONF_WIFI_SSID = doc["ssid"].isNull() ? "FAIL" : doc["ssid"].as<const char *>();
		CONF_WIFI_PASSWORD = doc["password"].isNull() ? "FAIL" : doc["password"].as<const char *>();
		CONF_IMAGE_URL = doc["url"].isNull() ? "" : doc["url"].as<const char *>();
		int sleep_min = doc["sleep"].isNull() ? 15 : doc["sleep"].as<int>();
		CONF_SLEEP_TIME = (uint64_t)sleep_min * 60ULL * 1000000ULL;
	}

	ESP_LOGI(TAG, "Configuration:");
	ESP_LOGI(TAG, "Sleep time: %llu", (unsigned long long)CONF_SLEEP_TIME);
	ESP_LOGI(TAG, "PSRAM size: %u", (unsigned)heap_caps_get_total_size(MALLOC_CAP_SPIRAM));

	wifi_stack_init();

	ESP_LOGI(TAG, "Hostname set to: %s", ESP_HOST_NAME.c_str());
	bool connected = wifi_connect_sta(CONF_WIFI_SSID, CONF_WIFI_PASSWORD, ESP_HOST_NAME);

	if (!connected)
	{
		ESP_LOGE(TAG, "WIFI connection failed!");
		display_draw_error("WIFI connection failed!");
		epd_poweron();
		vTaskDelay(pdMS_TO_TICKS(50));
		epd_clear();
		display_update();

		// there was a sw reset last time, let's just sleep to avoid a reboot loop
		if (esp_reset_reason() == ESP_RST_SW)
			goToSleep(); // no return

		ESP_LOGI(TAG, "Resetting ESP...");
		esp_restart(); // no return, reason will be ESP_RST_SW
	}

	ESP_LOGI(TAG, "WiFi connected");

	ESP_LOGI(TAG, "Downloading image...");
	updateImage(CONF_IMAGE_URL);
	vTaskDelay(pdMS_TO_TICKS(50));
	// sleep now, sleep...
	goToSleep();
}
