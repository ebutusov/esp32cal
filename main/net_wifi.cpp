#include "net_wifi.h"

#include <cstring>

#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "esp_wifi_default.h"
#include "nvs_flash.h"

static const char *TAG = "net_wifi";

#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT BIT1

static EventGroupHandle_t s_wifi_event_group = NULL;

static void wifi_event_handler(void *arg, esp_event_base_t event_base, int32_t event_id, void *event_data)
{
  if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED)
  {
    if (s_wifi_event_group)
      xEventGroupSetBits(s_wifi_event_group, WIFI_FAIL_BIT);
  }
  else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP)
  {
    if (s_wifi_event_group)
    	xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
  }
}

void wifi_stack_init()
{
  esp_err_t err = nvs_flash_init();
  if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND)
  {
    ESP_ERROR_CHECK(nvs_flash_erase());
    err = nvs_flash_init();
  }
  ESP_ERROR_CHECK(err);

  ESP_ERROR_CHECK(esp_netif_init());
  ESP_ERROR_CHECK(esp_event_loop_create_default());

  wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
  ESP_ERROR_CHECK(esp_wifi_init(&cfg));

  s_wifi_event_group = xEventGroupCreate();
  ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, NULL));
  ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL, NULL));
}

bool wifi_connect_sta(const std::string &ssid, const std::string &pass,
                      const std::string &hostname, int attempts, int timeout_ms)
{
  esp_netif_t *sta_netif = esp_netif_create_default_wifi_sta();
  if (!hostname.empty())
  {
    esp_netif_set_hostname(sta_netif, hostname.c_str());
  }

  wifi_config_t wifi_config = {};
  strncpy((char *)wifi_config.sta.ssid, ssid.c_str(), sizeof(wifi_config.sta.ssid) - 1);
  strncpy((char *)wifi_config.sta.password, pass.c_str(), sizeof(wifi_config.sta.password) - 1);

  ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
  ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
  ESP_ERROR_CHECK(esp_wifi_start());
  // Only valid after esp_wifi_start(); units are 0.25 dBm (34 = 8.5 dBm)
  ESP_ERROR_CHECK(esp_wifi_set_max_tx_power(34));
  ESP_LOGI(TAG, "Connecting to: %s", ssid.c_str());

  bool connected = false;
  for (int attempt = 0; attempt < attempts && !connected; attempt++)
  {
    xEventGroupClearBits(s_wifi_event_group, WIFI_CONNECTED_BIT | WIFI_FAIL_BIT);
    esp_wifi_connect();
    EventBits_t bits = xEventGroupWaitBits(s_wifi_event_group, WIFI_CONNECTED_BIT | WIFI_FAIL_BIT,
                                           pdTRUE, pdFALSE, pdMS_TO_TICKS(timeout_ms));
    if (bits & WIFI_CONNECTED_BIT)
    {
      connected = true;
    }
    else
    {
      ESP_LOGW(TAG, "WiFi connection timeout, attempt: %d", attempt + 1);
    }
  }
  return connected;
}

void wifi_stop()
{
  esp_wifi_disconnect();
  esp_wifi_stop();
  ESP_LOGI(TAG, "WiFi switched Off");
}

std::string wifi_start_softap(const std::string &ap_ssid, const std::string &ap_pass)
{
  esp_netif_t *ap_netif = esp_netif_create_default_wifi_ap();

  wifi_config_t wifi_config = {};
  size_t ssid_len = ap_ssid.copy((char *)wifi_config.ap.ssid, sizeof(wifi_config.ap.ssid));
  wifi_config.ap.ssid_len = ssid_len;
  strncpy((char *)wifi_config.ap.password, ap_pass.c_str(), sizeof(wifi_config.ap.password) - 1);
  wifi_config.ap.channel = 1;
  wifi_config.ap.max_connection = 4;
  wifi_config.ap.authmode = ap_pass.empty() ? WIFI_AUTH_OPEN : WIFI_AUTH_WPA2_PSK;

  ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
  ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &wifi_config));
  ESP_ERROR_CHECK(esp_wifi_start());

  ESP_LOGI(TAG, "Starting AP, SSID: %s, PASS: %s", ap_ssid.c_str(), ap_pass.c_str());

  esp_netif_ip_info_t ip_info;
  esp_netif_get_ip_info(ap_netif, &ip_info);
  char ip_str[16];
  esp_ip4addr_ntoa(&ip_info.ip, ip_str, sizeof(ip_str));
  return std::string(ip_str);
}
