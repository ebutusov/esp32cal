cmake_minimum_required(VERSION 3.16)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(cal32_epd47)

# No FLASH_IN_PROJECT: `idf.py flash` leaves the (large, config-holding) SPIFFS alone; use `idf.py storage-flash`
spiffs_create_partition_image(storage spiffs_image)
