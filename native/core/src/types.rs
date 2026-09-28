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
    #[serde(default)]
    pub task_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct LearningSetupDraft {
    pub original_intent: String,
    pub goal_title: String,
    pub goal_description: String,
    pub plan_title: String,
    pub plan_description: String,
    pub action_title: String,
    pub context_key: String,
    pub object_description: String,
    pub behavior: String,
    pub outcome_context_key: String,
    pub boundaries: String,
    pub stop_conditions: String,
    pub time_budget_minutes: Option<i64>,
}

impl LearningSetupDraft {
    pub fn validate(&self) -> Result<(), String> {
        for value in [
            &self.original_intent,
            &self.goal_title,
            &self.plan_title,
            &self.action_title,
            &self.context_key,
            &self.object_description,
            &self.behavior,
            &self.outcome_context_key,
            &self.stop_conditions,
        ] {
            if value.trim().is_empty() {
                return Err("学习安排的必填内容不能为空。".into());
            }
        }
        if self
            .time_budget_minutes
            .is_some_and(|minutes| !(1..=1440).contains(&minutes))
        {
            return Err("学习时间须为1到1440分钟。".into());
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct LearningTask {
    pub id: String,
    pub goal_id: String,
    pub plan_id: String,
    pub outcome_id: String,
    pub delegation_id: String,
    pub contract_id: String,
    pub request_id: String,
    pub origin_device: String,
    pub created_at: String,
    pub draft: LearningSetupDraft,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct LearningSession {
    pub id: String,
    pub task_id: String,
    pub request_id: String,
    pub origin_device: String,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct LearningNote {
    pub id: String,
    pub session_id: String,
    pub request_id: String,
    pub origin_device: String,
    pub created_at: String,
    pub content: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct HelpDisplay {
    pub id: String,
    pub turn_id: String,
    pub origin_device: String,
    pub at: String,
    pub characters: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Default)]
pub struct LearningPosition {
    pub session_id: Option<String>,
    pub turn_id: Option<String>,
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
    #[serde(default)]
    pub session_id: Option<String>,
    #[serde(default)]
    pub help_request: Option<String>,
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
    pub learning_tasks: Vec<LearningTask>,
    pub learning_sessions: Vec<LearningSession>,
    pub learning_notes: Vec<LearningNote>,
    pub help_displays: Vec<HelpDisplay>,
    pub position: LearningPosition,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SyncInventory {
    #[serde(default = "legacy_protocol")]
    pub protocol: u32,
    pub material_revision_ids: Vec<String>,
    pub turn_ids: Vec<String>,
    pub selection_revision_ids: Vec<String>,
    #[serde(default)]
    pub learning_task_ids: Vec<String>,
    #[serde(default)]
    pub learning_session_ids: Vec<String>,
    #[serde(default)]
    pub learning_note_ids: Vec<String>,
    #[serde(default)]
    pub help_display_ids: Vec<String>,
}

fn legacy_protocol() -> u32 {
    1
}
impl Default for SyncInventory {
    fn default() -> Self {
        Self {
            protocol: 2,
            material_revision_ids: vec![],
            turn_ids: vec![],
            selection_revision_ids: vec![],
            learning_task_ids: vec![],
            learning_session_ids: vec![],
            learning_note_ids: vec![],
            help_display_ids: vec![],
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SyncBatch {
    pub protocol: u32,
    pub material_revisions: Vec<MaterialRevision>,
    pub turns: Vec<Turn>,
    pub selections: Vec<SelectionRevision>,
    pub learning_tasks: Vec<LearningTask>,
    pub learning_sessions: Vec<LearningSession>,
    pub learning_notes: Vec<LearningNote>,
    pub help_displays: Vec<HelpDisplay>,
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
