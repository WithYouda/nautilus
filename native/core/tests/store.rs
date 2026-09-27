use nautilus_core::store::Store;
use nautilus_core::types::ProviderSettings;
use rusqlite::Connection;

fn store() -> (tempfile::TempDir, Store) {
    let dir = tempfile::tempdir().unwrap();
    let db = Store::open(dir.path().join("native.db")).unwrap();
    (dir, db)
}

#[test]
fn persists_identity_settings_materials_and_turns_across_reopen() {
    let (dir, mut db) = store();
    let device = db.snapshot().unwrap().device_id;
    db.save_settings(ProviderSettings {
        base_url: "https://example.test/v1".into(),
        model: "study".into(),
    })
    .unwrap();
    let material = db
        .save_material(None, "Title".into(), "Content".into())
        .unwrap();
    let prepared = db
        .begin_turn(
            "request-1".into(),
            "Explain".into(),
            vec![material.id.clone()],
        )
        .unwrap();
    assert!(prepared.created);
    assert_eq!(prepared.turn.provider.model, "study");
    assert!(prepared
        .messages
        .iter()
        .any(|m| m.content.contains("Content")));
    assert!(prepared
        .messages
        .iter()
        .filter(|m| m.role == "system")
        .all(|m| !m.content.contains("Content")));
    db.save_settings(ProviderSettings {
        base_url: "https://changed.test/v1".into(),
        model: "changed".into(),
    })
    .unwrap();
    db.update_turn(&prepared.turn.id, "Answer", "Reasoning")
        .unwrap();
    db.finish_turn(&prepared.turn.id, "complete", None).unwrap();
    drop(db);

    let reopened = Store::open(dir.path().join("native.db")).unwrap();
    let snapshot = reopened.snapshot().unwrap();
    assert_eq!(snapshot.device_id, device);
    assert_eq!(snapshot.schema_version, 1);
    assert_eq!(snapshot.settings.model, "changed");
    assert_eq!(snapshot.materials, vec![material]);
    assert_eq!(snapshot.turns[0].provider.model, "study");
    assert_eq!(snapshot.turns[0].answer, "Answer");
    assert_eq!(snapshot.turns[0].reasoning, "Reasoning");
}

#[test]
fn freezes_material_versions_and_limits_history_to_consecutive_compatible_turns() {
    let (_dir, mut db) = store();
    let material = db
        .save_material(None, "First".into(), "Old private text".into())
        .unwrap();
    let a = db
        .begin_turn(
            "a".into(),
            "First question".into(),
            vec![material.id.clone()],
        )
        .unwrap();
    db.update_turn(&a.turn.id, "First answer", "").unwrap();
    db.finish_turn(&a.turn.id, "complete", None).unwrap();
    let b = db
        .begin_turn("b".into(), "Follow-up".into(), vec![material.id.clone()])
        .unwrap();
    assert!(b.messages.iter().any(|m| m.content == "First answer"));
    db.update_turn(&b.turn.id, "Second answer", "").unwrap();
    db.finish_turn(&b.turn.id, "complete", None).unwrap();

    let edited = db
        .save_material(
            Some(material.id.clone()),
            "Second".into(),
            "New private text".into(),
        )
        .unwrap();
    assert_eq!(edited.version, 2);
    let c = db
        .begin_turn("c".into(), "After edit".into(), vec![edited.id.clone()])
        .unwrap();
    assert!(!c
        .messages
        .iter()
        .any(|m| m.content.contains("First answer")));
    assert!(!c
        .messages
        .iter()
        .any(|m| m.content.contains("Old private text")));
    assert_eq!(db.snapshot().unwrap().turns[0].materials, vec![material]);
    db.finish_turn(&c.turn.id, "complete", None).unwrap();

    let d = db
        .begin_turn("d".into(), "Without material".into(), vec![])
        .unwrap();
    assert!(!d
        .messages
        .iter()
        .any(|m| m.content.contains("New private text")));
    assert!(!d.messages.iter().any(|m| m.content == "Second answer"));
}

