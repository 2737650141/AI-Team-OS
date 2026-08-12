#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use rand::{distributions::Alphanumeric, rngs::OsRng, Rng};
use serde::Serialize;
use std::{
    fs,
    sync::{atomic::{AtomicBool, Ordering}, Mutex},
    thread,
    time::Duration,
};
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Manager, RunEvent, State, WindowEvent,
};
use tauri_plugin_shell::{process::CommandChild, ShellExt};

#[derive(Clone, Serialize)]
struct DesktopSession {
    base_url: String,
    token: String,
}

struct DesktopState {
    session: Mutex<DesktopSession>,
    child: Mutex<Option<CommandChild>>,
    exiting: AtomicBool,
}

#[tauri::command]
fn desktop_session(state: State<'_, DesktopState>) -> DesktopSession {
    state.session.lock().expect("session lock").clone()
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
        .invoke_handler(tauri::generate_handler![desktop_session])
        .setup(|app| {
            let data_dir = app.path().app_local_data_dir()?;
            fs::create_dir_all(&data_dir)?;
            let token: String = OsRng
                .sample_iter(&Alphanumeric)
                .take(48)
                .map(char::from)
                .collect();
            let ready = data_dir.join("desktop-backend-ready.json");
            let _ = fs::remove_file(&ready);
            let args = vec![
                "--port".to_string(), "0".to_string(),
                "--data-dir".to_string(), data_dir.to_string_lossy().to_string(),
                "--ready-file".to_string(), ready.to_string_lossy().to_string(),
            ];
            let (_events, child) = app
                .shell()
                .sidecar("ai-team-os-sidecar")?
                .env("AI_TEAM_OS_DESKTOP_SESSION_TOKEN", &token)
                .args(args)
                .spawn()?;
            app.manage(DesktopState {
                session: Mutex::new(DesktopSession { base_url: String::new(), token }),
                child: Mutex::new(Some(child)),
                exiting: AtomicBool::new(false),
            });
            let show = MenuItem::with_id(app, "show", "Show AI Team OS", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quit])?;
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
                "quit" => {
                    let state = app.state::<DesktopState>();
                    state.exiting.store(true, Ordering::SeqCst);
                    stop_backend(&state);
                    app.exit(0);
                }
                _ => {}
            }).build(app)?;
            let handle = app.handle().clone();
            thread::spawn(move || {
                for _ in 0..200 {
                    if let Ok(text) = fs::read_to_string(&ready) {
                        if let Ok(value) = serde_json::from_str::<serde_json::Value>(&text) {
                            if let Some(port) = value.get("port").and_then(|v| v.as_u64()) {
                                let state = handle.state::<DesktopState>();
                                state.session.lock().expect("session lock").base_url =
                                    format!("http://127.0.0.1:{port}");
                                let _ = fs::remove_file(&ready);
                                break;
                            }
                        }
                    }
                    thread::sleep(Duration::from_millis(50));
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
