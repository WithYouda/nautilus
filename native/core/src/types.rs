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
}

#[derive(Debug, Clone, Serialize, Deserialize)]
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
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Snapshot {
    pub device_id: String,
    pub schema_version: i64,
    pub materials: Vec<Material>,
    pub turns: Vec<Turn>,
    pub settings: ProviderSettings,
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
