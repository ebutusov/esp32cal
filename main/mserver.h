#pragma once

// Starts the maintenance-mode HTTP server. esp_http_server runs its own
// FreeRTOS task internally, so unlike the original Arduino WebServer there
// is no loopHandleClient()-style pump to call afterwards.
void setupServer();
