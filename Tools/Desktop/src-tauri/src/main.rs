#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde_json::{json, Value};
use std::{
    io::{BufRead, BufReader, Write},
    process::{Child, ChildStdin, ChildStdout, Command, Stdio},
    sync::{atomic::{AtomicBool, Ordering}, Arc, Mutex},
};
use tauri::Manager;

struct Process {
    child: Child,
    input: ChildStdin,
    output: BufReader<ChildStdout>,
}

impl Process {
    fn start() -> Result<Self, String> {
        let path = std::env::current_exe().map_err(|e| e.to_string())?
            .with_file_name("omi-device").join("omi-device.exe");
        let mut command = Command::new(path);
        if std::env::args().any(|arg| arg == "--demo") {
            command.arg("--demo");
        }
        command.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000);
        }
        let mut child = command.spawn().map_err(|e| format!("设备后台启动失败：{e}"))?;
        let input = child.stdin.take().unwrap();
        let output = BufReader::new(child.stdout.take().unwrap());
        Ok(Self { child, input, output })
    }

    fn exchange(&mut self, message: &Value) -> Result<Value, String> {
        let line = serde_json::to_string(message).map_err(|e| e.to_string())?;
        if line.len() > 4096 {
            return Err("请求超过 4096 字节".into());
        }
        writeln!(self.input, "{line}").and_then(|_| self.input.flush())
            .map_err(|e| format!("设备后台通信失败：{e}"))?;
        let mut reply = String::new();
        if self.output.read_line(&mut reply).map_err(|e| e.to_string())? == 0 {
            return Err("设备后台已退出，请关闭程序后重试。".into());
        }
        serde_json::from_str(&reply).map_err(|_| "设备后台返回了无效消息。".into())
    }

    fn close(mut self) {
        let _ = self.exchange(&json!({"action": "close", "body": null}));
        drop(self.input);
        let _ = self.child.wait();
    }
}

#[derive(Clone, Default)]
struct Backend {
    process: Arc<Mutex<Option<Process>>>,
    closing: Arc<AtomicBool>,
}

impl Backend {
    fn call(&self, message: Value) -> Result<Value, String> {
        let mut process = self.process.lock().map_err(|_| "设备后台不可用。")?;
        if self.closing.load(Ordering::SeqCst) {
            return Err("正在释放设备连接…".into());
        }
        if process.is_none() {
            *process = Some(Process::start()?);
        }
        process.as_mut().unwrap().exchange(&message)
    }

    fn close(&self) {
        if let Ok(mut process) = self.process.lock() {
            if let Some(process) = process.take() {
                process.close();
            }
        }
    }
}

#[tauri::command]
async fn request(window: tauri::WebviewWindow, state: tauri::State<'_, Backend>, message: Value) -> Result<Value, String> {
    if window.label() != "main" {
        return Err("此窗口无设备控制权限。".into());
    }
    let backend = state.inner().clone();
    //  管道读写放到后台，避免阻塞窗口布局与绘制 / Keep pipe I/O off the window layout and rendering thread
    tauri::async_runtime::spawn_blocking(move || backend.call(message)).await.map_err(|e| e.to_string())?
}

fn main() {
    tauri::Builder::default()
        .manage(Backend::default())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![request])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let backend = window.state::<Backend>().inner().clone();
                if backend.closing.swap(true, Ordering::SeqCst) {
                    return;
                }
                let window = window.clone();
                let _ = window.set_title("Omi · 正在释放设备连接…");
                std::thread::spawn(move || {
                    backend.close();
                    let _ = window.destroy();
                });
            }
        })
        .run(tauri::generate_context!())
        .expect("OmiPet failed to start");
}
