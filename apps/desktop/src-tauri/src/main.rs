use std::sync::Mutex;

use tauri::{Manager, RunEvent};
use tauri_plugin_shell::{process::CommandChild, ShellExt};

struct RuntimeProcess(Mutex<Option<CommandChild>>);

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let sidecar = app
                .shell()
                .sidecar("agent-man-runtime")?;
            let (mut events, child) = sidecar.spawn()?;

            tauri::async_runtime::spawn(async move {
                while events.recv().await.is_some() {
                }
            });

            app.manage(RuntimeProcess(Mutex::new(Some(child))));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build Agent Man desktop application");

    app.run(|app_handle, event| {
        if let RunEvent::ExitRequested { .. } = event {
            let runtime = app_handle.state::<RuntimeProcess>();
            if let Ok(mut guard) = runtime.0.lock() {
                if let Some(child) = guard.take() {
                    let _ = child.kill();
                }
            }
        }
    });
}
