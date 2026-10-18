#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde_json::{json, Value};
use std::{
    io::{BufRead, BufReader, Write},
    process::{Child, ChildStdin, ChildStdout, Command, Stdio},
    sync::{atomic::{AtomicBool, Ordering}, Arc, Mutex},
};
use tauri::Manager;
use tauri::{menu::{Menu, MenuItem, PredefinedMenuItem}, tray::{TrayIconBuilder, TrayIconEvent, MouseButton, MouseButtonState}};

mod window_behavior;

#[derive(Default)]
struct WindowBehavior {
    exit_on_close: AtomicBool,
    tray_available: AtomicBool,
}

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

fn show_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

fn exit_app(app: &tauri::AppHandle) {
    let backend = app.state::<Backend>().inner().clone();
    if backend.closing.swap(true, Ordering::SeqCst) {
        return;
    }
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.set_title("Omi · 正在释放设备连接…");
    }
    let app = app.clone();
    std::thread::spawn(move || {
        //  所有退出入口先完成原有释放，再结束托盘和进程 / Every exit path completes the existing release before ending the tray and process
        backend.close();
        app.exit(0);
    });
}

#[tauri::command]
fn window_control(window: tauri::WebviewWindow, action: String, behavior: Option<String>) -> Result<Value, String> {
    if window.label() != "main" {
        return Err("此窗口无应用控制权限。".into());
    }
    let app = window.app_handle();
    if app.state::<Backend>().closing.load(Ordering::SeqCst) {
        return Err("正在释放设备连接…".into());
    }
    let state = app.state::<WindowBehavior>();
    match action.as_str() {
        "settings" => {},
        "close-behavior" => {
            let path = app.path().app_config_dir().map_err(|e| e.to_string())?.join("window.json");
            let exit = window_behavior::save(&path, behavior.as_deref().ok_or("缺少关闭行为。")?)?;
            state.exit_on_close.store(exit, Ordering::SeqCst);
        },
        "hide" => {
            if !state.tray_available.load(Ordering::SeqCst) {
                return Err("托盘不可用，已保留主窗口。".into());
            }
            window.hide().map_err(|e| format!("无法隐藏窗口：{e}"))?;
        },
        "quit" => exit_app(app),
        _ => return Err("无效的应用控制操作。".into()),
    }
    Ok(json!({"closeBehavior": if state.exit_on_close.load(Ordering::SeqCst) {"exit"} else {"tray"},
              "trayAvailable": state.tray_available.load(Ordering::SeqCst)}))
}

fn main() {
    tauri::Builder::default()
        .manage(Backend::default())
        .manage(WindowBehavior::default())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![request, window_control])
        .setup(|app| {
            if let Ok(path) = app.path().app_config_dir() {
                app.state::<WindowBehavior>().exit_on_close.store(window_behavior::read(&path.join("window.json")), Ordering::SeqCst);
            }
            let show = MenuItem::with_id(app, "show", "显示主窗口", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "退出软件", true, None::<&str>)?;
            let separator = PredefinedMenuItem::separator(app)?;
            let menu = Menu::with_items(app, &[&show, &separator, &quit])?;
            if let Some(icon) = app.default_window_icon() {
                let tray = TrayIconBuilder::with_id("omi-tray")
                    .icon(icon.clone())
                    .tooltip("Omi · 设备控制中心（右键退出）")
                    .menu(&menu)
                    .show_menu_on_left_click(false)
                    .on_menu_event(|app, event| match event.id.as_ref() {
                        "show" => show_window(app),
                        "quit" => exit_app(app),
                        _ => {},
                    })
                    .on_tray_icon_event(|tray, event| {
                        if matches!(event, TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. }) {
                            show_window(tray.app_handle());
                        }
                    }).build(app);
                app.state::<WindowBehavior>().tray_available.store(tray.is_ok(), Ordering::SeqCst);
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let app = window.app_handle();
                if app.state::<Backend>().closing.load(Ordering::SeqCst) {
                    return;
                }
                let behavior = app.state::<WindowBehavior>();
                if !behavior.exit_on_close.load(Ordering::SeqCst) && behavior.tray_available.load(Ordering::SeqCst) {
                    let _ = window.hide();
                } else {
                    exit_app(app);
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("OmiPet failed to start")
        .run(|app, event| {
            if let tauri::RunEvent::ExitRequested { api, .. } = event {
                if !app.state::<Backend>().closing.load(Ordering::SeqCst) {
                    api.prevent_exit();
                    exit_app(app);
                }
            }
        });
}
