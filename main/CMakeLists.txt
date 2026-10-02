idf_component_register(
    SRC_DIRS "."
    INCLUDE_DIRS "." "fonts"
    REQUIRES epd_driver json
             esp_wifi esp_netif esp_event nvs_flash
             esp_http_client esp_http_server spiffs mdns
)
