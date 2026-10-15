#pragma once

#include <cstddef>
#include <cstdint>

using esp_err_t = int;
using nvs_handle_t = uint32_t;
enum nvs_open_mode_t { NVS_READONLY, NVS_READWRITE };
constexpr esp_err_t ESP_OK = 0;
constexpr esp_err_t ESP_ERR_NVS_NOT_FOUND = 0x1102;
constexpr esp_err_t ESP_ERR_NVS_FAIL = 0x11ff;

extern "C" {
esp_err_t nvs_open(const char* name, nvs_open_mode_t mode,
                   nvs_handle_t* handle);
esp_err_t nvs_get_blob(nvs_handle_t handle, const char* key, void* output,
                       size_t* length);
esp_err_t nvs_set_blob(nvs_handle_t handle, const char* key,
                       const void* value, size_t length);
esp_err_t nvs_commit(nvs_handle_t handle);
void nvs_close(nvs_handle_t handle);
}
