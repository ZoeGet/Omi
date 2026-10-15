import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import ntpath
import os
from pathlib import Path
import uuid

from process_probe import capture, check


class ProcessEntry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]


def process_parents():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry))
    kernel.Process32FirstW.restype = wintypes.BOOL
    kernel.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry))
    kernel.Process32NextW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        if not kernel.Process32FirstW(handle, ctypes.byref(entry)):
            raise ctypes.WinError(ctypes.get_last_error())
        parents = {}
        while True:
            parents[entry.th32ProcessID] = entry.th32ParentProcessID
            if not kernel.Process32NextW(handle, ctypes.byref(entry)):
                error = ctypes.get_last_error()
                if error != 18:
                    raise ctypes.WinError(error)
                return parents
    finally:
        kernel.CloseHandle(handle)


def normalized(image):
    return ntpath.normcase(ntpath.normpath(image))


def ancestry(allowed_images, *, start_pid=None, parents=None, identity_reader=capture,
             identity_checker=check):
    allowed = {normalized(image) for image in allowed_images}
    parent_map = process_parents() if parents is None else parents
    child = identity_reader(os.getpid() if start_pid is None else start_pid)
    chain = [child]
    seen = {child["pid"]}
    result = dict(associationState="unknown", reason="allowed-ancestor-not-found", chain=chain,
                  candidateIdentity=None, sessionLiveness="unverified")
    while parent_map.get(child["pid"]):
        parent_pid = parent_map[child["pid"]]
        if parent_pid in seen:
            result["reason"] = "ancestry-cycle"
            return result
        seen.add(parent_pid)
        parent = identity_reader(parent_pid)
        if int(parent["creationTime100ns"]) > int(child["creationTime100ns"]):
            result["reason"] = "parent-pid-reused"
            return result
        chain.append(parent)
        if normalized(parent["imagePath"]) in allowed:
            if any(identity_checker(identity)["processState"] != "running" for identity in chain):
                result["reason"] = "ancestry-changed-during-query"
                return result
            result.update(associationState="observed", reason="allowed-ancestor-in-hook-process-chain",
                          candidateIdentity=parent)
            return result
        child = parent
    return result


def record(payload, configuration):
    if not configuration.get("enabled") or not payload.get("session_id"):
        return
    allowed = configuration.get("allowedImages")
    if not isinstance(allowed, list) or not allowed or not all(isinstance(item, str) for item in allowed):
        raise ValueError("Explicit allowed images required")
    output = Path(configuration["outputDirectory"])
    if not output.is_absolute():
        raise ValueError("Absolute output directory required")
    event = dict(schema=1, receivedAtUtc=datetime.now(timezone.utc).isoformat(),
                 sessionId=str(payload["session_id"]), turnId=str(payload.get("turn_id") or ""),
                 hookEventName=str(payload.get("hook_event_name") or ""),
                 toolUseId=str(payload.get("tool_use_id") or ""))
    try:
        event.update(ancestry(allowed))
    except Exception as error:
        event.update(associationState="unknown", reason="ancestry-query-failed",
                     exceptionType=type(error).__name__, sessionLiveness="unverified")
    output.mkdir(parents=True, exist_ok=True)
    target = output / (uuid.uuid4().hex + ".json")
    with target.open("x", encoding="utf-8") as stream:
        json.dump(event, stream, ensure_ascii=False, separators=(",", ":"))
