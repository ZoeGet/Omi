#include "multinet_command_recognizer.h"

#include "generated_multinet_commands.h"

extern "C" {
#include "esp_afe_config.h"
#include "esp_afe_sr_iface.h"
#include "esp_afe_sr_models.h"
#include "esp_mn_iface.h"
#include "esp_mn_models.h"
#include "esp_mn_speech_commands.h"
#include "model_path.h"
}

namespace OmiPetAudio {

namespace {

//  ESP-SR 模型分区和当前使用的中文 MultiNet 模型 / ESP-SR model partition and the active Chinese MultiNet model
constexpr char kModelPartitionLabel[] = "model";  //  ESP-SR 模型分区标签 / ESP-SR model-partition label
constexpr char kMultiNetModelName[] = "mn6_cn";  //  当前使用的中文 MultiNet 模型名 / Active Chinese MultiNet model name


}

bool MultiNetCommandRecognizer::begin(uint32_t sampleRateHz,
                                      size_t inputFrameSamples) {
  ready_ = false;
  feedSamplesSinceFetch_ = 0;
  feedFramesPerFetch_ = 0;
  if (sampleRateHz != 16000U || inputFrameSamples == 0U) {
    return false;
  }

  srmodel_list_t* models = esp_srmodel_init(kModelPartitionLabel);
  if (models == nullptr) {
    Serial.println("[ASR] model partition unavailable");
    return false;
  }
  modelList_ = models;
  if (esp_srmodel_exists(models, const_cast<char*>(kMultiNetModelName)) < 0) {
    Serial.printf("[ASR] model missing name=%s\n", kMultiNetModelName);
    return false;
  }

  //  关闭 WakeNet，只保留 AFE 的语音活动检测和 MultiNet 输入链 / Disable WakeNet and keep only AFE speech activity processing plus MultiNet input
  afe_config_t afeConfig = {};
  afeConfig.aec_init = false;
  afeConfig.se_init = true;
  afeConfig.vad_init = true;
  afeConfig.wakenet_init = false;
  afeConfig.vad_mode = VAD_MODE_3;
  afeConfig.afe_mode = SR_MODE_LOW_COST;
  afeConfig.afe_perferred_core = 0;  //  AFE 运行的 CPU 核 / CPU core preferred by AFE
  afeConfig.afe_perferred_priority = 5;  //  AFE 任务优先级 / AFE task priority
  afeConfig.afe_ringbuf_size = 50;  //  AFE 环形缓冲区容量 / AFE ring-buffer capacity
  afeConfig.memory_alloc_mode = AFE_MEMORY_ALLOC_MORE_PSRAM;
  afeConfig.agc_mode = AFE_MN_PEAK_AGC_MODE_2;
  afeConfig.pcm_config.total_ch_num = 1;  //  AFE 输入总声道数 / Total AFE input channel count
  afeConfig.pcm_config.mic_num = 1;  //  麦克风声道数 / Microphone channel count
  afeConfig.pcm_config.ref_num = 0;  //  参考声道数 / Reference channel count
  afeConfig.pcm_config.sample_rate = static_cast<int>(sampleRateHz);
  afe_config_t* afeConfigPointer = &afeConfig;

  const esp_afe_sr_iface_t* afe = &ESP_AFE_SR_HANDLE;
  if (afe->create_from_config == nullptr || afe->feed == nullptr ||
      afe->fetch == nullptr) {
    Serial.println("[ASR] AFE interface incomplete");
    return false;
  }
  esp_afe_sr_data_t* afeData = afe->create_from_config(afeConfigPointer);
  if (afeData == nullptr) {
    Serial.println("[ASR] AFE initialization failed");
    return false;
  }
  afeHandle_ = const_cast<esp_afe_sr_iface_t*>(afe);
  afeData_ = afeData;
  feedFrameSamples_ = static_cast<size_t>(afe->get_feed_chunksize(afeData));
  fetchFrameSamples_ = static_cast<size_t>(afe->get_fetch_chunksize(afeData));

  char modelName[] = "mn6_cn";
  esp_mn_iface_t* multiNet = esp_mn_handle_from_name(modelName);
  if (multiNet == nullptr || multiNet->create == nullptr ||
      multiNet->detect == nullptr || multiNet->get_results == nullptr) {
    Serial.println("[ASR] MultiNet interface unavailable");
    return false;
  }
  model_iface_data_t* multiNetData = multiNet->create(modelName, 5000);
  if (multiNetData == nullptr) {
    Serial.println("[ASR] MultiNet model initialization failed");
    return false;
  }
  multiNet_ = multiNet;
  multiNetData_ = multiNetData;
  modelFrameSamples_ =
      static_cast<size_t>(multiNet->get_samp_chunksize(multiNetData));

  if (feedFrameSamples_ != inputFrameSamples ||
      fetchFrameSamples_ != modelFrameSamples_ ||
      multiNet->get_samp_rate(multiNetData) !=
          static_cast<int>(sampleRateHz)) {
    Serial.printf(
        "[ASR] frame mismatch input=%u afe_feed=%u afe_fetch=%u mn=%u rate=%d\n",
        static_cast<unsigned>(inputFrameSamples),
        static_cast<unsigned>(feedFrameSamples_),
        static_cast<unsigned>(fetchFrameSamples_),
        static_cast<unsigned>(modelFrameSamples_),
        multiNet->get_samp_rate(multiNetData));
    return false;
  }

  feedFramesPerFetch_ =
      (fetchFrameSamples_ + feedFrameSamples_ - 1U) / feedFrameSamples_;
  if (feedFramesPerFetch_ == 0U) {
    Serial.println("[ASR] invalid AFE feed/fetch frame ratio");
    return false;
  }

  if (multiNet->set_speech_commands != nullptr) {
    if (esp_mn_commands_alloc() != ESP_OK) {
      Serial.println("[ASR] command list initialization failed");
      return false;
    }
    for (const GeneratedCommandPhrase& phrase : kGeneratedCommandPhrases) {
      if (esp_mn_commands_add(phrase.commandId,
                              const_cast<char*>(phrase.phonemes)) != ESP_OK) {
        Serial.printf("[ASR] command phrase rejected: %s\n", phrase.phonemes);
        return false;
      }
    }
    esp_mn_error_t* commandErrors =
        esp_mn_commands_update(multiNet, multiNetData);
    if (commandErrors != nullptr && commandErrors->num > 0) {
      Serial.printf("[ASR] command phrase parse errors=%d\n",
                    static_cast<int>(commandErrors->num));
      return false;
    }
  } else {
    Serial.println("[ASR] model uses offline command list");
  }

  ready_ = true;
  Serial.printf(
      "[ASR] ready model=%s rate=%lu feed=%u fetch=%u feed_ratio=%.2f feed_ceil=%u phrases=%u\n",
                kMultiNetModelName, static_cast<unsigned long>(sampleRateHz),
                static_cast<unsigned>(feedFrameSamples_),
                static_cast<unsigned>(fetchFrameSamples_),
                static_cast<double>(fetchFrameSamples_) /
                    static_cast<double>(feedFrameSamples_),
                static_cast<unsigned>(feedFramesPerFetch_),
                static_cast<unsigned>(kGeneratedCommandPhraseCount));
  Serial.printf("[ASR] continuous experiment wake_id=%d phrase=%s\n",
                kWakePhraseCommandId, kGeneratedWakePhrasePinyin);
  return true;
}

int MultiNetCommandRecognizer::processFrame(const int16_t* samples,
                                            size_t sampleCount,
                                            bool allowDetection) {
  if (!ready_ || samples == nullptr || sampleCount != feedFrameSamples_) {
    return 0;
  }

  const auto* afe = static_cast<const esp_afe_sr_iface_t*>(afeHandle_);
  auto* afeData = static_cast<esp_afe_sr_data_t*>(afeData_);
  const int feedResult = afe->feed(afeData, samples);
  if (feedResult <= 0) {
    Serial.printf("[ASR] AFE feed failed result=%d\n", feedResult);
    return 0;
  }

  feedSamplesSinceFetch_ += feedFrameSamples_;
  if (feedSamplesSinceFetch_ < fetchFrameSamples_) {
    return 0;
  }
  feedSamplesSinceFetch_ -= fetchFrameSamples_;

  afe_fetch_result_t* result = afe->fetch(afeData);
  if (result == nullptr || result->data == nullptr || result->data_size <= 0 ||
      static_cast<size_t>(result->data_size) !=
          fetchFrameSamples_ * sizeof(int16_t)) {
    Serial.println("[ASR] AFE fetch returned invalid frame");
    return 0;
  }

  //  门控只跳过 MultiNet 推理，不停止 AFE 的 feed/fetch / Gating skips only MultiNet inference; AFE feed/fetch continues
  if (!allowDetection) {
    return 0;
  }

  const auto* multiNet = static_cast<const esp_mn_iface_t*>(multiNet_);
  auto* multiNetData = static_cast<model_iface_data_t*>(multiNetData_);
  if (multiNet->detect(multiNetData, result->data) != ESP_MN_STATE_DETECTED) {
    return 0;
  }

  esp_mn_results_t* results = multiNet->get_results(multiNetData);
  if (results == nullptr || results->num <= 0) {
    return 0;
  }

  const int commandId = results->command_id[0];
  Serial.printf("[ASR] detected id=%d phrase=%d score=%.3f text=%s\n",
                commandId, results->phrase_id[0], results->prob[0],
                results->string);
  multiNet->clean(multiNetData);
  return commandId;
}

//  清空当前语音上下文，避免上一段语音影响下一次识别 / Clear speech context so the next segment starts cleanly
void MultiNetCommandRecognizer::reset() {
  feedSamplesSinceFetch_ = 0;
  if (ready_) {
    const auto* afe = static_cast<const esp_afe_sr_iface_t*>(afeHandle_);
    afe->reset_buffer(static_cast<esp_afe_sr_data_t*>(afeData_));
    const auto* multiNet = static_cast<const esp_mn_iface_t*>(multiNet_);
    multiNet->clean(static_cast<model_iface_data_t*>(multiNetData_));
  }
}

//  返回识别器是否已经初始化完成 / Return whether the recognizer is initialized
bool MultiNetCommandRecognizer::available() const { return ready_; }

MultiNetCommandRecognizer multiNetCommandRecognizer;

}
