#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use rand::{distributions::Alphanumeric, rngs::OsRng, Rng};
use serde::{Deserialize, Serialize};
use std::{
    fs,
    io::Write,
    path::{Path, PathBuf},
    sync::{atomic::{AtomicBool, AtomicUsize, Ordering}, Mutex},
    thread,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tauri::{
    async_runtime::Receiver,
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Emitter, Manager, RunEvent, State, WindowEvent,
};
use tauri_plugin_shell::{process::{CommandChild, CommandEvent}, ShellExt};

#[derive(Clone, Serialize)]
struct DesktopSession {
    base_url: String,
    token: String,
}

struct DesktopState {
    session: Mutex<DesktopSession>,
    child: Mutex<Option<CommandChild>>,
    exiting: AtomicBool,
    restart_count: AtomicUsize,
    data_dir: PathBuf,
    session_id: String,
}

#[tauri::command]
fn desktop_session(state: State<'_, DesktopState>) -> DesktopSession {
    state.session.lock().expect("session lock").clone()
}

#[derive(Deserialize, Serialize)]
struct FrontendDiagnostic {
    error_type: String,
    message: String,
    route: String,
    timestamp: String,
    task_id: Option<String>,
    last_event_id: Option<String>,
    component: Option<String>,
}

#[tauri::command]
fn write_frontend_diagnostic(
    app: tauri::AppHandle,
    state: State<'_, DesktopState>,
    diagnostic: FrontendDiagnostic,
) -> Result<(), String> {
    let data_dir = app.path().app_local_data_dir().map_err(|error| error.to_string())?;
    let logs = data_dir.join("logs");
    fs::create_dir_all(&logs).map_err(|error| error.to_string())?;
    let line = serde_json::to_string(&serde_json::json!({
        "session_id": state.session_id,
        "diagnostic": diagnostic,
    })).map_err(|error| error.to_string())? + "\n";
    std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(logs.join("frontend-error.log"))
        .and_then(|mut file| file.write_all(line.as_bytes()))
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn frontend_heartbeat(state: State<'_, DesktopState>, timestamp: String) -> Result<(), String> {
    let logs = state.data_dir.join("logs");
    fs::create_dir_all(&logs).map_err(|error| error.to_string())?;
    fs::write(
        logs.join("frontend-heartbeat.json"),
        serde_json::to_vec(&serde_json::json!({
            "session_id": state.session_id,
            "renderer_alive_at": timestamp,
        })).map_err(|error| error.to_string())?,
    ).map_err(|error| error.to_string())
}

fn now_millis() -> u128 {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_millis()
}

fn append_desktop_log(data_dir: &Path, session_id: &str, event: &str, detail: &str) {
    let logs = data_dir.join("logs");
    if fs::create_dir_all(&logs).is_err() { return; }
    let Ok(line) = serde_json::to_string(&serde_json::json!({
        "timestamp_ms": now_millis(),
        "session_id": session_id,
        "event": event,
        "detail": detail,
    })) else { return; };
    if let Ok(mut file) = fs::OpenOptions::new().create(true).append(true).open(logs.join("desktop.log")) {
        let _ = writeln!(file, "{line}");
    }
}

fn spawn_sidecar(
    app: &tauri::AppHandle,
    data_dir: &Path,
    ready: &Path,
    token: &String,
    session_id: &str,
) -> Result<(Receiver<CommandEvent>, CommandChild), String> {
    let args = vec![
        "--port".to_string(), "0".to_string(),
        "--data-dir".to_string(), data_dir.to_string_lossy().to_string(),
        "--ready-file".to_string(), ready.to_string_lossy().to_string(),
        "--parent-pid".to_string(), std::process::id().to_string(),
        "--session-id".to_string(), session_id.to_string(),
    ];
    app.shell()
        .sidecar("ai-team-os-sidecar")
        .map_err(|error| error.to_string())?
        .env("AI_TEAM_OS_DESKTOP_SESSION_TOKEN", &token)
        .args(args)
        .spawn()
        .map_err(|error| error.to_string())
}

fn watch_ready(handle: tauri::AppHandle, ready: PathBuf) {
    thread::spawn(move || {
        for _ in 0..200 {
            if let Ok(text) = fs::read_to_string(&ready) {
                if let Ok(value) = serde_json::from_str::<serde_json::Value>(&text) {
                    if let Some(port) = value.get("port").and_then(|value| value.as_u64()) {
                        handle.state::<DesktopState>().session.lock().expect("session lock").base_url =
                            format!("http://127.0.0.1:{port}");
                        let _ = fs::remove_file(&ready);
                        return;
                    }
                }
            }
            thread::sleep(Duration::from_millis(50));
        }
    });
}

fn stop_backend(state: &DesktopState) {
    if let Some(child) = state.child.lock().expect("child lock").take() {
        let _ = child.kill();
    }
}

fn main() {
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![desktop_session, write_frontend_diagnostic, frontend_heartbeat])
        .setup(|app| {
            let data_dir = app.path().app_local_data_dir()?;
            fs::create_dir_all(&data_dir)?;
            let token: String = OsRng
                .sample_iter(&Alphanumeric)
                .take(48)
                .map(char::from)
                .collect();
            let session_id: String = OsRng.sample_iter(&Alphanumeric).take(16).map(char::from).collect();
            let ready = data_dir.join("desktop-backend-ready.json");
            let _ = fs::remove_file(&ready);
            let (events, child) = spawn_sidecar(app.handle(), &data_dir, &ready, &token, &session_id)
                .map_err(std::io::Error::other)?;
            app.manage(DesktopState {
                session: Mutex::new(DesktopSession { base_url: String::new(), token: token.clone() }),
                child: Mutex::new(Some(child)),
                exiting: AtomicBool::new(false),
                restart_count: AtomicUsize::new(0),
                data_dir: data_dir.clone(),
                session_id: session_id.clone(),
            });
            append_desktop_log(&data_dir, &session_id, "desktop_started", "sidecar spawned");
            let show = MenuItem::with_id(app, "show", "打开 AI Team OS", true, None::<&str>)?;
            let pause_jarvis =
                MenuItem::with_id(app, "pause_jarvis", "暂停 JARVIS", true, None::<&str>)?;
            let stop_computer = MenuItem::with_id(
                app,
                "stop_computer",
                "停止电脑控制",
                true,
                None::<&str>,
            )?;
            let toggle_voice =
                MenuItem::with_id(app, "toggle_voice", "语音 开/关", true, None::<&str>)?;
            let settings =
                MenuItem::with_id(app, "settings", "设置", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
            let menu = Menu::with_items(
                app,
                &[
                    &show,
                    &pause_jarvis,
                    &stop_computer,
                    &toggle_voice,
                    &settings,
                    &quit,
                ],
            )?;
            let mut tray = TrayIconBuilder::with_id("main-tray").menu(&menu).show_menu_on_left_click(false);
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.on_menu_event(|app, event| match event.id.as_ref() {
                "show" => {
                    if let Some(window) = app.get_webview_window("main") {
                        let _ = window.show();
                        let _ = window.set_focus();
                    }
                }
                "pause_jarvis" | "stop_computer" | "toggle_voice" => {
                    let _ = app.emit("desktop-tray-action", event.id.as_ref());
                }
                "settings" => {
                    if let Some(window) = app.get_webview_window("main") {
                        let _ = window.show();
                        let _ = window.set_focus();
                    }
                    let _ = app.emit("desktop-tray-action", event.id.as_ref());
                }
                "quit" => {
                    let state = app.state::<DesktopState>();
                    state.exiting.store(true, Ordering::SeqCst);
                    stop_backend(&state);
                    app.exit(0);
                }
                _ => {}
            }).build(app)?;
            watch_ready(app.handle().clone(), ready.clone());
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let mut events = events;
                'monitor: loop {
                    while let Some(event) = events.recv().await {
                        if matches!(event, CommandEvent::Terminated(_)) { break; }
                    }
                    let state = handle.state::<DesktopState>();
                    if state.exiting.load(Ordering::SeqCst) { break; }
                    state.session.lock().expect("session lock").base_url.clear();
                    append_desktop_log(&data_dir, &session_id, "backend_disconnected", "sidecar terminated");
                    loop {
                        let attempt = state.restart_count.fetch_add(1, Ordering::SeqCst) + 1;
                        if attempt > 2 {
                            append_desktop_log(&data_dir, &session_id, "backend_restart_exhausted", "maximum 2 restarts");
                            break 'monitor;
                        }
                        thread::sleep(Duration::from_secs(attempt as u64));
                        let _ = fs::remove_file(&ready);
                        match spawn_sidecar(&handle, &data_dir, &ready, &token, &session_id) {
                            Ok((new_events, child)) => {
                                *state.child.lock().expect("child lock") = Some(child);
                                append_desktop_log(&data_dir, &session_id, "backend_restarted", &format!("attempt {attempt}"));
                                watch_ready(handle.clone(), ready.clone());
                                events = new_events;
                                break;
                            }
                            Err(error) => append_desktop_log(&data_dir, &session_id, "backend_restart_failed", &error),
                        }
                    }
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build AI Team OS desktop");

    builder.run(|app, event| match event {
        RunEvent::WindowEvent { label, event: WindowEvent::CloseRequested { api, .. }, .. }
            if label == "main" && !app.state::<DesktopState>().exiting.load(Ordering::SeqCst) => {
                api.prevent_close();
                if let Some(window) = app.get_webview_window("main") { let _ = window.hide(); }
            }
        RunEvent::ExitRequested { .. } | RunEvent::Exit => stop_backend(&app.state::<DesktopState>()),
        _ => {}
    });
}