#[test]
fn reordering_same_selected_material_versions_keeps_history() {
    let (_dir, mut db) = store();
    let first = db.save_material(None, "A".into(), "A text".into()).unwrap();
    let second = db.save_material(None, "B".into(), "B text".into()).unwrap();
    let previous = db
        .begin_turn(
            "first".into(),
            "Question".into(),
            vec![first.id.clone(), second.id.clone()],
        )
        .unwrap();
    db.update_turn(&previous.turn.id, "Compatible answer", "")
        .unwrap();
    db.finish_turn(&previous.turn.id, "complete", None).unwrap();
    let reordered = db
        .begin_turn("second".into(), "Next".into(), vec![second.id, first.id])
        .unwrap();
    assert!(reordered
        .messages
        .iter()
        .any(|m| m.content == "Compatible answer"));
}

#[test]
fn request_replay_is_idempotent_and_pending_is_exclusive() {
    let (_dir, mut db) = store();
    let a = db
        .begin_turn("same".into(), "Question".into(), vec![])
        .unwrap();
    let replay = db
        .begin_turn("same".into(), "Question".into(), vec![])
        .unwrap();
    assert!(!replay.created);
    assert!(replay.messages.is_empty());
    assert_eq!(replay.turn.id, a.turn.id);
    assert!(db
        .begin_turn("same".into(), "Changed".into(), vec![])
        .is_err());
    assert!(db
        .begin_turn("another".into(), "Question".into(), vec![])
        .is_err());
    assert_eq!(db.snapshot().unwrap().turns.len(), 1);
    db.finish_turn(&a.turn.id, "canceled", None).unwrap();
    assert!(db
        .begin_turn("another".into(), "Question".into(), vec![])
        .is_ok());
}

#[test]
fn partial_failure_and_recovery_do_not_invent_completed_answers() {
    let (dir, mut db) = store();
    let failed = db.begin_turn("failed".into(), "Q".into(), vec![]).unwrap();
    db.update_turn(&failed.turn.id, "partial", "partial thought")
        .unwrap();
    db.finish_turn(&failed.turn.id, "failed", Some("网络中断"))
        .unwrap();
    assert!(db.update_turn(&failed.turn.id, "late", "late").is_err());
    let pending = db
        .begin_turn("pending".into(), "Q2".into(), vec![])
        .unwrap();
    db.update_turn(&pending.turn.id, "another partial", "")
        .unwrap();
    drop(db);
    let mut reopened = Store::open(dir.path().join("native.db")).unwrap();
    reopened.recover().unwrap();
    let turns = reopened.snapshot().unwrap().turns;
    assert_eq!(turns[0].status, "failed");
    assert_eq!(turns[0].answer, "partial");
    assert_eq!(turns[1].status, "interrupted");
    assert_eq!(turns[1].answer, "another partial");
    let next = reopened
        .begin_turn("next".into(), "Q3".into(), vec![])
        .unwrap();
    assert!(!next.messages.iter().any(|m| m.content.contains("partial")));
}

#[test]
fn rejects_foreign_databases_without_modifying_them() {
    let dir = tempfile::tempdir().unwrap();
    for (name, statement) in [
        ("foreign.db", "CREATE TABLE unrelated (private_value TEXT); INSERT INTO unrelated VALUES ('keep');"),
        ("trial.db", "PRAGMA user_version = 35; CREATE TABLE users (id TEXT); INSERT INTO users VALUES ('keep');"),
    ] {
        let path = dir.path().join(name);
        let connection = Connection::open(&path).unwrap();
        connection.execute_batch(statement).unwrap();
        drop(connection);
        let before = std::fs::read(&path).unwrap();
        assert!(Store::open(&path).is_err());
        assert_eq!(std::fs::read(&path).unwrap(), before);
    }
}
