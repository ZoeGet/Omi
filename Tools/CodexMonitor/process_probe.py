import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import ntpath
import os
from pathlib import Path


def valid_identity(identity):
    if not isinstance(identity, dict):
        return False
    pid = identity.get("pid")
    ticks = identity.get("creationTime100ns")
    image = identity.get("imagePath")
    return (type(pid) is int and 0 < pid <= 0xFFFFFFFF
            and isinstance(ticks, str) and len(ticks) <= 20 and ticks.isascii() and ticks.isdecimal()
            and 0 < int(ticks) <= 0xFFFFFFFFFFFFFFFF
            and isinstance(image, str) and bool(ntpath.splitdrive(image)[0])
            and ntpath.isabs(image) and "\x00" not in image)


def read_process(pid):
    if os.name != "nt":
        raise OSError("Windows required")
    if type(pid) is not int or not 0 < pid <= 0xFFFFFFFF:
        raise ValueError("Invalid PID")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD,
                                               wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
            raise ctypes.WinError(ctypes.get_last_error())
        created = str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        image = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(image))
        image_ok = kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(length))
        image_error = ctypes.get_last_error() if not image_ok else None
        outcome = kernel.WaitForSingleObject(handle, 0)
        if outcome not in (0, 0x102):
            raise ctypes.WinError(ctypes.get_last_error())
        if not image_ok and outcome != 0:
            raise ctypes.WinError(image_error)
        return dict(pid=pid, creationTime100ns=created, imagePath=image.value if image_ok else None,
                    processState="exited" if outcome == 0 else "running")
    finally:
        kernel.CloseHandle(handle)


def capture(pid):
    observed = read_process(pid)
    if observed["processState"] != "running" or not valid_identity(observed):
        raise ValueError("Cannot capture a running process identity")
    return {key: observed[key] for key in ("pid", "creationTime100ns", "imagePath")}


def check(identity, reader=read_process):
    result = dict(schema=1, checkedAtUtc=datetime.now(timezone.utc).isoformat(),
                  processState="unknown", reason="invalid-identity", sessionLiveness="unverified")
    if not valid_identity(identity):
        return result
    try:
        observed = reader(identity["pid"])
    except OSError as error:
        result.update(reason="process-query-failed", errorCode=getattr(error, "winerror", None))
        return result
    if not isinstance(observed, dict):
        result["reason"] = "invalid-observation"
        return result
    if observed.get("pid") != identity["pid"] or observed.get("creationTime100ns") != identity["creationTime100ns"]:
        result.update(processState="identityMismatch", reason="process-identity-changed")
    elif observed.get("processState") == "exited":
        result.update(processState="exited", reason="process-signaled")
    elif not valid_identity(observed):
        result["reason"] = "invalid-observation"
    elif ntpath.normcase(ntpath.normpath(observed["imagePath"])) != ntpath.normcase(ntpath.normpath(identity["imagePath"])):
        result.update(processState="identityMismatch", reason="process-image-changed")
    elif observed.get("processState") == "running":
        result.update(processState="running", reason="same-process-observed")
    else:
        result["reason"] = "invalid-observation"
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read-only Windows process identity probe; no session inference")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--capture-pid", type=int)
    group.add_argument("--identity", type=Path)
    args = parser.parse_args()
    try:
        result = capture(args.capture_pid) if args.capture_pid is not None else check(
            json.loads(args.identity.read_text(encoding="utf-8-sig")))
    except (OSError, ValueError, UnicodeError) as error:
        result = dict(processState="unknown", reason="capture-or-input-failed",
                      errorCode=getattr(error, "winerror", None))
    print(json.dumps(result, ensure_ascii=False, indent=2))
