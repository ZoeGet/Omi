import base64
import ctypes
from ctypes import wintypes
from functools import lru_cache
import json
import os
from pathlib import Path

WIDTH, HEIGHT = 160, 16


@lru_cache(maxsize=64)
def render_title(text, width=WIDTH):
    #  仅栅格化标题，使用系统字库且不读取或传输正文 / Rasterize titles with system fonts without reading or transmitting conversation bodies
    if os.name != 'nt':
        raise OSError('Windows title renderer required')
    gdi = ctypes.WinDLL('gdi32', use_last_error=True)
    user = ctypes.WinDLL('user32', use_last_error=True)
    for name in ('CreateCompatibleDC', 'CreateDIBSection', 'SelectObject', 'CreateFontW'):
        getattr(gdi, name).restype = ctypes.c_void_p
    gdi.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi.CreateDIBSection.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, wintypes.DWORD]
    gdi.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi.DeleteDC.argtypes = [ctypes.c_void_p]
    gdi.SetTextColor.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    gdi.SetBkMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
    gdi.CreateFontW.argtypes = [ctypes.c_int] * 5 + [wintypes.DWORD] * 8 + [wintypes.LPCWSTR]
    user.DrawTextW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.RECT), wintypes.UINT]
    class Header(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('width', wintypes.LONG), ('height', wintypes.LONG),
                    ('planes', wintypes.WORD), ('bits', wintypes.WORD), ('compression', wintypes.DWORD),
                    ('image', wintypes.DWORD), ('x', wintypes.LONG), ('y', wintypes.LONG),
                    ('used', wintypes.DWORD), ('important', wintypes.DWORD)]
    info = Header(40, width, -HEIGHT, 1, 32, 0, width * HEIGHT * 4, 0, 0, 0, 0)
    dc = gdi.CreateCompatibleDC(None)
    bits = ctypes.c_void_p()
    bitmap = gdi.CreateDIBSection(dc, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
    font = gdi.CreateFontW(-14, 0, 0, 0, 500, 0, 0, 0, 1, 0, 0, 3, 0, 'Microsoft YaHei UI')
    old_bitmap = old_font = None
    try:
        if not dc or not bitmap or not bits.value or not font:
            raise OSError('Title rendering unavailable')
        old_bitmap = gdi.SelectObject(dc, bitmap)
        old_font = gdi.SelectObject(dc, font)
        ctypes.memset(bits, 0, width * HEIGHT * 4)
        gdi.SetTextColor(dc, 0xFFFFFF)
        gdi.SetBkMode(dc, 1)
        rect = wintypes.RECT(0, 0, width, HEIGHT)
        if not user.DrawTextW(dc, text, -1, ctypes.byref(rect), 0x8000 | 0x800 | 0x20 | 4):
            raise OSError('Title rendering failed')
        gdi.GdiFlush()
        pixels = ctypes.string_at(bits, width * HEIGHT * 4)
        packed = bytearray(width * HEIGHT // 8)
        for i in range(width * HEIGHT):
            if max(pixels[i * 4:i * 4 + 3]) >= 96:
                packed[i // 8] |= 0x80 >> (i % 8)
        return bytes(packed)
    finally:
        if old_font: gdi.SelectObject(dc, old_font)
        if old_bitmap: gdi.SelectObject(dc, old_bitmap)
        if font: gdi.DeleteObject(font)
        if bitmap: gdi.DeleteObject(bitmap)
        if dc: gdi.DeleteDC(dc)


class TaskCards:
    def __init__(self, index=None, renderer=render_title):
        self.index = Path(index) if index else Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'session_index.jsonl'
        self.renderer = renderer
        self.slots = [None] * 4
        self.stamp = None
        self.titles = {}

    def read_titles(self):
        try:
            stat = self.index.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
            if stamp != self.stamp:
                if stat.st_size > 2 * 1024 * 1024:
                    raise ValueError('Title index too large')
                titles = {}
                with self.index.open(encoding='utf-8') as stream:
                    content = stream.read(2 * 1024 * 1024 + 1)
                    if len(content) > 2 * 1024 * 1024:
                        raise ValueError('Title index too large')
                    for line in content.splitlines():
                        if len(line) > 4096: continue
                        try:
                            item = json.loads(line)
                            if isinstance(item, dict) and isinstance(item.get('id'), str) and isinstance(item.get('thread_name'), str):
                                titles[item['id']] = ' '.join(item['thread_name'].split())[:120]
                        except (ValueError, TypeError):
                            continue
                self.titles, self.stamp = titles, stamp
        except (OSError, ValueError, UnicodeError):
            self.titles, self.stamp = {}, None

    def build(self, body, aliases):
        self.read_titles()
        active = [s for s in body['sessions'] if s['display'] in ('working', 'waitingApproval')]
        previous = {key: i for i, key in enumerate(self.slots) if key}
        ranked = sorted(active, key=lambda s: (s['display'] != 'waitingApproval', previous.get(s['id'], 4), s['id']))
        selected = {s['id']: s for s in ranked[:4]}
        self.slots = [key if key in selected else None for key in self.slots]
        for entry in ranked[:4]:
            if entry['id'] not in self.slots:
                self.slots[self.slots.index(None)] = entry['id']
        real_ids = {alias: key for key, alias in aliases.items()}
        cards = []
        for slot, alias in enumerate(self.slots):
            if alias is None: continue
            title = self.titles.get(real_ids.get(alias)) or f'Conversation {alias}'
            try:
                pixels = self.renderer(title)
            except (OSError, ValueError):
                pixels = bytes(WIDTH * HEIGHT // 8)
            cards.append(dict(slot=slot, id=alias, bitmap=base64.b64encode(pixels).decode('ascii')))
        result = dict(active=len(active), cards=cards)
        try:
            result['labels'] = base64.b64encode(render_title('等待操作', 64) + render_title('正在处理', 64)).decode('ascii')
        except (OSError, ValueError):
            pass
        return result
