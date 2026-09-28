use nautilus_core::store::Store;
use nautilus_core::types::{SyncBatch, SyncInventory};
use rusqlite::Connection;

const LEGACY_SQL: &str = "CREATE TABLE native_identity (device_id TEXT NOT NULL); INSERT INTO native_identity VALUES ('old-device'); CREATE TABLE native_settings (id INTEGER PRIMARY KEY CHECK (id = 1), base_url TEXT NOT NULL, model TEXT NOT NULL); INSERT INTO native_settings VALUES (1,'https://local.test','old-model'); CREATE TABLE native_materials (id TEXT PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL, version INTEGER NOT NULL); INSERT INTO native_materials VALUES ('m','Latest','new',2); CREATE TABLE native_material_versions (id TEXT NOT NULL, version INTEGER NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL, PRIMARY KEY(id,version)); INSERT INTO native_material_versions VALUES ('m',1,'Old','old'),('m',2,'Latest','new'); CREATE TABLE native_turns (id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, question TEXT NOT NULL, answer TEXT NOT NULL, reasoning TEXT NOT NULL, status TEXT NOT NULL, error TEXT, materials_json TEXT NOT NULL, material_ids_json TEXT NOT NULL, provider_json TEXT NOT NULL); INSERT INTO native_turns VALUES ('t1','r1','Q','A','R1','complete',NULL,'[{\"id\":\"m\",\"title\":\"Old\",\"content\":\"old\",\"version\":1}]','[\"m\"]','{\"base_url\":\"https://local.test\",\"model\":\"old-model\"}'); PRAGMA user_version = 1;";

fn pair() -> (tempfile::TempDir, Store, tempfile::TempDir, Store) {
    let a_dir = tempfile::tempdir().unwrap();
    let b_dir = tempfile::tempdir().unwrap();
    let a = Store::open(a_dir.path().join("a.db")).unwrap();
    let b = Store::open(b_dir.path().join("b.db")).unwrap();
    (a_dir, a, b_dir, b)
}
fn exchange(a: &mut Store, b: &mut Store) {
    let to_b = a.export_missing(&b.inventory().unwrap()).unwrap();
    let to_a = b.export_missing(&a.inventory().unwrap()).unwrap();
    b.import_batch(&to_b).unwrap();
    a.import_batch(&to_a).unwrap();
}
fn complete(
    db: &mut Store,
    request: &str,
    question: &str,
    ids: Vec<String>,
    parent: Option<String>,
) -> String {
    let turn = db
        .begin_turn(request.into(), question.into(), ids, parent)
        .unwrap()
        .turn;
    db.update_turn(&turn.id, &format!("answer-{request}"), "")
        .unwrap();
    db.finish_turn(&turn.id, "complete", None).unwrap();
    turn.id
}

#[test]
fn reciprocal_exchange_is_idempotent_and_pending_is_local() {
    let (_ad, mut a, _bd, mut b) = pair();
    let material = a
        .save_material(None, "Title".into(), "Private text".into())
        .unwrap();
    a.save_selection(vec![material.id.clone()]).unwrap();
    let first = complete(&mut a, "a1", "Q", vec![material.id.clone()], None);
    exchange(&mut a, &mut b);
    assert_eq!(b.snapshot().unwrap().materials, vec![material.clone()]);
    assert_eq!(b.snapshot().unwrap().turns.len(), 1);
    let pending = b
        .begin_turn(
            "b-pending".into(),
            "Draft".into(),
            vec![material.id.clone()],
            Some(first),
        )
        .unwrap();
    exchange(&mut a, &mut b);
    assert_eq!(a.snapshot().unwrap().turns.len(), 1);
    assert!(!a.inventory().unwrap().turn_ids.contains(&pending.turn.id));
    b.finish_turn(&pending.turn.id, "complete", None).unwrap();
    exchange(&mut a, &mut b);
    assert_eq!(a.snapshot().unwrap().turns.len(), 2);
    assert!(!a
        .import_batch(&b.export_missing(&SyncInventory::default()).unwrap())
        .unwrap());
    assert!(!b
        .import_batch(&a.export_missing(&SyncInventory::default()).unwrap())
        .unwrap());
}

