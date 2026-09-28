//! LAN-only transport. Device authentication is provided by iroh's pinned public keys;
//! application pairing is a separate, bilateral authorization before any store access.
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use iroh::{Endpoint, EndpointAddr, SecretKey};
use nautilus_core::{
    store::Store,
    types::{SyncBatch, SyncInventory},
};
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant},
};
use tokio::sync::Notify;
use uuid::Uuid;

const ALPN: &[u8] = b"nautilus-local-sync/1";
const LOCK: &str = "设备连接状态暂时不可用";
const NETWORK: &str = "尚未连上；请保持两端应用打开，并确认连接同一网络";
const PAIR_TIME: Duration = Duration::from_secs(600);

#[derive(Clone, Serialize, Deserialize)]
struct Peer {
    id: String,
    name: String,
    address: EndpointAddr,
    pairing_id: String,
}
#[derive(Clone, Serialize, Deserialize)]
struct Config {
    secret: [u8; 32],
    #[serde(default)]
    port: u16,
    name: String,
    peers: Vec<Peer>,
}
#[derive(Clone)]
struct Pending {
    peer: Peer,
    local: bool,
    remote: bool,
    expires: Instant,
}
struct Inner {
    config: Config,
    invitation: Option<(String, Instant)>,
    pending: BTreeMap<String, Pending>,
    statuses: BTreeMap<String, String>,
}
#[derive(Clone, Serialize)]
pub struct PeerStatus {
    pub id: String,
    pub name: String,
    pub status: String,
}
#[derive(Clone, Serialize)]
pub struct PairRequest {
    pub id: String,
    pub name: String,
    pub confirmed: bool,
}
#[derive(Clone, Serialize)]
pub struct SyncStatus {
    pub device_name: String,
    pub invitation: Option<String>,
    pub peers: Vec<PeerStatus>,
    pub pending: Vec<PairRequest>,
}
#[derive(Serialize, Deserialize)]
struct PairCode {
    protocol: u32,
    address: EndpointAddr,
    secret: String,
}
#[derive(Serialize, Deserialize)]
enum Request {
    Hello {
        secret: String,
        name: String,
        address: EndpointAddr,
    },
    Confirm {
        pairing_id: String,
    },
    Reject {
        pairing_id: String,
    },
    Inventory {
        pairing_id: String,
        known: SyncInventory,
    },
    Push {
        pairing_id: String,
        batch: SyncBatch,
    },
    Revoke {
        pairing_id: String,
    },
}
#[derive(Serialize, Deserialize)]
enum Reply {
    Hello {
        name: String,
        pairing_id: String,
        address: EndpointAddr,
    },
    Confirm {
        confirmed: bool,
    },
    Data {
        known: SyncInventory,
        batch: SyncBatch,
    },
    Ok,
    Error(String),
}

pub struct SyncService {
    endpoint: Endpoint,
    store: Arc<Mutex<Store>>,
    path: PathBuf,
    inner: Mutex<Inner>,
    wake: Notify,
    connections: Mutex<Vec<(String, iroh::endpoint::WeakConnectionHandle)>>,
    stopped: AtomicBool,
    changed: Arc<dyn Fn() + Send + Sync>,
}

