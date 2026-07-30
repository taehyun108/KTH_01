// PFM-Agent 데스크톱 앱 진입점.
//
// 역할
// ----
// 1. 시스템 트레이 아이콘 등록 (창을 닫아도 백그라운드 유지)
// 2. 전역 단축키 등록
//    - ESC        : 비상 정지 (백엔드에 중단 요청)
//    - Ctrl+Alt+P : 창 열기/숨기기
//
// ⚠️ 비상 정지는 백엔드(/api/agent/kill)로 전달된다.
//    앱 화면 안에서도 ESC 가 동작하므로 두 경로 모두로 중단할 수 있다.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Manager,
};

/// 백엔드 기본 주소 (포터블 원칙: 로컬 고정)
const BACKEND_URL: &str = "http://127.0.0.1:8756";

/// 백엔드에 실행 중단을 요청한다.
///
/// 화면이 응답하지 않는 상황에서도 동작해야 하므로
/// 프론트엔드를 거치지 않고 직접 호출한다.
#[tauri::command]
async fn emergency_stop() -> Result<String, String> {
    let client = reqwest::Client::new();
    match client
        .post(format!("{BACKEND_URL}/api/agent/kill"))
        .json(&serde_json::json!({ "run_id": null }))
        .send()
        .await
    {
        Ok(_) => Ok("실행을 중단했습니다.".to_string()),
        Err(error) => Err(format!("중단 요청에 실패했습니다: {error}")),
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .invoke_handler(tauri::generate_handler![emergency_stop])
        .setup(|app| {
            // --- 시스템 트레이 ---
            let show_item = MenuItem::with_id(app, "show", "PFM-Agent 열기", true, None::<&str>)?;
            let stop_item = MenuItem::with_id(app, "stop", "비상 정지", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "종료", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show_item, &stop_item, &quit_item])?;

            TrayIconBuilder::with_id("pfm-agent-tray")
                .tooltip("PFM-Agent")
                .menu(&menu)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    "stop" => {
                        // 트레이에서도 비상 정지가 가능해야 한다.
                        tauri::async_runtime::spawn(async {
                            let _ = emergency_stop().await;
                        });
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("PFM-Agent 를 시작하지 못했습니다");
}