#[test]
fn rejects_missing_dependency_and_changed_id_atomically() {
    let (_ad, mut a, _bd, mut b) = pair();
    let material = a.save_material(None, "T".into(), "C".into()).unwrap();
    a.save_selection(vec![material.id.clone()]).unwrap();
    complete(&mut a, "one", "Q", vec![material.id], None);
    let batch = a.export_missing(&SyncInventory::default()).unwrap();
    let before = b.snapshot().unwrap();
    let mut missing = batch.clone();
    missing.material_revisions.clear();
    assert!(b.import_batch(&missing).is_err());
    assert_eq!(b.snapshot().unwrap(), before);
    let mut missing_parent = batch.clone();
    let parent = missing_parent.turns[0].id.clone();
    missing_parent.turns[0].parent_id = Some(parent);
    assert!(b.import_batch(&missing_parent).is_err());
    assert_eq!(b.snapshot().unwrap(), before);
    assert!(b
        .import_batch(&SyncBatch {
            protocol: 99,
            ..batch.clone()
        })
        .is_err());
    assert_eq!(b.snapshot().unwrap(), before);
    assert!(b.import_batch(&batch).unwrap());
    let mut changed = batch;
    changed.material_revisions[0].material.content = "tampered".into();
    assert!(b.import_batch(&changed).is_err());
    assert_eq!(b.snapshot().unwrap().materials[0].content, "C");
}

#[test]
fn material_and_selection_conflicts_require_explicit_resolution() {
    let (_ad, mut a, _bd, mut b) = pair();
    let material = a.save_material(None, "Base".into(), "same".into()).unwrap();
    a.save_selection(vec![material.id.clone()]).unwrap();
    exchange(&mut a, &mut b);
    let left = a
        .save_material(Some(material.id.clone()), "Left".into(), "left".into())
        .unwrap();
    let right = b
        .save_material(Some(material.id.clone()), "Right".into(), "right".into())
        .unwrap();
    a.save_selection(vec![]).unwrap();
    let other = b
        .save_material(None, "Other".into(), "other".into())
        .unwrap();
    b.save_selection(vec![material.id.clone(), other.id.clone()])
        .unwrap();
    exchange(&mut a, &mut b);
    let snap = a.snapshot().unwrap();
    assert!(snap.materials.iter().all(|m| m.id != material.id));
    assert_eq!(snap.material_conflicts[0].versions.len(), 2);
    assert_eq!(snap.selection_heads.len(), 2);
    assert!(a
        .save_material(Some(material.id.clone()), "Bad".into(), "bad".into())
        .is_err());
    assert!(a
        .begin_turn("blocked".into(), "Q".into(), vec![], None)
        .is_err());
    let resolved = a.resolve_material(&material.id, &left.revision_id).unwrap();
    assert_eq!(resolved.content, "left");
    assert!(resolved.version > left.version && resolved.version > right.version);
    let chosen = snap
        .selection_heads
        .iter()
        .find(|s| s.material_ids.is_empty())
        .unwrap();
    a.resolve_selection(&chosen.id).unwrap();
    exchange(&mut a, &mut b);
    assert!(b.snapshot().unwrap().material_conflicts.is_empty());
    assert_eq!(
        b.snapshot()
            .unwrap()
            .materials
            .iter()
            .find(|m| m.id == material.id)
            .unwrap(),
        &resolved
    );
    assert_eq!(b.snapshot().unwrap().selection_heads.len(), 1);
    assert!(b.snapshot().unwrap().selection_heads[0]
        .material_ids
        .is_empty());
}

#[test]
fn explicit_parent_keeps_concurrent_branches_out_of_each_others_context() {
    let (_ad, mut a, _bd, mut b) = pair();
    let root = complete(&mut a, "root", "Root", vec![], None);
    exchange(&mut a, &mut b);
    let left = complete(&mut a, "left", "Left", vec![], Some(root.clone()));
    let right = complete(&mut b, "right", "Right", vec![], Some(root));
    exchange(&mut a, &mut b);
    let next = a
        .begin_turn("next".into(), "Next".into(), vec![], Some(left))
        .unwrap();
    assert!(next.messages.iter().any(|m| m.content == "answer-left"));
    assert!(!next.messages.iter().any(|m| m.content == "answer-right"));
    assert!(a.snapshot().unwrap().turns.iter().any(|t| t.id == right));
}

