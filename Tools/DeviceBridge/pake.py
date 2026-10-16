import ctypes as c
import os
from pathlib import Path
import sys


class Pake:
    def __init__(self, code, *, server=False, library=None):
        if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdecimal():
            raise ValueError("配对码必须为六位数字")
        path = library or os.environ.get("OMIPET_PAKE_LIBRARY")
        if not path:
            path = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent / "Desktop/build/crypto")) / "omi_pake.dll"
        self.lib = c.CDLL(str(path))
        self.lib.omi_pake_create.argtypes = [c.c_int, c.c_char_p]
        self.lib.omi_pake_create.restype = c.c_void_p
        self.lib.omi_pake_write.argtypes = [c.c_void_p, c.c_void_p, c.POINTER(c.c_size_t)]
        self.lib.omi_pake_read.argtypes = [c.c_void_p, c.c_void_p, c.c_size_t]
        self.lib.omi_pake_derive.argtypes = [c.c_void_p, c.c_void_p]
        self.lib.omi_pake_free.argtypes = [c.c_void_p]
        self.lib.omi_pake_free.restype = None
        self.peer = self.lib.omi_pake_create(int(server), code.encode("ascii"))
        if not self.peer:
            raise RuntimeError("无法初始化安全配对")

    def write(self):
        data, size = c.create_string_buffer(1024), c.c_size_t()
        if not self.lib.omi_pake_write(self.peer, data, c.byref(size)):
            raise ValueError("配对交换失败")
        return data.raw[:size.value]

    def read(self, data):
        if not isinstance(data, bytes) or not 0 < len(data) <= 1024:
            raise ValueError("配对交换长度无效")
        if not self.lib.omi_pake_read(self.peer, data, len(data)):
            raise ValueError("配对交换校验失败")

    def derive(self):
        data = c.create_string_buffer(32)
        if not self.lib.omi_pake_derive(self.peer, data):
            raise ValueError("配对密钥生成失败")
        return data.raw

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.lib.omi_pake_free(self.peer)
        self.peer = None
