use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Default)]
pub struct ProviderSettings {
    pub base_url: String,
    pub model: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Material {
    pub id: String,
    pub title: String,
    pub content: String,
    pub version: i64,
    pub revision_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct MaterialRevision {
    pub material: Material,
    pub parents: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct MaterialConflict {
    pub material_id: String,
    pub versions: Vec<Material>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SelectionRevision {
    pub id: String,
    pub parents: Vec<String>,
    pub material_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Turn {
    pub id: String,
    pub request_id: String,
    pub question: String,
    pub answer: String,
    pub reasoning: String,
    pub status: String,
    pub error: Option<String>,
    pub materials: Vec<Material>,
    pub provider: ProviderSettings,
    pub parent_id: Option<String>,
    pub origin_device: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Snapshot {
    pub device_id: String,
    pub schema_version: i64,
    pub materials: Vec<Material>,
    pub material_conflicts: Vec<MaterialConflict>,
    pub selection_heads: Vec<SelectionRevision>,
    pub turns: Vec<Turn>,
    pub settings: ProviderSettings,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Default)]
pub struct SyncInventory {
    pub material_revision_ids: Vec<String>,
    pub turn_ids: Vec<String>,
    pub selection_revision_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SyncBatch {
    pub protocol: u32,
    pub material_revisions: Vec<MaterialRevision>,
    pub turns: Vec<Turn>,
    pub selections: Vec<SelectionRevision>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatMessage {
    pub role: String,
    pub content: String,
}

pub struct PreparedTurn {
    pub turn: Turn,
    pub messages: Vec<ChatMessage>,
    pub created: bool,
}
