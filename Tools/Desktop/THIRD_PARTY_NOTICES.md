# Third-party components

This application uses packages from their official npm / crates.io distributions. Exact JavaScript and Rust versions are recorded in `package-lock.json` and `Cargo.lock`. No Clash Verge or CC Switch source code is incorporated.

| Component | Source | License |
|---|---|---|
| Tauri and its CLI | https://github.com/tauri-apps/tauri | MIT OR Apache-2.0 |
| React / React DOM | https://github.com/facebook/react | MIT |
| Material UI | https://github.com/mui/material-ui | MIT |
| Material Icons | https://github.com/mui/material-ui/tree/master/packages/mui-icons-material | MIT package; icon designs Apache-2.0 |
| Emotion | https://github.com/emotion-js/emotion | MIT |
| Vite / React plugin | https://github.com/vitejs/vite | MIT |
| TypeScript | https://github.com/microsoft/TypeScript | Apache-2.0 |
| Vitest | https://github.com/vitest-dev/vitest | MIT |
| Testing Library | https://github.com/testing-library | MIT |
| jsdom | https://github.com/jsdom/jsdom | MIT |
| websocket-client 1.9.2 | https://github.com/websocket-client/websocket-client | Apache-2.0 |
| Mbed TLS 2.28.7 (EC J-PAKE native helper) | https://github.com/Mbed-TLS/mbedtls/tree/v2.28.7 | Apache-2.0 OR GPL-2.0-or-later; distributed under Apache-2.0 |

System fonts (Segoe UI / Microsoft YaHei UI) are referenced by name and are not bundled. Windows WebView2 is a separate Microsoft runtime. Portable packages include dependency license texts; no remote release has been published.

The Windows portable application directory includes `DEPENDENCY_LICENSES.txt` with the collected production npm and downloaded Rust build-source license texts. This intentionally includes build-time crates. The unchanged transitive `selectors` 0.38.0 crate uses MPL-2.0; its source is available at https://github.com/servo/stylo/tree/572ecba2d1600e7c3d490586692a209faf703baa/selectors and https://crates.io/crates/selectors/0.38.0. Additional text sources are the Mozilla MPL-2.0 text and upstream license files at the exact `alloc-stdlib` / `webview2-com` source revisions recorded by Cargo.

The device backend reuses OmiPet's existing Python control code. Bundled Python uses the PSF license; pyserial 3.5 uses BSD-3-Clause; the PyInstaller bootloader is distributed under its GPL exception (see bundled COPYING text). This package does not include CustomTkinter, Pillow or Tk UI code. Tauri's official dialog plugin uses MIT OR Apache-2.0 and is restricted to opening native file/directory selectors.

Supplementary license texts are retained in `licenses/` when an upstream package archive omits its text. Sources: pyserial v3.5 `LICENSE.txt`; Tauri `LICENSE-MIT` at `59b63ab500da9859f12d8888c3298bc29bba0b92` for tauri-plugin 2.7.2; the previously verified pinned sources for alloc-stdlib, selectors and webview2-com. They are included by `collect_licenses.py` and must accompany portable distribution.
