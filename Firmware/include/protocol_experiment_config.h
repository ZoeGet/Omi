#pragma once

//  实验入口默认关闭，不修改已验证的串口行为 / Keep the experiment disabled by default and preserve verified serial behavior
#ifndef OMIPET_PROTOCOL_EXPERIMENT
#define OMIPET_PROTOCOL_EXPERIMENT 0
#endif

//  USB 执行入口独立于已验证的诊断入口，默认关闭 / Keep the USB execution path separate from verified diagnostics and disabled by default
#ifndef OMIPET_PROTOCOL_USB
#define OMIPET_PROTOCOL_USB 0
#endif
//  短连接信号过滤默认关闭，仅在隔离 USB 实验中显式选择。 / Short link-signal filtering stays off unless explicitly selected for an isolated USB experiment.
#ifndef OMIPET_PROTOCOL_LINK_GRACE_MS
#define OMIPET_PROTOCOL_LINK_GRACE_MS 0
#endif
#if OMIPET_PROTOCOL_LINK_GRACE_MS && !OMIPET_PROTOCOL_USB
#error "Link grace requires USB protocol"
#endif
//  挑战校验仅在隔离实验构建中显式启用 / Enable freshness challenges explicitly in isolated experiment builds only
#ifndef OMIPET_PROTOCOL_FRESHNESS_CHALLENGE
#define OMIPET_PROTOCOL_FRESHNESS_CHALLENGE 0
#endif
//  实体灯带仲裁单独开启，稳定构建保持本地灯效 / Gate physical LED arbitration separately so stable builds keep local effects
#ifndef OMIPET_MONITOR_LIGHTS
#define OMIPET_MONITOR_LIGHTS 0
#endif
//  新监控规则独立启用：来源未知为绿，监控断联为关灯 / Independently enable green for unknown sources and off for monitor disconnection
#ifndef OMIPET_MONITOR_GREEN_OFF
#define OMIPET_MONITOR_GREEN_OFF 0
#endif
#if OMIPET_MONITOR_GREEN_OFF != 0 && OMIPET_MONITOR_GREEN_OFF != 1
#error "OMIPET_MONITOR_GREEN_OFF must be 0 or 1"
#endif
#if OMIPET_MONITOR_GREEN_OFF && !OMIPET_MONITOR_LIGHTS
#error "Green/off monitor policy requires monitor lights"
#endif
//  上位机手动灯光命令单独隔离，默认关闭 / Isolate desktop manual-light commands and keep them disabled by default
#ifndef OMIPET_DESKTOP_CONTROL
#define OMIPET_DESKTOP_CONTROL 0
#endif
#if OMIPET_DESKTOP_CONTROL != 0 && OMIPET_DESKTOP_CONTROL != 1
#error "OMIPET_DESKTOP_CONTROL must be 0 or 1"
#endif
#if OMIPET_DESKTOP_CONTROL && !OMIPET_PROTOCOL_USB
#error "Desktop control requires USB protocol"
#endif
#if OMIPET_MONITOR_LIGHTS != 0 && OMIPET_MONITOR_LIGHTS != 1
#error "OMIPET_MONITOR_LIGHTS must be 0 or 1"
#endif
#if OMIPET_MONITOR_LIGHTS && (!OMIPET_PROTOCOL_USB || !OMIPET_PROTOCOL_FRESHNESS_CHALLENGE)
#error "Monitor lights require USB protocol and freshness challenge"
#endif
#if OMIPET_PROTOCOL_FRESHNESS_CHALLENGE != 0 && OMIPET_PROTOCOL_FRESHNESS_CHALLENGE != 1
#error "OMIPET_PROTOCOL_FRESHNESS_CHALLENGE must be 0 or 1"
#endif
#if OMIPET_PROTOCOL_FRESHNESS_CHALLENGE && !OMIPET_PROTOCOL_USB
#error "Freshness challenge requires USB protocol"
#endif
#if OMIPET_PROTOCOL_USB != 0 && OMIPET_PROTOCOL_USB != 1
#error "OMIPET_PROTOCOL_USB must be 0 or 1"
#endif
#if OMIPET_PROTOCOL_USB
#if !OMIPET_PROTOCOL_EXPERIMENT
#error "USB protocol requires OMIPET_PROTOCOL_EXPERIMENT"
#endif
#if !defined(OMIPET_PROTOCOL_MAX_SESSIONS) || !defined(OMIPET_PROTOCOL_LEASE_MS) || !defined(OMIPET_PROTOCOL_TX_BUFFER_BYTES) || !defined(OMIPET_PROTOCOL_WRITE_WAIT_MS)
#error "Explicit USB session, lease, TX buffer and write-wait budgets required"
#endif
static_assert(OMIPET_PROTOCOL_MAX_SESSIONS > 0, "Positive session capacity required");
static_assert(OMIPET_PROTOCOL_LEASE_MS > 0 && OMIPET_PROTOCOL_LEASE_MS <= 4294967295ULL, "Lease must fit uint32");
static_assert(OMIPET_PROTOCOL_LINK_GRACE_MS >= 0 && OMIPET_PROTOCOL_LINK_GRACE_MS < OMIPET_PROTOCOL_LEASE_MS,
              "Link grace must be nonnegative and shorter than the lease");
static_assert(OMIPET_PROTOCOL_TX_BUFFER_BYTES >= OMIPET_PROTOCOL_MAX_JSON_BYTES + 8, "TX buffer must hold a complete frame");
static_assert(OMIPET_PROTOCOL_WRITE_WAIT_MS > 0, "HWCDC requires a positive write timeout");
#endif

#if OMIPET_PROTOCOL_EXPERIMENT != 0 && OMIPET_PROTOCOL_EXPERIMENT != 1
#error "OMIPET_PROTOCOL_EXPERIMENT must be 0 or 1"
#endif

#if OMIPET_PROTOCOL_EXPERIMENT
//  开启实验必须显式提供资源预算，不设置实机默认阈值 / Enabling requires explicit resource budgets without device defaults
#ifndef OMIPET_PROTOCOL_MAX_JSON_BYTES
#error "Define OMIPET_PROTOCOL_MAX_JSON_BYTES for the experiment"
#endif
#ifndef OMIPET_PROTOCOL_RX_BYTES_PER_LOOP
#error "Define OMIPET_PROTOCOL_RX_BYTES_PER_LOOP for the experiment"
#endif
#ifndef OMIPET_PROTOCOL_MAX_JSON_DEPTH
#error "Define OMIPET_PROTOCOL_MAX_JSON_DEPTH for the experiment"
#endif
static_assert(OMIPET_PROTOCOL_MAX_JSON_BYTES > 0, "JSON byte budget must be positive");
static_assert(OMIPET_PROTOCOL_RX_BYTES_PER_LOOP > 0, "RX byte budget must be positive");
static_assert(OMIPET_PROTOCOL_MAX_JSON_DEPTH > 0, "JSON depth budget must be positive");
#endif
