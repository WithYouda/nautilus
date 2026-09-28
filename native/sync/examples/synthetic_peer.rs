//! Isolated peer for the Windows WebView LAN sync journey.
//! cargo run -p nautilus-sync --example synthetic_peer -- <new-empty-nautilus-sync-peer-dir> <control-port>
use nautilus_core::store::Store;
use nautilus_sync::SyncService;
use serde_json::{json, Value};
use std::{
    path::PathBuf,
    sync::{Arc, Mutex},
};
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::TcpListener,
};
use uuid::Uuid;

fn field<'a>(request: &'a Value, key: &str) -> Result<&'a str, String> {
    request
        .get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("missing {key}"))
}
fn strings(request: &Value, key: &str) -> Result<Vec<String>, String> {
    request
        .get(key)
        .and_then(Value::as_array)
        .ok_or_else(|| format!("missing {key}"))?
        .iter()
        .map(|v| {
            v.as_str()
                .map(str::to_owned)
                .ok_or_else(|| format!("invalid {key}"))
        })
        .collect()
}
fn snapshot(store: &Arc<Mutex<Store>>) -> Result<Value, String> {
    serde_json::to_value(
        store
            .lock()
            .map_err(|_| "store lock unavailable")?
            .snapshot()?,
    )
    .map_err(|error| error.to_string())
}
async fn close_service(service: &mut Option<Arc<SyncService>>) -> Result<(), String> {
    if let Some(active) = service.take() {
        let old = Arc::downgrade(&active);
        active.close().await;
        drop(active);
        // Endpoint shutdown is asynchronous. Ensure the old service and its UDP
        // socket are gone before resume reuses the persisted listening port.
        for _ in 0..100 {
            if old.upgrade().is_none() {
                return Ok(());
            }
            tokio::time::sleep(std::time::Duration::from_millis(100)).await;
        }
        return Err("paused peer transport did not finish closing".into());
    }
    Ok(())
}
async fn command(
    request: &Value,
    store: &Arc<Mutex<Store>>,
    service: &mut Option<Arc<SyncService>>,
    dir: &PathBuf,
) -> Result<Value, String> {
    match field(request, "command")? {
        "name" => {
            service
                .as_ref()
                .ok_or("peer is paused")?
                .set_name(field(request, "name")?.into())?;
            Ok(json!(null))
        }
        "status" => serde_json::to_value(service.as_ref().ok_or("peer is paused")?.status()?)
            .map_err(|error| error.to_string()),
        "invite" => Ok(json!(service.as_ref().ok_or("peer is paused")?.invite()?)),
        "join" => {
            service
                .as_ref()
                .ok_or("peer is paused")?
                .join(field(request, "code")?.into())
                .await?;
            Ok(json!(null))
        }
        "confirm" => {
            service
                .as_ref()
                .ok_or("peer is paused")?
                .confirm(field(request, "peerId")?.into())?;
            Ok(json!(null))
        }
        "unpair" => {
            service
                .as_ref()
                .ok_or("peer is paused")?
                .unpair(field(request, "peerId")?.into())
                .await?;
            Ok(json!(null))
        }
        "pause" => {
            close_service(service).await?;
            Ok(json!(null))
        }
        "resume" => {
            if service.is_none() {
                *service = Some(
                    SyncService::start(dir, store.clone(), "合成设备", Arc::new(|| {})).await?,
                );
            }
            Ok(json!(null))
        }
        "snapshot" => snapshot(store),
        "add_material" => {
            let material = store
                .lock()
                .map_err(|_| "store lock unavailable")?
                .save_material(
                    None,
                    field(request, "title")?.into(),
                    field(request, "content")?.into(),
                )?;
            if let Some(active) = service.as_ref() {
                active.notify_change();
            }
            serde_json::to_value(material).map_err(|error| error.to_string())
        }
        "edit_material" => {
            let material = store
                .lock()
                .map_err(|_| "store lock unavailable")?
                .save_material(
                    Some(field(request, "materialId")?.into()),
                    field(request, "title")?.into(),
                    field(request, "content")?.into(),
                )?;
            if let Some(active) = service.as_ref() {
                active.notify_change();
            }
            serde_json::to_value(material).map_err(|error| error.to_string())
        }
        "save_selection" => {
            store
                .lock()
                .map_err(|_| "store lock unavailable")?
                .save_selection(strings(request, "materialIds")?)?;
            if let Some(active) = service.as_ref() {
                active.notify_change();
            }
            Ok(json!(null))
        }
        "create_completed_turn" => {
            let material_ids = strings(request, "materialIds")?;
            let parent = request
                .get("parentId")
                .and_then(Value::as_str)
                .map(str::to_owned);
            let request_id = Uuid::new_v4().to_string();
            let id = {
                let mut data = store.lock().map_err(|_| "store lock unavailable")?;
                data.save_selection(material_ids.clone())?;
                let prepared = data.begin_turn(
                    request_id,
                    field(request, "question")?.into(),
                    material_ids,
                    parent,
                )?;
                data.update_turn(&prepared.turn.id, field(request, "answer")?, "")?;
                data.finish_turn(&prepared.turn.id, "complete", None)?;
                prepared.turn.id
            };
            if let Some(active) = service.as_ref() {
                active.notify_change();
            }
            Ok(json!(id))
        }
        "stop" => {
            close_service(service).await?;
            Ok(json!("stopped"))
        }
        _ => Err("unknown command".into()),
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args().skip(1);
    let dir = PathBuf::from(args.next().ok_or("provide empty peer directory")?);
    let port: u16 = args.next().ok_or("provide control port")?.parse()?;
    if args.next().is_some()
        || !dir
            .file_name()
            .and_then(|s| s.to_str())
            .is_some_and(|s| s.starts_with("nautilus-sync-peer-"))
    {
        return Err("use an empty directory named nautilus-sync-peer-* and a port".into());
    }
    if dir.exists() {
        if dir.read_dir()?.next().is_some() {
            return Err("peer directory must be empty".into());
        }
    } else {
        std::fs::create_dir_all(&dir)?;
    }
    let store = Arc::new(Mutex::new(Store::open(dir.join("peer.sqlite3"))?));
    let mut service =
        Some(SyncService::start(&dir, store.clone(), "合成设备", Arc::new(|| {})).await?);
    let listener = TcpListener::bind(("0.0.0.0", port)).await?;
    let token = Uuid::new_v4().to_string();
    println!(
        "{}",
        json!({"ready": true, "controlPort": listener.local_addr()?.port(), "controlToken": token})
    );
    loop {
        let (stream, _) = listener.accept().await?;
        let (reader, mut writer) = stream.into_split();
        let mut reader = BufReader::new(reader);
        let mut line = String::new();
        reader.read_line(&mut line).await?;
        let mut requested_stop = false;
        let response = match serde_json::from_str::<Value>(&line) {
            Ok(request) if request.get("token").and_then(Value::as_str) == Some(token.as_str()) => {
                requested_stop = request.get("command").and_then(Value::as_str) == Some("stop");
                match command(&request, &store, &mut service, &dir).await {
                    Ok(value) => json!({"ok": true, "value": value}),
                    Err(error) => json!({"ok": false, "error": error}),
                }
            }
            _ => json!({"ok": false, "error": "invalid control request"}),
        };
        writer.write_all(format!("{response}\n").as_bytes()).await?;
        if requested_stop && response.get("ok") == Some(&json!(true)) {
            break;
        }
    }
    Ok(())
}
