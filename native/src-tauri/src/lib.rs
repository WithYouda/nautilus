use nautilus_core::{
    store::Store,
    types::{Material, ProviderSettings, Snapshot, Turn},
};
use std::sync::Mutex;
use tauri::{Emitter, Manager};
use tokio::sync::watch;

struct LocalState {
    store: Mutex<Store>,
    cancel: Mutex<Option<(String, watch::Sender<bool>)>>,
}
const LOCK_ERROR: &str = "本地数据暂时不可用，请重开应用";

#[tauri::command]
fn snapshot(state: tauri::State<LocalState>) -> Result<Snapshot, String> {
    state.store.lock().map_err(|_| LOCK_ERROR)?.snapshot()
}
#[tauri::command]
fn save_settings(
    settings: ProviderSettings,
    state: tauri::State<LocalState>,
) -> Result<(), String> {
    nautilus_core::provider::validate_settings(&settings)?;
    state
        .store
        .lock()
        .map_err(|_| LOCK_ERROR)?
        .save_settings(settings)
}
#[tauri::command]
fn save_material(
    id: Option<String>,
    title: String,
    content: String,
    state: tauri::State<LocalState>,
) -> Result<Material, String> {
    state
        .store
        .lock()
        .map_err(|_| LOCK_ERROR)?
        .save_material(id, title, content)
}
#[tauri::command]
fn cancel_generation(request_id: String, state: tauri::State<LocalState>) -> Result<(), String> {
    let active = state.cancel.lock().map_err(|_| LOCK_ERROR)?;
    if let Some((id, sender)) = active.as_ref() {
        if *id == request_id {
            let _ = sender.send(true);
        }
    }
    Ok(())
}
#[tauri::command]
async fn send_message(
    request_id: String,
    question: String,
    material_ids: Vec<String>,
    api_key: String,
    state: tauri::State<'_, LocalState>,
    app: tauri::AppHandle,
) -> Result<Turn, String> {
    if question.trim().is_empty() {
        return Err("请先输入问题".into());
    }
    // Register cancellation before exposing the persisted pending turn.
    let (prepared, receiver) = {
        let mut active = state.cancel.lock().map_err(|_| LOCK_ERROR)?;
        let mut store = state.store.lock().map_err(|_| LOCK_ERROR)?;
        let settings = store.snapshot()?.settings;
        if settings.base_url.trim().is_empty() || settings.model.trim().is_empty() {
            return Err("请先保存模型服务地址和模型名称".into());
        }
        let prepared = store.begin_turn(request_id.clone(), question, material_ids)?;
        if !prepared.created {
            return Ok(prepared.turn);
        }
        let (sender, receiver) = watch::channel(false);
        *active = Some((request_id.clone(), sender));
        (prepared, receiver)
    };
    let mut turn = prepared.turn;
    let _ = app.emit("native-turn", &turn);
    let result = nautilus_core::provider::generate(
        &turn.provider.clone(),
        &api_key,
        &prepared.messages,
        receiver.clone(),
        |text, reasoning| {
            turn.answer.push_str(text);
            turn.reasoning.push_str(reasoning);
            state.store.lock().map_err(|_| LOCK_ERROR)?.update_turn(
                &turn.id,
                &turn.answer,
                &turn.reasoning,
            )?;
            let _ = app.emit("native-turn", &turn);
            Ok(())
        },
    )
    .await;
    // Serialise completion against cancellation and the next send.
    let mut active = state.cancel.lock().map_err(|_| LOCK_ERROR)?;
    let canceled = *receiver.borrow();
    turn.status = if canceled {
        "canceled"
    } else if result.is_ok() {
        "complete"
    } else {
        "failed"
    }
    .into();
    turn.error = if canceled {
        Some("已停止回答".into())
    } else {
        result.err()
    };
    state.store.lock().map_err(|_| LOCK_ERROR)?.finish_turn(
        &turn.id,
        &turn.status,
        turn.error.as_deref(),
    )?;
    *active = None;
    let _ = app.emit("native-turn", &turn);
    Ok(turn)
}
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let dir = app.path().app_data_dir()?;
            std::fs::create_dir_all(&dir)?;
            let mut store = Store::open(dir.join("native-validation.sqlite3"))
                .map_err(std::io::Error::other)?;
            store.recover().map_err(std::io::Error::other)?;
            app.manage(LocalState {
                store: Mutex::new(store),
                cancel: Mutex::new(None),
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            snapshot,
            save_settings,
            save_material,
            send_message,
            cancel_generation
        ])
        .run(tauri::generate_context!())
        .expect("无法启动 Nautilus");
}