#[test]
fn schema_one_stays_unchanged_until_explicit_upgrade() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("old.db");
    let db = Connection::open(&path).unwrap();
    db.execute_batch(LEGACY_SQL).unwrap();
    for (id, status, answer, reasoning, error, material_version, material_content, model) in [
        (
            "t2",
            "canceled",
            "partial-2",
            "R2",
            Some("canceled by user"),
            1,
            "old",
            "model-2",
        ),
        (
            "t3",
            "failed",
            "partial-3",
            "R3",
            Some("network error"),
            2,
            "new",
            "model-3",
        ),
        (
            "t4",
            "pending",
            "partial-4",
            "R4",
            None,
            2,
            "new",
            "model-4",
        ),
    ] {
        let material = format!(
            "[{{\"id\":\"m\",\"title\":\"{}\",\"content\":\"{}\",\"version\":{}}}]",
            if material_version == 1 {
                "Old"
            } else {
                "Latest"
            },
            material_content,
            material_version
        );
        let provider = format!("{{\"base_url\":\"https://local.test\",\"model\":\"{model}\"}}");
        db.execute(
            "INSERT INTO native_turns VALUES (?1,?2,?3,?4,?5,?6,?7,?8,'[\"m\"]',?9)",
            rusqlite::params![
                id,
                format!("request-{id}"),
                format!("question-{id}"),
                answer,
                reasoning,
                status,
                error,
                material,
                provider
            ],
        )
        .unwrap();
    }
    drop(db);
    let before = std::fs::read(&path).unwrap();
    assert!(Store::open(&path).is_err());
    assert_eq!(std::fs::read(&path).unwrap(), before);
    Store::upgrade_v1(&path).unwrap();
    assert!(Store::open(&path).is_err());
    let v2 = Connection::open(&path).unwrap();
    v2.execute(
        "INSERT INTO native_selections VALUES ('legacy-selection','[]','[\"m\"]')",
        [],
    )
    .unwrap();
    drop(v2);
    Store::upgrade_v2(&path).unwrap();
    let upgraded = Store::open(&path).unwrap();
    let snap = upgraded.snapshot().unwrap();
    assert_eq!(snap.device_id, "old-device");
    assert_eq!(snap.schema_version, 3);
    assert_eq!(snap.materials[0].version, 2);
    assert_eq!(snap.turns[0].materials[0].content, "old");
    assert_eq!(
        snap.turns[0].materials[0].revision_id,
        "legacy:old-device:m:1"
    );
    assert_eq!(snap.turns[0].provider.model, "old-model");
    assert_eq!(snap.turns.len(), 4);
    assert_eq!(snap.turns[0].question, "Q");
    assert_eq!(snap.turns[0].answer, "A");
    assert_eq!(snap.turns[0].reasoning, "R1");
    assert_eq!(snap.turns[0].parent_id, None);
    assert_eq!(snap.turns[0].session_id, None);
    assert_eq!(snap.turns[0].help_request, None);
    assert_eq!(snap.selection_heads[0].id, "legacy-selection");
    assert_eq!(snap.selection_heads[0].task_id, None);
    for (i, status, answer, reasoning, error, material_version, material_content, model) in [
        (
            1,
            "canceled",
            "partial-2",
            "R2",
            Some("canceled by user"),
            1,
            "old",
            "model-2",
        ),
        (
            2,
            "failed",
            "partial-3",
            "R3",
            Some("network error"),
            2,
            "new",
            "model-3",
        ),
        (3, "pending", "partial-4", "R4", None, 2, "new", "model-4"),
    ] {
        let turn = &snap.turns[i];
        assert_eq!(turn.question, format!("question-t{}", i + 1));
        assert_eq!(turn.answer, answer);
        assert_eq!(turn.reasoning, reasoning);
        assert_eq!(turn.status, status);
        assert_eq!(turn.error.as_deref(), error);
        assert_eq!(turn.materials[0].version, material_version);
        assert_eq!(turn.materials[0].content, material_content);
        assert_eq!(turn.provider.model, model);
        assert_eq!(
            turn.parent_id.as_deref(),
            Some(snap.turns[i - 1].id.as_str())
        );
        assert_eq!(turn.origin_device, "old-device");
    }
    assert_eq!(upgraded.inventory().unwrap().material_revision_ids.len(), 2);
    assert_eq!(upgraded.inventory().unwrap().turn_ids.len(), 3);
    let mut upgraded = upgraded;
    upgraded.recover().unwrap();
    let recovered = upgraded.snapshot().unwrap();
    assert_eq!(recovered.turns[3].status, "interrupted");
    assert_eq!(recovered.turns[3].answer, "partial-4");
    assert_eq!(recovered.turns[3].reasoning, "R4");
}

