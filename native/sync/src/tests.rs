use super::*;
use nautilus_core::types::SyncInventory;
use std::sync::atomic::AtomicUsize;

async fn device(
    name: &str,
) -> (
    tempfile::TempDir,
    Arc<Mutex<Store>>,
    Arc<SyncService>,
    Arc<AtomicUsize>,
) {
    let dir = tempfile::tempdir().unwrap();
    let store = Arc::new(Mutex::new(
        Store::open(dir.path().join("test.sqlite3")).unwrap(),
    ));
    let calls = Arc::new(AtomicUsize::new(0));
    let copy = calls.clone();
    let service = SyncService::start(
        dir.path(),
        store.clone(),
        name,
        Arc::new(move || {
            copy.fetch_add(1, Ordering::Relaxed);
        }),
    )
    .await
    .unwrap();
    tokio::time::sleep(Duration::from_millis(150)).await;
    (dir, store, service, calls)
}
async fn until(mut predicate: impl FnMut() -> bool) {
    for _ in 0..150 {
        if predicate() {
            return;
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    assert!(predicate(), "condition did not become true");
}
async fn pair(a: &Arc<SyncService>, b: &Arc<SyncService>) {
    b.join(a.invite().unwrap()).await.unwrap();
    a.confirm(b.endpoint.id().to_string()).unwrap();
    b.confirm(a.endpoint.id().to_string()).unwrap();
    until(|| a.status().unwrap().peers.len() == 1 && b.status().unwrap().peers.len() == 1).await;
}
#[tokio::test]
async fn both_confirm_before_private_exchange_then_auto_sync_and_revoke() {
    let (_ad, as_, a, _ac) = device("Computer").await;
    let (_bd, bs, b, bc) = device("Phone").await;
    as_.lock()
        .unwrap()
        .save_material(None, "Private".into(), "Do not send before approval".into())
        .unwrap();
    let bad = a.invite().unwrap();
    let mut decoded: PairCode = serde_json::from_slice(
        &URL_SAFE_NO_PAD
            .decode(bad.strip_prefix("nautilus1:").unwrap())
            .unwrap(),
    )
    .unwrap();
    decoded.secret = "wrong".into();
    let bad = format!(
        "nautilus1:{}",
        URL_SAFE_NO_PAD.encode(serde_json::to_vec(&decoded).unwrap())
    );
    assert!(b.join(bad).await.is_err());
    b.join(a.invite().unwrap()).await.unwrap();
    let unauthorized = b
        .rpc(
            a.local_address(),
            Request::Inventory {
                pairing_id: "wrong".into(),
                known: SyncInventory::default(),
            },
        )
        .await;
    assert!(unauthorized.is_err()); // sender gates business requests before sending.
    a.confirm(b.endpoint.id().to_string()).unwrap();
    tokio::time::sleep(Duration::from_millis(300)).await;
    assert!(bs.lock().unwrap().snapshot().unwrap().materials.is_empty());
    b.confirm(a.endpoint.id().to_string()).unwrap();
    until(|| bs.lock().unwrap().snapshot().unwrap().materials.len() == 1).await;
    bs.lock()
        .unwrap()
        .save_material(None, "Phone note".into(), "Phone text".into())
        .unwrap();
    b.notify_change();
    until(|| as_.lock().unwrap().snapshot().unwrap().materials.len() == 2).await;
    assert!(bc.load(Ordering::Relaxed) > 0);
    a.unpair(b.endpoint.id().to_string()).await.unwrap();
    assert!(a.status().unwrap().peers.is_empty());
    let saved = bs.lock().unwrap().snapshot().unwrap();
    assert_eq!(saved.materials.len(), 2);
    as_.lock()
        .unwrap()
        .save_material(None, "After revocation".into(), "Keep local".into())
        .unwrap();
    a.notify_change();
    tokio::time::sleep(Duration::from_millis(400)).await;
    assert_eq!(bs.lock().unwrap().snapshot().unwrap(), saved);
    assert!(a.status().unwrap().pending.is_empty());
    a.close().await;
    b.close().await;
}
#[tokio::test]
async fn reconnect_persists_identity_and_sends_missing_objects_only() {
    let (_ad, as_, a, _) = device("A").await;
    let (bd, bs, b, _) = device("B").await;
    pair(&a, &b).await;
    let id = b.endpoint.id();
    let old_port = b
        .endpoint
        .bound_sockets()
        .into_iter()
        .find(|a| a.is_ipv4())
        .unwrap()
        .port();
    b.close().await;
    drop(b);
    tokio::time::sleep(Duration::from_millis(150)).await;
    let m = as_
        .lock()
        .unwrap()
        .save_material(None, "Offline".into(), "Written while peer closed".into())
        .unwrap();
    a.notify_change();
    let reopened = SyncService::start(
        bd.path(),
        bs.clone(),
        "Ignored existing name",
        Arc::new(|| {}),
    )
    .await
    .unwrap();
    assert_eq!(reopened.endpoint.id(), id);
    assert_eq!(
        reopened
            .endpoint
            .bound_sockets()
            .into_iter()
            .find(|a| a.is_ipv4())
            .unwrap()
            .port(),
        old_port
    );
    until(|| {
        bs.lock()
            .unwrap()
            .snapshot()
            .unwrap()
            .materials
            .iter()
            .any(|v| v.id == m.id)
    })
    .await;
    let known = bs.lock().unwrap().inventory().unwrap();
    assert!(as_
        .lock()
        .unwrap()
        .export_missing(&known)
        .unwrap()
        .material_revisions
        .is_empty());
    assert_eq!(reopened.status().unwrap().device_name, "B");
    a.close().await;
    reopened.close().await;
}
#[tokio::test]
async fn rejects_unpaired_wire_requests_and_expired_codes() {
    let (_ad, as_, a, _) = device("A").await;
    let (_cd, _cs, c, _) = device("C").await;
    as_.lock()
        .unwrap()
        .save_material(None, "Secret".into(), "Private".into())
        .unwrap();
    let connection = c.endpoint.connect(a.local_address(), ALPN).await.unwrap();
    let (mut send, mut recv) = connection.open_bi().await.unwrap();
    send.write_all(
        &serde_json::to_vec(&Request::Inventory {
            pairing_id: "forged".into(),
            known: SyncInventory::default(),
        })
        .unwrap(),
    )
    .await
    .unwrap();
    send.finish().unwrap();
    let bytes = recv.read_to_end(1024).await.unwrap();
    assert!(matches!(
        serde_json::from_slice::<Reply>(&bytes).unwrap(),
        Reply::Error(_)
    ));
    assert!(!String::from_utf8_lossy(&bytes).contains("Private"));
    let code = a.invite().unwrap();
    a.inner.lock().unwrap().invitation.as_mut().unwrap().1 =
        Instant::now() - Duration::from_secs(1);
    assert!(c.join(code).await.is_err());
    a.close().await;
    c.close().await;
}
