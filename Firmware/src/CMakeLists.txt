#  显式列出当前固件源文件，确保 PlatformIO 的 Arduino/ESP-IDF 构建一致 / List active firmware sources explicitly for consistent PlatformIO Arduino/ESP-IDF builds
set(OMIPET_SOURCES
    "main.cpp"
    "aht20_sensor.cpp"
    "battery_monitor.cpp"
    "buzzer.cpp"
    "device_protocol_envelope.cpp"
    "device_protocol_experiment.cpp"
    "device_protocol_session.cpp"
    "ics43434_mic.cpp"
    "led_controller.cpp"
    "monitor_light_profiles.cpp"
    "multinet_command_recognizer.cpp"
    "omi_pet_ui.cpp"
    "pcm_audio_frame_buffer.cpp"
    "time_service.cpp"
    "voice_controller.cpp"
    "wifi_manager.cpp"
    "../lib/NV3007_Display/NV3007_Display.cpp"
)

if(OMIPET_WIFI_PAIRING)
    list(APPEND OMIPET_SOURCES "wireless_pairing.cpp" "pairing_tls_identity.cpp"
        "pairing_tls_store.cpp" "pairing_nvs_store.cpp")
endif()
if(OMIPET_WIFI_CONTROL)
    if(NOT OMIPET_WIFI_PAIRING)
        message(FATAL_ERROR "Wireless control requires authenticated pairing")
    endif()
    list(APPEND OMIPET_SOURCES "wireless_control.cpp")
endif()

idf_component_register(
    SRCS ${OMIPET_SOURCES}
    INCLUDE_DIRS "../include" "../lib/NV3007_Display"
    REQUIRES esp-sr json esp_http_server mbedtls nvs_flash
)
if(OMIPET_WIFI_PAIRING)
    target_compile_definitions(${COMPONENT_LIB} PRIVATE OMIPET_WIFI_PAIRING=1)
endif()
if(OMIPET_WIFI_CONTROL)
    target_compile_definitions(${COMPONENT_LIB} PRIVATE OMIPET_WIFI_CONTROL=1)
endif()
