# Omi UI 字模

`include/omi_ui_font.h` 是随固件编译的 **Omi UI** 位图字模子集，采用 4 位覆盖率并在 RGB565 区域缓冲中混合。小号中文使用 14 像素、FreeType 单色栅格化，覆盖率仅为 0/15，避免小字灰边发虚；ASCII 与大号文字保留抗锯齿。只包含页面固定中文、ASCII 和需要的大号数字，不在设备加载完整字体，也不改变电脑发送的 160×16 单色任务标题协议。

来源：[Noto Sans CJK SC Regular](https://github.com/notofonts/noto-cjk/blob/f8d157532fbfaeda587e826d4cd5b21a49186f7c/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf)，版本由提交 `f8d157532fbfaeda587e826d4cd5b21a49186f7c` 固定。源文件 SHA256：`2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b`。

源字体与派生字模采用 [SIL Open Font License 1.1](OFL.txt)，版权与字体内嵌声明见 [NOTICE.txt](NOTICE.txt)。分发字模时保留这两个文件。字模许可独立于项目代码许可。

普通固件构建直接使用已生成头文件，不下载字体，不需要 Pillow。维护字模时，下载上述固定版本的字体到本地忽略目录，使用 Python 3.10+ 与 Pillow 12.3.0 执行：

```powershell
python Firmware/scripts/generate_ui_font.py <本地字体路径>
python Firmware/scripts/generate_ui_font.py <本地字体路径> --check
```

生成器先校验源字体哈希，字符集和字号由 `SIZES` 定义。添加固定文案时同步补充字符集并核对原生像素渲染；不要直接编辑生成头文件。完整 OTF 只留本地缓存。
