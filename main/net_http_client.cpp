#include "net_http_client.h"

#include "esp_http_client.h"
#include "esp_log.h"

static const char *TAG = "net_http";

int http_get_to_buffer(const char *url, uint8_t *dst, size_t expected, int timeout_ms) {
	esp_http_client_config_t config = {};
	config.url = url;
	config.timeout_ms = timeout_ms;
	esp_http_client_handle_t client = esp_http_client_init(&config);
	if (!client) {
		ESP_LOGE(TAG, "http client init failed");
		return 0;
	}

	ESP_LOGI(TAG, "Getting url: %s", url);

	esp_err_t err = esp_http_client_open(client, 0);
	if (err != ESP_OK) {
		ESP_LOGE(TAG, "Failed to open connection: %s", esp_err_to_name(err));
		esp_http_client_cleanup(client);
		return 0;
	}

	int64_t clen = esp_http_client_fetch_headers(client);
	int status = esp_http_client_get_status_code(client);
	ESP_LOGI(TAG, "HTTP code: %d, content-length: %lld", status, (long long)clen);

	int ok = 0;
	if (status == 200 && clen == (int64_t)expected) {
		size_t got = 0;
		while (got < expected) {
			int r = esp_http_client_read(client, (char *)dst + got, expected - got);
			if (r <= 0) {
				break;
			}
			got += r;
		}
		ESP_LOGI(TAG, "Received %u of %u bytes", (unsigned)got, (unsigned)expected);
		ok = (got == expected);
	} else {
		ESP_LOGE(TAG, "Unexpected response (status %d, length %lld, expected %u)", status, (long long)clen, (unsigned)expected);
	}

	esp_http_client_close(client);
	esp_http_client_cleanup(client);
	return ok;
}
