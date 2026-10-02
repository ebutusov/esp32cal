#pragma once

#include <string>

// One-time init: nvs_flash_init + esp_netif_init + esp_event_loop_create_default
// + esp_wifi_init. Must be called once before wifi_connect_sta()/wifi_start_softap().
void wifi_stack_init();

// Connects in STA mode, retrying up to `attempts` times with `timeout_ms`
// budget each - mirrors the original firmware's connectWiFi(). Returns
// true if connected by the time it returns.
bool wifi_connect_sta(const std::string &ssid, const std::string &pass,
                       const std::string &hostname, int attempts = 3, int timeout_ms = 10000);

// Disconnects and turns the WiFi radio off (saves battery before deep sleep).
void wifi_stop();

// Starts a SoftAP with the given SSID/password and returns its IP address
// as a dotted-decimal string.
std::string wifi_start_softap(const std::string &ap_ssid, const std::string &ap_pass);