impl SyncService {
    pub async fn start(
        dir: &Path,
        store: Arc<Mutex<Store>>,
        name: &str,
        changed: Arc<dyn Fn() + Send + Sync>,
    ) -> Result<Arc<Self>, String> {
        let path = dir.join("paired-devices.json");
        let mut config: Config = if path.exists() {
            serde_json::from_slice(&std::fs::read(&path).map_err(|_| "无法读取设备身份")?)
                .map_err(|_| "设备身份文件无法读取，请勿删除后重新同步")?
        } else {
            let c = Config {
                secret: SecretKey::generate().to_bytes(),
                port: 0,
                name: name.into(),
                peers: vec![],
            };
            persist(&path, &c)?;
            c
        };
        // Minimal only supplies cryptography. Explicitly disable public networking helpers.
        let builder = iroh::endpoint::Builder::empty()
            .preset(iroh::endpoint::presets::Minimal)
            .relay_mode(iroh::RelayMode::Disabled)
            .secret_key(SecretKey::from_bytes(&config.secret))
            .alpns(vec![ALPN.to_vec()])
            .portmapper_config(iroh::endpoint::PortmapperConfig::Disabled)
            .net_report_config(iroh::endpoint::NetReportConfig::minimal())
            .address_lookup(
                iroh_mdns_address_lookup::MdnsAddressLookup::builder().addr_filter(
                    iroh::address_lookup::AddrFilter::new(|addrs| {
                        std::borrow::Cow::Owned(
                            addrs
                                .iter()
                                .filter(|a| is_lan_transport(a))
                                .cloned()
                                .collect(),
                        )
                    }),
                ),
            )
            .bind_addr(std::net::SocketAddr::from(([0, 0, 0, 0], config.port)))
            .map_err(|_| "无法配置本机连接端口")?;
        let endpoint = builder.bind().await.map_err(|error| {
            #[cfg(test)]
            eprintln!("LAN bind: {error:?}");
            let _ = error;
            "无法启动局域网连接，请检查网络权限"
        })?;
        let port = endpoint
            .bound_sockets()
            .iter()
            .find(|a| a.is_ipv4())
            .ok_or("没有可用的本机IPv4连接")?
            .port();
        if config.port != port {
            config.port = port;
            persist(&path, &config)?;
        }
        let service = Arc::new(Self {
            endpoint,
            store,
            path,
            inner: Mutex::new(Inner {
                config,
                invitation: None,
                pending: BTreeMap::new(),
                statuses: BTreeMap::new(),
            }),
            wake: Notify::new(),
            connections: Mutex::new(vec![]),
            stopped: AtomicBool::new(false),
            changed,
        });
        let runner = service.clone();
        tokio::spawn(async move {
            while let Some(incoming) = runner.endpoint.accept().await {
                let task = runner.clone();
                tokio::spawn(async move {
                    if let Ok(connection) = incoming.await {
                        let peer_id = connection.remote_id().to_string();
                        task.track(&peer_id, &connection);
                        while let Ok((mut send, mut recv)) = connection.accept_bi().await {
                            let paired = task
                                .inner
                                .lock()
                                .map(|s| s.config.peers.iter().any(|p| p.id == peer_id))
                                .unwrap_or(false);
                            // Only unauthenticated pairing metadata has an envelope bound. Synced
                            // materials and answers have no artificial body/file/count limit.
                            let limit = if paired { usize::MAX } else { 64 * 1024 };
                            let bytes = if paired {
                                recv.read_to_end(limit).await.ok()
                            } else {
                                tokio::time::timeout(
                                    Duration::from_secs(10),
                                    recv.read_to_end(limit),
                                )
                                .await
                                .ok()
                                .and_then(Result::ok)
                            };
                            let reply = match bytes
                                .and_then(|b| serde_json::from_slice::<Request>(&b).ok())
                            {
                                Some(request) => task.handle(&peer_id, request),
                                None => Reply::Error("无法读取设备请求".into()),
                            };
                            if let Ok(bytes) = serde_json::to_vec(&reply) {
                                let _ = send.write_all(&bytes).await;
                                let _ = send.finish();
                            }
                        }
                    }
                });
            }
        });
        let runner = service.clone();
        tokio::spawn(async move {
            while !runner.stopped.load(Ordering::Relaxed) {
                runner.tick().await;
                tokio::select! { _ = runner.wake.notified() => {}, _ = tokio::time::sleep(Duration::from_secs(3)) => {} }
            }
        });
        Ok(service)
    }

