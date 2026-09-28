mod credentials;
use nautilus_core::{
    store::Store,
    types::{Material, ProviderSettings, Snapshot, Turn},
};
use nautilus_sync::SyncService;
use serde::Serialize;
use std::{
    path::PathBuf,
    sync::{Arc, Mutex},
};
use tauri::{Emitter, Manager};
use tokio::sync::watch;

struct LocalState {
    store: Mutex<Option<Arc<Mutex<Store>>>>,
    sync: Mutex<Option<Arc<SyncService>>>,
    sync_error: Mutex<Option<String>>,
    initial_error: Mutex<Option<String>>,
    needs_upgrade: Mutex<bool>,
    path: PathBuf,
    credential_lock: tokio::sync::Mutex<()>,
    upgrade_lock: tokio::sync::Mutex<()>,
    network_lock: tokio::sync::Mutex<()>,
    cancel: Mutex<Option<(String, watch::Sender<bool>)>>,
}
const LOCK_ERROR: &str = "本地数据暂时不可用，请重开应用";
impl LocalState {
    fn store(&self) -> Result<Arc<Mutex<Store>>, String> {
        self.store
            .lock()
            .map_err(|_| LOCK_ERROR)?
            .clone()
            .ok_or_else(|| "请先备份并升级本机数据".into())
    }
    fn sync(&self) -> Result<Arc<SyncService>, String> {
        self.sync
            .lock()
            .map_err(|_| LOCK_ERROR)?
            .clone()
            .ok_or_else(|| "局域网连接仍在启动，请稍后重试".into())
    }
    fn changed(&self) {
        if let Ok(Some(sync)) = self.sync.lock().map(|s| s.clone()) {
            sync.notify_change();
        }
    }
}
fn with_store<T>(
    state: &LocalState,
    action: impl FnOnce(&mut Store) -> Result<T, String>,
) -> Result<T, String> {
    let store = state.store()?;
    let mut store = store.lock().map_err(|_| LOCK_ERROR)?;
    action(&mut store)
}
fn same_ids(mut a: Vec<String>, mut b: Vec<String>) -> bool {
    a.sort();
    b.sort();
    a == b
}
const STALE: &str = "另一台设备已更新相关内容，请核对最新状态后重新操作；输入内容仍保留。";
#[derive(Serialize)]
struct LocalStatus {
    needs_upgrade: bool,
    error: Option<String>,
}
#[tauri::command]
fn local_status(state: tauri::State<LocalState>) -> Result<LocalStatus, String> {
    Ok(LocalStatus {
        needs_upgrade: *state.needs_upgrade.lock().map_err(|_| LOCK_ERROR)?,
        error: state.initial_error.lock().map_err(|_| LOCK_ERROR)?.clone(),
    })
}
#[tauri::command]
fn snapshot(state: tauri::State<LocalState>) -> Result<Snapshot, String> {
    with_store(&state, |s| s.snapshot())
}
#[tauri::command]
async fn credential_status(
    base_url: String,
    state: tauri::State<'_, LocalState>,
) -> Result<bool, String> {
    let scope = credentials::scope(&base_url)?;
    let _guard = state.credential_lock.lock().await;
    credentials::exists(state.path.parent().ok_or(LOCK_ERROR)?, &scope)
}
#[tauri::command]
async fn save_credential(
    base_url: String,
    key: String,
    state: tauri::State<'_, LocalState>,
    app: tauri::AppHandle,
) -> Result<(), String> {
    let scope = credentials::scope(&base_url)?;
    let _guard = state.credential_lock.lock().await;
    credentials::save(&app, state.path.parent().ok_or(LOCK_ERROR)?, &scope, &key).await
}
#[tauri::command]
async fn delete_credential(
    base_url: String,
    state: tauri::State<'_, LocalState>,
) -> Result<(), String> {
    let scope = credentials::scope(&base_url)?;
    let _guard = state.credential_lock.lock().await;
    credentials::delete(state.path.parent().ok_or(LOCK_ERROR)?, &scope)
}
#[tauri::command]
fn save_settings(
    settings: ProviderSettings,
    state: tauri::State<LocalState>,
) -> Result<(), String> {
    nautilus_core::provider::validate_settings(&settings)?;
    with_store(&state, |s| s.save_settings(settings))
}
#[tauri::command]
fn save_material(
    id: Option<String>,
    title: String,
    content: String,
    expected_revision_id: Option<String>,
    state: tauri::State<LocalState>,
) -> Result<Material, String> {
    let saved = with_store(&state, |s| {
        if let Some(id) = &id {
            let snap = s.snapshot()?;
            let current = snap
                .materials
                .iter()
                .find(|m| &m.id == id)
                .map(|m| m.revision_id.clone());
            if current.is_none() || current != expected_revision_id {
                return Err(STALE.into());
            }
        }
        s.save_material(id, title, content)
    })?;
    state.changed();
    Ok(saved)
}
#[tauri::command]
fn save_selection(
    material_ids: Vec<String>,
    expected_selection_ids: Vec<String>,
    state: tauri::State<LocalState>,
) -> Result<(), String> {
    with_store(&state, |s| {
        if !same_ids(
            s.snapshot()?
                .selection_heads
                .into_iter()
                .map(|h| h.id)
                .collect(),
            expected_selection_ids,
        ) {
            return Err(STALE.into());
        }
        s.save_selection(material_ids)
    })?;
    state.changed();
    Ok(())
}
#[tauri::command]
fn resolve_selection(
    chosen_revision_id: String,
    expected_head_ids: Vec<String>,
    state: tauri::State<LocalState>,
) -> Result<(), String> {
    with_store(&state, |s| {
        if !same_ids(
            s.snapshot()?
                .selection_heads
                .into_iter()
                .map(|h| h.id)
                .collect(),
            expected_head_ids,
        ) {
            return Err(STALE.into());
        }
        s.resolve_selection(&chosen_revision_id)
    })?;
    state.changed();
    Ok(())
}
#[tauri::command]
fn resolve_material(
    material_id: String,
    chosen_revision_id: String,
    expected_head_ids: Vec<String>,
    state: tauri::State<LocalState>,
) -> Result<Material, String> {
    let result = with_store(&state, |s| {
        let snap = s.snapshot()?;
        let heads = snap
            .material_conflicts
            .iter()
            .find(|c| c.material_id == material_id)
            .map(|c| c.versions.iter().map(|v| v.revision_id.clone()).collect())
            .unwrap_or_default();
        if !same_ids(heads, expected_head_ids) {
            return Err(STALE.into());
        }
        s.resolve_material(&material_id, &chosen_revision_id)
    })?;
    state.changed();
    Ok(result)
}
#[tauri::command]
fn sync_status(state: tauri::State<LocalState>) -> Result<nautilus_sync::SyncStatus, String> {
    if let Some(error) = state.sync_error.lock().map_err(|_| LOCK_ERROR)?.clone() {
        return Err(error);
    }
    match state.sync.lock().map_err(|_| LOCK_ERROR)?.clone() {
        Some(sync) => sync.status(),
        None => Ok(nautilus_sync::SyncStatus {
            device_name: default_device_name().into(),
            invitation: None,
            peers: vec![],
            pending: vec![],
        }),
    }
}
#[tauri::command]
fn sync_set_name(name: String, state: tauri::State<LocalState>) -> Result<(), String> {
    state.sync()?.set_name(name)
}
#[tauri::command]
fn sync_invite(state: tauri::State<LocalState>) -> Result<String, String> {
    state.sync()?.invite()
}
#[tauri::command]
async fn sync_join(code: String, state: tauri::State<'_, LocalState>) -> Result<(), String> {
    state.sync()?.join(code).await
}
#[tauri::command]
fn sync_confirm(peer_id: String, state: tauri::State<LocalState>) -> Result<(), String> {
    state.sync()?.confirm(peer_id)
}
#[tauri::command]
async fn sync_reject(peer_id: String, state: tauri::State<'_, LocalState>) -> Result<(), String> {
    state.sync()?.reject(peer_id).await
}
#[tauri::command]
async fn sync_unpair(peer_id: String, state: tauri::State<'_, LocalState>) -> Result<(), String> {
    state.sync()?.unpair(peer_id).await
}
fn default_device_name() -> &'static str {
    if cfg!(target_os = "android") {
        "我的手机"
    } else {
        "我的电脑"
    }
}
async fn start_sync(app: tauri::AppHandle) {
    let state = app.state::<LocalState>();
    let _network_guard = state.network_lock.lock().await;
    if state.sync.lock().map(|s| s.is_some()).unwrap_or(true) {
        return;
    }
    let Ok(store) = state.store() else {
        return;
    };
    let event_app = app.clone();
    match SyncService::start(
        state.path.parent().expect("app directory"),
        store,
        default_device_name(),
        Arc::new(move || {
            let _ = event_app.emit("native-sync", ());
        }),
    )
    .await
    {
        Ok(sync) => {
            if let Ok(mut error) = state.sync_error.lock() {
                *error = None;
            }
            if let Ok(mut holder) = state.sync.lock() {
                *holder = Some(sync);
            }
        }
        Err(error) => {
            if let Ok(mut holder) = state.sync_error.lock() {
                *holder = Some(error);
            }
        }
    }
    let _ = app.emit("native-sync", ());
}
#[tauri::command]
async fn sync_restart(
    app: tauri::AppHandle,
    state: tauri::State<'_, LocalState>,
) -> Result<(), String> {
    start_sync(app).await;
    if let Some(error) = state.sync_error.lock().map_err(|_| LOCK_ERROR)?.clone() {
        return Err(error);
    }
    state.sync()?.notify_change();
    Ok(())
}
#[tauri::command]
async fn upgrade_local_data(
    state: tauri::State<'_, LocalState>,
    app: tauri::AppHandle,
) -> Result<String, String> {
    let _guard = state.upgrade_lock.lock().await;
    if !*state.needs_upgrade.lock().map_err(|_| LOCK_ERROR)? {
        return Err("本机数据不需要升级".into());
    }
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|_| "无法读取时间")?
        .as_nanos();
    let backup = state
        .path
        .with_file_name(format!("native-before-sync-{stamp}.sqlite3"));
    {
        let db = rusqlite::Connection::open_with_flags(
            &state.path,
            rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
        )
        .map_err(|_| "无法读取旧数据")?;
        let result: String = db
            .query_row("PRAGMA integrity_check", [], |r| r.get(0))
            .map_err(|_| "旧数据完整性检查失败")?;
        if result != "ok" {
            return Err("旧数据完整性检查失败，尚未升级".into());
        }
        db.backup(rusqlite::MAIN_DB, &backup, None)
            .map_err(|_| "备份失败，尚未升级")?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&backup, std::fs::Permissions::from_mode(0o600))
                .map_err(|_| "无法设置备份权限，尚未升级")?;
        }
        let checked = rusqlite::Connection::open_with_flags(
            &backup,
            rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
        )
        .map_err(|_| "备份无法读取，尚未升级")?;
        let result: String = checked
            .query_row("PRAGMA integrity_check", [], |r| r.get(0))
            .map_err(|_| "备份检查失败，尚未升级")?;
        if result != "ok" {
            return Err("备份检查失败，尚未升级".into());
        }
    }
    Store::upgrade_v1(&state.path)?;
    let mut store = Store::open(&state.path)?;
    store.recover()?;
    *state.store.lock().map_err(|_| LOCK_ERROR)? = Some(Arc::new(Mutex::new(store)));
    *state.needs_upgrade.lock().map_err(|_| LOCK_ERROR)? = false;
    *state.initial_error.lock().map_err(|_| LOCK_ERROR)? = None;
    start_sync(app).await;
    Ok(backup.to_string_lossy().into_owned())
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
    expected_base_url: String,
    parent_id: Option<String>,
    expected_selection_ids: Vec<String>,
    expected_revision_ids: Vec<String>,
    state: tauri::State<'_, LocalState>,
    app: tauri::AppHandle,
) -> Result<Turn, String> {
    if question.trim().is_empty() {
        return Err("请先输入问题".into());
    }
    let settings = with_store(&state, |s| Ok(s.snapshot()?.settings))?;
    if settings.base_url != expected_base_url {
        return Err("模型接口地址已变化，请核对后重新发送".into());
    }
    let scope = credentials::scope(&settings.base_url)?;
    let api_key = if api_key.is_empty() {
        let _guard = state.credential_lock.lock().await;
        credentials::load(&app, state.path.parent().ok_or(LOCK_ERROR)?, &scope)
            .await?
            .unwrap_or_default()
    } else {
        api_key
    };
    // Register cancellation before exposing the persisted pending turn.
    let (prepared, receiver) = {
        let mut active = state.cancel.lock().map_err(|_| LOCK_ERROR)?;
        let shared_store = state.store()?;
        let mut store = shared_store.lock().map_err(|_| LOCK_ERROR)?;
        if store.snapshot()?.settings != settings {
            return Err("模型设置已变化，请核对后重新发送".into());
        }
        if settings.base_url.trim().is_empty() || settings.model.trim().is_empty() {
            return Err("请先保存模型服务地址和模型名称".into());
        }
        let current = store.snapshot()?;
        if !same_ids(
            current
                .selection_heads
                .iter()
                .map(|h| h.id.clone())
                .collect(),
            expected_selection_ids,
        ) {
            return Err(STALE.into());
        }
        let actual: Vec<String> = material_ids
            .iter()
            .filter_map(|id| {
                current
                    .materials
                    .iter()
                    .find(|m| &m.id == id)
                    .map(|m| m.revision_id.clone())
            })
            .collect();
        if actual.len() != material_ids.len() || !same_ids(actual, expected_revision_ids) {
            return Err(STALE.into());
        }
        let prepared = store.begin_turn(request_id.clone(), question, material_ids, parent_id)?;
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
            state.store()?.lock().map_err(|_| LOCK_ERROR)?.update_turn(
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
    state.store()?.lock().map_err(|_| LOCK_ERROR)?.finish_turn(
        &turn.id,
        &turn.status,
        turn.error.as_deref(),
    )?;
    *active = None;
    state.changed();
    let _ = app.emit("native-turn", &turn);
    Ok(turn)
}
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default();
    #[cfg(target_os = "android")]
    let builder = builder.plugin(credentials::plugin());
    #[cfg(target_os = "windows")]
    let builder = builder.plugin(tauri_plugin_single_instance::init(|app, _, _| {
        if let Some(window) = app.get_webview_window("main") {
            let _ = window.show();
            let _ = window.unminimize();
            let _ = window.set_focus();
        }
    }));
    builder
        .setup(|app| {
            #[cfg(target_os = "windows")]
            let dir = match std::env::var_os("NAUTILUS_VALIDATION_DATA_DIR") {
                Some(path) => std::path::PathBuf::from(path),
                None => app.path().app_local_data_dir()?,
            };
            #[cfg(not(target_os = "windows"))]
            let dir = app.path().app_data_dir()?;
            std::fs::create_dir_all(&dir)?;
            let path = dir.join("native-validation.sqlite3");
            let mut initial_error = None;
            let mut needs_upgrade = false;
            let store = match Store::open(&path) {
                Ok(mut store) => {
                    store.recover().map_err(std::io::Error::other)?;
                    Some(Arc::new(Mutex::new(store)))
                }
                Err(error) => {
                    let version = rusqlite::Connection::open_with_flags(
                        &path,
                        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
                    )
                    .ok()
                    .and_then(|db| {
                        db.query_row("PRAGMA user_version", [], |r| r.get::<_, i64>(0))
                            .ok()
                    });
                    needs_upgrade = version == Some(1);
                    if !needs_upgrade {
                        initial_error = Some(error);
                    }
                    None
                }
            };
            app.manage(LocalState {
                store: Mutex::new(store),
                sync: Mutex::new(None),
                sync_error: Mutex::new(None),
                initial_error: Mutex::new(initial_error),
                needs_upgrade: Mutex::new(needs_upgrade),
                path,
                credential_lock: tokio::sync::Mutex::new(()),
                upgrade_lock: tokio::sync::Mutex::new(()),
                network_lock: tokio::sync::Mutex::new(()),
                cancel: Mutex::new(None),
            });
            tauri::async_runtime::spawn(start_sync(app.handle().clone()));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            snapshot,
            credential_status,
            save_credential,
            delete_credential,
            save_settings,
            save_material,
            send_message,
            cancel_generation,
            local_status,
            upgrade_local_data,
            save_selection,
            resolve_selection,
            resolve_material,
            sync_status,
            sync_restart,
            sync_set_name,
            sync_invite,
            sync_join,
            sync_confirm,
            sync_reject,
            sync_unpair
        ])
        .run(tauri::generate_context!())
        .expect("无法启动 Nautilus");
}
