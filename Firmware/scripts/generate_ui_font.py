import argparse
import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


FONT_SHA256 = '2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b'
LABELS = ('桌面伙伴设备温度湿度已连接离线配网中语音就绪正在聆听配对未就绪'
          '等待联网校时任务活动更多暂无活动任务来源不可用标题不可用等待操作正在处理'
          '在电脑端输入配对码后失效离线语音试试说「亮一点」我在听')
SIZES = {
    11: ''.join(chr(i) for i in range(32, 127)) + '°',
    14: ''.join(chr(i) for i in range(32, 127)) + LABELS,
    24: '-.0123456789',
    27: '我在听',
    39: ' 0123456789',
    43: '-:0123456789',
}


def generate(font_path):
    if hashlib.sha256(font_path.read_bytes()).hexdigest() != FONT_SHA256:
        raise ValueError('Expected pinned Noto Sans CJK SC Regular source; see assets/fonts/README.md')
    data, glyphs = [], []
    for size, characters in sorted(SIZES.items()):
        font = ImageFont.truetype(str(font_path), size, layout_engine=ImageFont.Layout.BASIC)
        for char in sorted(set(characters)):
            left, top, right, bottom = font.getbbox(char, anchor='ls')
            width, height = right - left, bottom - top
            advance = round(font.getlength(char))
            image = Image.new('L', (max(1, width), max(1, height)))
            draw = ImageDraw.Draw(image)
            if ord(char) > 255 and size <= 14:
                draw.fontmode = '1'
            draw.text((-left, -top), char, font=font, anchor='ls', fill=255)
            alpha = [round(v * 15 / 255) for v in image.tobytes()] if height else []
            offset = len(data)
            data.extend((alpha[i] << 4) | (alpha[i + 1] if i + 1 < len(alpha) else 0)
                        for i in range(0, len(alpha), 2))
            assert 0 <= width < 256 and 0 <= height < 256 and -128 <= top < 128
            assert len(data) - offset == (width * height + 1) // 2
            glyphs.append((ord(char), offset, size, width, height, advance, left, top))
    lines = ['#pragma once', '#include <cstdint>', '',
             '//  生成的 Omi UI 字模，源字体及许可见 assets/fonts / Generated Omi UI glyphs; source and license in assets/fonts',
             '//  使用 generate_ui_font.py 重建，4 位覆盖率按行高半字节优先 / Rebuild with generate_ui_font.py; row-major 4-bit coverage, high nibble first',
             'namespace OmiPetUiFont {',
             'struct Glyph { uint32_t codepoint, offset; uint8_t size, width, height, advance; int8_t left, top; };',
             'constexpr uint8_t kPixels[] = {']
    lines.extend('  ' + ', '.join(f'0x{n:02x}' for n in data[i:i + 24]) + ','
                 for i in range(0, len(data), 24))
    lines += ['};', 'constexpr Glyph kGlyphs[] = {']
    lines.extend('  {' + ', '.join(str(n) for n in glyph) + '},' for glyph in glyphs)
    lines += ['};', '}  //  字模命名空间 / Glyph namespace', '']
    return '\n'.join(lines), len(data), len(glyphs)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='生成离线 UI 字模 / Generate offline UI glyphs')
    parser.add_argument('font', type=Path)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'include/omi_ui_font.h')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    result, byte_count, glyph_count = generate(args.font)
    if args.check:
        assert args.output.read_text(encoding='utf-8') == result, 'Glyph output differs'
    else:
        args.output.write_text(result, encoding='utf-8', newline='\n')
    print(f'{glyph_count} glyphs, {byte_count} coverage bytes')