#[test]
fn inconsistent_schema_one_rejects_upgrade_without_changes() {
    for (name, change) in [
        ("missing_identity", "DELETE FROM native_identity"),
        (
            "duplicate_identity",
            "INSERT INTO native_identity VALUES ('other-device')",
        ),
        (
            "stale_current",
            "UPDATE native_materials SET version = 1, title = 'Old', content = 'old'",
        ),
        (
            "changed_current",
            "UPDATE native_materials SET content = 'unsaved current text'",
        ),
        (
            "orphan_version",
            "INSERT INTO native_material_versions VALUES ('orphan',1,'Lost','lost')",
        ),
    ] {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join(format!("{name}.db"));
        let db = Connection::open(&path).unwrap();
        db.execute_batch(LEGACY_SQL).unwrap();
        db.execute_batch(change).unwrap();
        drop(db);
        let before = std::fs::read(&path).unwrap();
        assert!(Store::upgrade_v1(&path).is_err(), "{name}");
        assert_eq!(std::fs::read(&path).unwrap(), before, "{name}");
        let db = Connection::open(&path).unwrap();
        let version: i64 = db
            .query_row("PRAGMA user_version", [], |r| r.get(0))
            .unwrap();
        assert_eq!(version, 1, "{name}");
    }
}

#[test]
fn reopened_devices_converge_incrementally_without_mixing_branches() {
    let (a_dir, mut a, b_dir, mut b) = pair();
    let material = a.save_material(None, "Notes".into(), "v1".into()).unwrap();
    a.save_selection(vec![material.id.clone()]).unwrap();
    let root = complete(&mut a, "root", "Shared", vec![material.id.clone()], None);
    exchange(&mut a, &mut b);
    drop(a);
    drop(b);
    let mut a = Store::open(a_dir.path().join("a.db")).unwrap();
    let mut b = Store::open(b_dir.path().join("b.db")).unwrap();
    let left = complete(
        &mut a,
        "left",
        "A branch",
        vec![material.id.clone()],
        Some(root.clone()),
    );
    let right = complete(
        &mut b,
        "right",
        "B branch",
        vec![material.id.clone()],
        Some(root),
    );
    let a_change = a
        .save_material(Some(material.id.clone()), "Notes A".into(), "v2-a".into())
        .unwrap();
    let b_change = b
        .save_material(Some(material.id.clone()), "Notes B".into(), "v2-b".into())
        .unwrap();
    exchange(&mut a, &mut b);
    drop(a);
    drop(b);
    let mut a = Store::open(a_dir.path().join("a.db")).unwrap();
    let mut b = Store::open(b_dir.path().join("b.db")).unwrap();
    assert_eq!(
        a.snapshot().unwrap().material_conflicts,
        b.snapshot().unwrap().material_conflicts
    );
    assert_eq!(
        a.snapshot().unwrap().material_conflicts[0].versions.len(),
        2
    );
    let chosen = a
        .resolve_material(&material.id, &a_change.revision_id)
        .unwrap();
    exchange(&mut a, &mut b);
    assert_eq!(
        b.snapshot()
            .unwrap()
            .materials
            .iter()
            .find(|m| m.id == material.id),
        Some(&chosen)
    );
    assert_ne!(chosen.revision_id, b_change.revision_id);
    let seen_left = b.snapshot().unwrap().turns.iter().any(|t| t.id == left);
    let seen_right = a.snapshot().unwrap().turns.iter().any(|t| t.id == right);
    assert!(seen_left && seen_right);
    assert!(a
        .export_missing(&b.inventory().unwrap())
        .unwrap()
        .turns
        .is_empty());
    assert!(b
        .export_missing(&a.inventory().unwrap())
        .unwrap()
        .material_revisions
        .is_empty());
}
