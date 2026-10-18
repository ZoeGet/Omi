# Third-party components

This application uses packages from their official npm / crates.io distributions. Exact JavaScript and Rust versions are recorded in `package-lock.json` and `src-tauri/Cargo.lock`. Its layout follows Microsoft WinUI Gallery design concepts; no Gallery XAML or business code is incorporated.

| Component | Source | License |
|---|---|---|
| Tauri and its CLI | https://github.com/tauri-apps/tauri | MIT OR Apache-2.0 |
| React / React DOM | https://github.com/facebook/react | MIT |
| Fluent UI React Components 9.74.9 | https://github.com/microsoft/fluentui | MIT |
| Fluent UI React Icons 2.0.344 | https://github.com/microsoft/fluentui-system-icons | MIT |
| Vite / React plugin | https://github.com/vitejs/vite | MIT |
| TypeScript | https://github.com/microsoft/TypeScript | Apache-2.0 |
| Vitest | https://github.com/vitest-dev/vitest | MIT |
| Testing Library | https://github.com/testing-library | MIT |
| jsdom | https://github.com/jsdom/jsdom | MIT |
| websocket-client 1.9.2 | https://github.com/websocket-client/websocket-client | Apache-2.0 |
| Mbed TLS 2.28.7 (EC J-PAKE native helper) | https://github.com/Mbed-TLS/mbedtls/tree/v2.28.7 | Apache-2.0 OR GPL-2.0-or-later; distributed under Apache-2.0 |

System fonts (Segoe UI / Microsoft YaHei UI) are referenced by name and are not bundled. Windows WebView2 is a separate Microsoft runtime. Portable packages include dependency license texts. Building a local portable package does not publish a remote release.

The Misaka Mikoto app avatar was prepared with the built-in imagegen tool using an official anime portrait as its reference: https://toaru-project.com/index_3/chara/mikoto.html. Character and reference-art rights remain with their original rightsholders; it is not included under the software dependencies' MIT licenses. Details and the preparation prompt are in `src-tauri/icons/README.md` in the source tree, or `APP_ICON_SOURCE.md` in a portable package.

The Windows portable application directory includes `DEPENDENCY_LICENSES.txt` with the collected production npm and downloaded Rust build-source license texts. This intentionally includes build-time crates. The unchanged transitive `selectors` 0.38.0 crate uses MPL-2.0; its source is available at https://github.com/servo/stylo/tree/572ecba2d1600e7c3d490586692a209faf703baa/selectors and https://crates.io/crates/selectors/0.38.0. Additional text sources are the Mozilla MPL-2.0 text and upstream license files at the exact `alloc-stdlib` / `webview2-com` source revisions recorded by Cargo.

The device backend reuses OmiPet's existing Python control code. Bundled Python uses the PSF license; pyserial 3.5 uses BSD-3-Clause; the PyInstaller bootloader is distributed under its GPL exception (see bundled COPYING text). This package does not include CustomTkinter, Pillow or Tk UI code. Tauri's official dialog plugin uses MIT OR Apache-2.0 and is restricted to opening native file/directory selectors.

Supplementary license texts are retained in `licenses/` when an upstream package archive omits its text. Sources: pyserial v3.5 `LICENSE.txt`; Tauri `LICENSE-MIT` at `59b63ab500da9859f12d8888c3298bc29bba0b92` for tauri-plugin 2.7.2; the previously verified pinned sources for alloc-stdlib, selectors and webview2-com. They are included by `collect_licenses.py` and must accompany portable distribution.

Fluent UI supplements: `react-icons.txt` comes from microsoft/fluentui-system-icons `f1260014e8a4fcfa6777182fd6cf082fc5e952d8/LICENSE` (2.0.344). The Embla Carousel 8.6.0 family is an indirect Fluent UI dependency; `embla-carousel.txt`, `embla-carousel-autoplay.txt` and `embla-carousel-fade.txt` use davidjerleke/embla-carousel `0fe65834136f1aa35e4c1a4a477e5ccb4bb5ee54/LICENSE`. All four supplements are MIT license texts from the exact published package revisions.