    pub fn status(&self) -> Result<SyncStatus, String> {
        let mut inner = self.inner.lock().map_err(|_| LOCK)?;
        inner.pending.retain(|_, p| p.expires > Instant::now());
        if inner
            .invitation
            .as_ref()
            .is_some_and(|(_, end)| *end <= Instant::now())
        {
            inner.invitation = None;
        }
        let invitation = inner
            .invitation
            .as_ref()
            .map(|(secret, _)| self.encode_code(secret))
            .transpose()?;
        Ok(SyncStatus {
            device_name: inner.config.name.clone(),
            invitation,
            peers: inner
                .config
                .peers
                .iter()
                .map(|p| PeerStatus {
                    id: p.id.clone(),
                    name: p.name.clone(),
                    status: inner
                        .statuses
                        .get(&p.id)
                        .cloned()
                        .unwrap_or_else(|| "等待连接".into()),
                })
                .collect(),
            pending: inner
                .pending
                .values()
                .map(|p| PairRequest {
                    id: p.peer.id.clone(),
                    name: p.peer.name.clone(),
                    confirmed: p.local,
                })
                .collect(),
        })
    }
    pub fn set_name(&self, name: String) -> Result<(), String> {
        if name.trim().is_empty() {
            return Err("请填写设备名称".into());
        }
        let mut inner = self.inner.lock().map_err(|_| LOCK)?;
        let mut next = inner.config.clone();
        next.name = name.trim().into();
        persist(&self.path, &next)?;
        inner.config = next;
        drop(inner);
        (self.changed)();
        Ok(())
    }
    fn local_address(&self) -> EndpointAddr {
        let mut address = self.endpoint.addr();
        address.addrs.retain(is_lan_transport);
        address
    }
    fn encode_code(&self, secret: &str) -> Result<String, String> {
        let code = PairCode {
            protocol: 1,
            address: self.local_address(),
            secret: secret.into(),
        };
        Ok(format!(
            "nautilus1:{}",
            URL_SAFE_NO_PAD.encode(serde_json::to_vec(&code).map_err(|_| "无法生成配对码")?)
        ))
    }
    pub fn invite(&self) -> Result<String, String> {
        let secret = format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple());
        let code = self.encode_code(&secret)?;
        self.inner.lock().map_err(|_| LOCK)?.invitation =
            Some((secret, Instant::now() + PAIR_TIME));
        (self.changed)();
        Ok(code)
    }
    pub async fn join(&self, text: String) -> Result<(), String> {
        let code: PairCode = serde_json::from_slice(
            &URL_SAFE_NO_PAD
                .decode(
                    text.trim()
                        .strip_prefix("nautilus1:")
                        .ok_or("配对码格式不正确")?,
                )
                .map_err(|_| "配对码格式不正确")?,
        )
        .map_err(|_| "配对码格式不正确")?;
        if code.protocol != 1 {
            return Err("两端版本不兼容，请更新应用".into());
        }
        if code.address.id == self.endpoint.id() {
            return Err("不能与本设备配对".into());
        }
        ensure_lan_address(&code.address)?;
        let id = code.address.id.to_string();
        let name = {
            let inner = self.inner.lock().map_err(|_| LOCK)?;
            if inner.config.peers.iter().any(|p| p.id == id) {
                return Err("这台设备已配对".into());
            }
            inner.config.name.clone()
        };
        let reply = self
            .rpc(
                code.address,
                Request::Hello {
                    secret: code.secret,
                    name,
                    address: self.local_address(),
                },
            )
            .await?;
        match reply {
            Reply::Hello {
                name,
                pairing_id,
                address,
            } if address.id.to_string() == id => {
                ensure_lan_address(&address)?;
                let mut inner = self.inner.lock().map_err(|_| LOCK)?;
                inner.pending.insert(
                    id.clone(),
                    Pending {
                        peer: Peer {
                            id,
                            name,
                            address,
                            pairing_id,
                        },
                        local: false,
                        remote: false,
                        expires: Instant::now() + PAIR_TIME,
                    },
                );
                drop(inner);
                (self.changed)();
                Ok(())
            }
            Reply::Error(error) => Err(error),
            _ => Err("配对响应不正确".into()),
        }
    }
    pub fn confirm(&self, peer_id: String) -> Result<(), String> {
        let mut inner = self.inner.lock().map_err(|_| LOCK)?;
        let pending = inner
            .pending
            .get_mut(&peer_id)
            .ok_or("配对请求已失效，请重新输入配对码")?;
        if pending.expires <= Instant::now() {
            return Err("配对请求已过期".into());
        }
        pending.local = true;
        drop(inner);
        self.wake.notify_one();
        (self.changed)();
        Ok(())
    }
    pub async fn reject(&self, peer_id: String) -> Result<(), String> {
        let pending = self
            .inner
            .lock()
            .map_err(|_| LOCK)?
            .pending
            .remove(&peer_id);
        (self.changed)();
        if let Some(p) = pending {
            let _ = self
                .rpc(
                    p.peer.address,
                    Request::Reject {
                        pairing_id: p.peer.pairing_id,
                    },
                )
                .await;
        }
        Ok(())
    }
    pub async fn unpair(&self, peer_id: String) -> Result<(), String> {
        let peer = {
            let mut inner = self.inner.lock().map_err(|_| LOCK)?;
            let peer = inner
                .config
                .peers
                .iter()
                .find(|p| p.id == peer_id)
                .cloned()
                .ok_or("设备已解除配对")?;
            remove_peer(&self.path, &mut inner, &peer_id)?;
            self.disconnect(&peer_id);
            peer
        };
        (self.changed)();
        let _ = self
            .rpc(
                peer.address,
                Request::Revoke {
                    pairing_id: peer.pairing_id,
                },
            )
            .await;
        Ok(())
    }
    pub fn notify_change(&self) {
        self.wake.notify_one();
        (self.changed)();
    }
    pub async fn close(&self) {
        self.stopped.store(true, Ordering::Relaxed);
        self.wake.notify_one();
        self.endpoint.close().await;
    }

    fn handle(&self, remote: &str, request: Request) -> Reply {
        match self.handle_result(remote, request) {
            Ok(reply) => reply,
            Err(error) => Reply::Error(error),
        }
    }
    fn handle_result(&self, remote: &str, request: Request) -> Result<Reply, String> {
        let mut inner = self.inner.lock().map_err(|_| LOCK)?;
        let mut notify = true;
        let reply = match request {
            Request::Hello {
                secret,
                name,
                address,
            } => {
                ensure_lan_address(&address)?;
                if address.id.to_string() != remote || name.trim().is_empty() {
                    return Err("设备身份不匹配".into());
                }
                if inner.config.peers.iter().any(|p| p.id == remote) {
                    return Err("设备已配对".into());
                }
                let valid = inner
                    .invitation
                    .as_ref()
                    .is_some_and(|(expected, expires)| {
                        *expires > Instant::now() && *expected == secret
                    });
                if !valid {
                    return Err("配对码无效或已过期，请重新生成".into());
                }
                inner.invitation = None;
                let pairing_id = Uuid::new_v4().to_string();
                inner.pending.insert(
                    remote.into(),
                    Pending {
                        peer: Peer {
                            id: remote.into(),
                            name,
                            address,
                            pairing_id: pairing_id.clone(),
                        },
                        local: false,
                        remote: false,
                        expires: Instant::now() + PAIR_TIME,
                    },
                );
                Reply::Hello {
                    name: inner.config.name.clone(),
                    pairing_id,
                    address: self.local_address(),
                }
            }
            Request::Confirm { pairing_id } => {
                if inner
                    .config
                    .peers
                    .iter()
                    .any(|p| p.id == remote && p.pairing_id == pairing_id)
                {
                    return Ok(Reply::Confirm { confirmed: true });
                }
                let p = inner.pending.get_mut(remote).ok_or("配对请求已失效")?;
                if p.peer.pairing_id != pairing_id || p.expires <= Instant::now() {
                    return Err("配对请求已失效".into());
                }
                p.remote = true;
                let confirmed = p.local;
                if confirmed {
                    activate(&self.path, &mut inner, remote)?;
                }
                Reply::Confirm { confirmed }
            }
            Request::Reject { pairing_id } => {
                if inner
                    .pending
                    .get(remote)
                    .is_some_and(|p| p.peer.pairing_id == pairing_id)
                {
                    inner.pending.remove(remote);
                }
                Reply::Ok
            }
            Request::Inventory { pairing_id, known } => {
                notify = false;
                authorize(&inner, remote, &pairing_id)?;
                let store = self.store.lock().map_err(|_| LOCK)?;
                Reply::Data {
                    known: store.inventory()?,
                    batch: store.export_missing(&known)?,
                }
            }
            Request::Push { pairing_id, batch } => {
                authorize(&inner, remote, &pairing_id)?;
                notify = self.store.lock().map_err(|_| LOCK)?.import_batch(&batch)?;
                inner.statuses.insert(remote.into(), "已同步".into());
                Reply::Ok
            }
            Request::Revoke { pairing_id } => {
                authorize(&inner, remote, &pairing_id)?;
                remove_peer(&self.path, &mut inner, remote)?;
                self.disconnect(remote);
                Reply::Ok
            }
        };
        drop(inner);
        if notify {
            (self.changed)();
            self.wake.notify_one();
        }
        Ok(reply)
    }
    async fn rpc(&self, address: EndpointAddr, request: Request) -> Result<Reply, String> {
        ensure_lan_address(&address)?;
        let connection =
            tokio::time::timeout(Duration::from_secs(5), self.endpoint.connect(address, ALPN))
                .await
                .map_err(|_| NETWORK)?
                .map_err(|_| NETWORK)?;
        {
            let inner = self.inner.lock().map_err(|_| LOCK)?;
            if let Request::Inventory { pairing_id, .. } | Request::Push { pairing_id, .. } =
                &request
            {
                authorize(&inner, &connection.remote_id().to_string(), pairing_id)?;
            }
            self.track(&connection.remote_id().to_string(), &connection);
        }
        let (mut send, mut recv) = connection.open_bi().await.map_err(|_| NETWORK)?;
        send.write_all(&serde_json::to_vec(&request).map_err(|_| "设备请求编码失败")?)
            .await
            .map_err(|_| NETWORK)?;
        send.finish().map_err(|_| NETWORK)?;
        let bytes = recv.read_to_end(usize::MAX).await.map_err(|_| NETWORK)?;
        let reply = serde_json::from_slice(&bytes).map_err(|_| "两端同步协议不兼容")?;
        // Do not close until response bytes are fully received.
        connection.close(0u32.into(), b"done");
        Ok(reply)
    }
    fn track(&self, id: &str, connection: &iroh::endpoint::Connection) {
        if let Ok(mut connections) = self.connections.lock() {
            connections.retain(|(_, weak)| weak.upgrade().is_some());
            connections.push((id.into(), connection.weak_handle()));
        }
    }
    fn disconnect(&self, id: &str) {
        if let Ok(mut connections) = self.connections.lock() {
            connections.retain(|(peer, weak)| {
                if peer == id {
                    if let Some(c) = weak.upgrade() {
                        c.close(0u32.into(), b"unpaired");
                    }
                    false
                } else {
                    weak.upgrade().is_some()
                }
            });
        }
    }
    async fn tick(&self) {
        let (pending, peers) = match self.inner.lock() {
            Ok(mut inner) => {
                inner.pending.retain(|_, p| p.expires > Instant::now());
                (
                    inner
                        .pending
                        .values()
                        .filter(|p| p.local)
                        .cloned()
                        .collect::<Vec<_>>(),
                    inner.config.peers.clone(),
                )
            }
            Err(_) => return,
        };
        for p in pending {
            if let Ok(Reply::Confirm { confirmed: true }) = self
                .rpc(
                    p.peer.address,
                    Request::Confirm {
                        pairing_id: p.peer.pairing_id.clone(),
                    },
                )
                .await
            {
                if let Ok(mut inner) = self.inner.lock() {
                    if let Some(current) = inner.pending.get_mut(&p.peer.id) {
                        if current.peer.pairing_id == p.peer.pairing_id && current.local {
                            current.remote = true;
                            let _ = activate(&self.path, &mut inner, &p.peer.id);
                        }
                    }
                }
                (self.changed)();
            }
        }
        for peer in peers {
            let result = self.exchange(&peer).await;
            if let Ok(mut inner) = self.inner.lock() {
                if inner
                    .config
                    .peers
                    .iter()
                    .any(|p| p.id == peer.id && p.pairing_id == peer.pairing_id)
                {
                    let status = match result {
                        Ok(()) => "已同步".into(),
                        Err(error) => error,
                    };
                    if inner.statuses.get(&peer.id) != Some(&status) {
                        inner.statuses.insert(peer.id, status);
                        drop(inner);
                        (self.changed)();
                    }
                }
            }
        }
    }
    async fn exchange(&self, peer: &Peer) -> Result<(), String> {
        let known = self.store.lock().map_err(|_| LOCK)?.inventory()?;
        let reply = self
            .rpc(
                peer.address.clone(),
                Request::Inventory {
                    pairing_id: peer.pairing_id.clone(),
                    known,
                },
            )
            .await?;
        let (remote_known, batch) = match reply {
            Reply::Data { known, batch } => (known, batch),
            Reply::Error(error) => return Err(error),
            _ => return Err("同步响应不正确".into()),
        };
        let outgoing = {
            // Authorization and the import share this lock with unpair, so a late reply
            // cannot restore data after local pairing has been removed.
            let inner = self.inner.lock().map_err(|_| LOCK)?;
            authorize(&inner, &peer.id, &peer.pairing_id)?;
            let mut store = self.store.lock().map_err(|_| LOCK)?;
            let changed = store.import_batch(&batch)?;
            let outgoing = store.export_missing(&remote_known)?;
            drop(store);
            drop(inner);
            if changed {
                (self.changed)();
            }
            outgoing
        };
        match self
            .rpc(
                peer.address.clone(),
                Request::Push {
                    pairing_id: peer.pairing_id.clone(),
                    batch: outgoing,
                },
            )
            .await?
        {
            Reply::Ok => Ok(()),
            Reply::Error(error) => Err(error),
            _ => Err("同步响应不正确".into()),
        }
    }
}
fn authorize(inner: &Inner, id: &str, pairing_id: &str) -> Result<(), String> {
    if inner
        .config
        .peers
        .iter()
        .any(|p| p.id == id && p.pairing_id == pairing_id)
    {
        Ok(())
    } else {
        Err("设备未配对或已解除配对，请重新确认配对".into())
    }
}
fn activate(path: &Path, inner: &mut Inner, id: &str) -> Result<(), String> {
    let p = inner.pending.get(id).ok_or("配对请求已失效")?;
    if !p.local || !p.remote || p.expires <= Instant::now() {
        return Err("尚未获得两端确认".into());
    }
    let mut next = inner.config.clone();
    next.peers.retain(|peer| peer.id != id);
    next.peers.push(p.peer.clone());
    persist(path, &next)?;
    inner.config = next;
    inner.pending.remove(id);
    Ok(())
}
fn remove_peer(path: &Path, inner: &mut Inner, id: &str) -> Result<(), String> {
    let mut next = inner.config.clone();
    next.peers.retain(|p| p.id != id);
    persist(path, &next)?;
    inner.config = next;
    inner.pending.remove(id);
    inner.statuses.remove(id);
    Ok(())
}
fn persist(path: &Path, config: &Config) -> Result<(), String> {
    use std::io::Write;
    let mut file = tempfile::NamedTempFile::new_in(path.parent().ok_or("设备保存路径无效")?)
        .map_err(|_| "无法保存设备身份")?;
    serde_json::to_writer(&mut file, config).map_err(|_| "无法保存设备身份")?;
    file.flush().map_err(|_| "无法保存设备身份")?;
    file.as_file().sync_all().map_err(|_| "无法保存设备身份")?;
    file.persist(path).map_err(|_| "无法保存设备身份")?;
    Ok(())
}
fn ensure_lan_address(address: &EndpointAddr) -> Result<(), String> {
    use iroh::TransportAddr;
    for addr in &address.addrs {
        match addr {
            TransportAddr::Ip(addr) => {
                let local = match addr.ip() {
                    std::net::IpAddr::V4(ip) => {
                        ip.is_private() || ip.is_loopback() || ip.is_link_local()
                    }
                    std::net::IpAddr::V6(ip) => {
                        ip.is_loopback() || ip.is_unique_local() || ip.is_unicast_link_local()
                    }
                };
                if !local {
                    return Err("当前版本只接受局域网设备地址".into());
                }
            }
            _ => return Err("当前版本不使用外部中继".into()),
        }
    }
    Ok(())
}

fn is_lan_transport(addr: &iroh::TransportAddr) -> bool {
    match addr {
        iroh::TransportAddr::Ip(a) => match a.ip() {
            std::net::IpAddr::V4(ip) => ip.is_private() || ip.is_loopback() || ip.is_link_local(),
            std::net::IpAddr::V6(ip) => {
                ip.is_loopback() || ip.is_unique_local() || ip.is_unicast_link_local()
            }
        },
        _ => false,
    }
}

#[cfg(test)]
mod tests;
