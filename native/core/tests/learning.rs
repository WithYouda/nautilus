use nautilus_core::store::Store;
use nautilus_core::types::{LearningPosition, LearningSetupDraft, SyncInventory};

fn draft(title: &str) -> LearningSetupDraft {
    LearningSetupDraft {
        original_intent: "理解主题".into(),
        goal_title: title.into(),
        goal_description: String::new(),
        plan_title: "逐步学习".into(),
        plan_description: String::new(),
        action_title: "阅读并解释".into(),
        context_key: "学习室".into(),
        object_description: "一个概念".into(),
        behavior: "解释".into(),
        outcome_context_key: "本次学习".into(),
        boundaries: String::new(),
        stop_conditions: "能够自行解释".into(),
        time_budget_minutes: Some(30),
    }
}

#[test]
fn task_session_and_note_retry_preserve_facts_and_position() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("a.db");
    let mut db = Store::open(&path).unwrap();
    let task = db
        .create_learning_task("task-request".into(), draft("代数"))
        .unwrap();
    assert_eq!(
        task,
        db.create_learning_task("task-request".into(), draft("代数"))
            .unwrap()
    );
    assert!(db
        .create_learning_task("task-request".into(), draft("几何"))
        .is_err());
    assert!(db
        .start_learning_session("missing".into(), "missing".into())
        .is_err());
    assert!(db.snapshot().unwrap().learning_sessions.is_empty());
    let session = db
        .start_learning_session("session-request".into(), task.id.clone())
        .unwrap();
    assert_eq!(
        session,
        db.start_learning_session("session-request".into(), task.id.clone())
            .unwrap()
    );
    let note = db
        .save_learning_note(
            "note-request".into(),
            session.id.clone(),
            "今天理解了变量".into(),
        )
        .unwrap();
    assert_eq!(
        note,
        db.save_learning_note(
            "note-request".into(),
            session.id.clone(),
            "今天理解了变量".into()
        )
        .unwrap()
    );
    let turn = db
        .begin_learning_turn(
            "turn".into(),
            "请解释".into(),
            vec![],
            None,
            Some(session.id.clone()),
            None,
        )
        .unwrap();
    db.update_turn(&turn.turn.id, "答案", "").unwrap();
    db.finish_turn(&turn.turn.id, "complete", None).unwrap();
    let position = LearningPosition {
        session_id: Some(session.id),
        turn_id: Some(turn.turn.id),
    };
    db.save_learning_position(position.clone()).unwrap();
    drop(db);
    let db = Store::open(path).unwrap();
    let snap = db.snapshot().unwrap();
    assert_eq!(snap.learning_tasks, vec![task]);
    assert_eq!(snap.learning_notes, vec![note]);
    assert_eq!(snap.position, position);
}

#[test]
fn task_context_and_selections_remain_separate() {
    let dir = tempfile::tempdir().unwrap();
    let mut db = Store::open(dir.path().join("a.db")).unwrap();
    let a = db.create_learning_task("a".into(), draft("代数")).unwrap();
    let b = db.create_learning_task("b".into(), draft("几何")).unwrap();
    let sa = db
        .start_learning_session("sa".into(), a.id.clone())
        .unwrap();
    let sb = db
        .start_learning_session("sb".into(), b.id.clone())
        .unwrap();
    let material = db
        .save_material(None, "共享资料".into(), "内容".into())
        .unwrap();
    db.save_task_selection(Some(a.id.clone()), vec![material.id.clone()])
        .unwrap();
    db.save_task_selection(Some(b.id.clone()), vec![]).unwrap();
    assert!(db
        .begin_learning_turn(
            "bad-selection".into(),
            "Q".into(),
            vec![],
            None,
            Some(sa.id.clone()),
            None
        )
        .is_err());
    let first = db
        .begin_learning_turn(
            "qa".into(),
            "代数问题".into(),
            vec![material.id.clone()],
            None,
            Some(sa.id.clone()),
            None,
        )
        .unwrap();
    assert!(first.messages.iter().any(|m| m.content.contains("代数")));
    db.update_turn(&first.turn.id, "代数回答", "").unwrap();
    db.finish_turn(&first.turn.id, "complete", None).unwrap();
    assert!(db
        .begin_learning_turn(
            "cross".into(),
            "几何问题".into(),
            vec![],
            Some(first.turn.id.clone()),
            Some(sb.id.clone()),
            None
        )
        .is_err());
    assert!(db
        .save_learning_position(LearningPosition {
            session_id: Some(sb.id.clone()),
            turn_id: Some(first.turn.id.clone())
        })
        .is_err());
    let second = db
        .begin_learning_turn(
            "qb".into(),
            "几何问题".into(),
            vec![],
            None,
            Some(sb.id),
            None,
        )
        .unwrap();
    assert!(second.messages.iter().any(|m| m.content.contains("几何")));
    assert!(!second
        .messages
        .iter()
        .any(|m| m.content.contains("代数回答")));
}

#[test]
fn synced_learning_dependencies_and_receipt_survive_reopen() {
    let ad = tempfile::tempdir().unwrap();
    let bd = tempfile::tempdir().unwrap();
    let mut a = Store::open(ad.path().join("a.db")).unwrap();
    let mut b = Store::open(bd.path().join("b.db")).unwrap();
    let task = a
        .create_learning_task("task".into(), draft("物理"))
        .unwrap();
    let session = a
        .start_learning_session("session".into(), task.id.clone())
        .unwrap();
    a.save_learning_note("note".into(), session.id.clone(), "我的记录".into())
        .unwrap();
    let turn = a
        .begin_learning_turn(
            "help".into(),
            "请给提示".into(),
            vec![],
            None,
            Some(session.id.clone()),
            Some("hint".into()),
        )
        .unwrap();
    assert!(turn
        .messages
        .iter()
        .any(|m| m.content.contains("给一个有用的线索")));
    a.update_turn(&turn.turn.id, "线索🔎", "").unwrap();
    a.finish_turn(&turn.turn.id, "complete", None).unwrap();
    let display = a.record_help_display(&turn.turn.id, 3).unwrap();
    assert_eq!(display, a.record_help_display(&turn.turn.id, 3).unwrap());
    let batch = a.export_missing(&SyncInventory::default()).unwrap();
    let before = b.snapshot().unwrap();
    let mut missing = batch.clone();
    missing.learning_tasks.clear();
    assert!(b.import_batch(&missing).is_err());
    assert_eq!(b.snapshot().unwrap(), before);
    let mut bad_parent = batch.clone();
    bad_parent.turns[0].session_id = Some("missing".into());
    assert!(b.import_batch(&bad_parent).is_err());
    assert_eq!(b.snapshot().unwrap(), before);
    assert!(b.import_batch(&batch).unwrap());
    assert!(!b.import_batch(&batch).unwrap());
    drop(b);
    let b = Store::open(bd.path().join("b.db")).unwrap();
    let snap = b.snapshot().unwrap();
    assert_eq!(snap.learning_tasks, vec![task]);
    assert_eq!(snap.learning_sessions, vec![session]);
    assert_eq!(snap.learning_notes.len(), 1);
    assert_eq!(snap.help_displays, vec![display]);
    assert_eq!(snap.position, LearningPosition::default());
    let old_inventory = SyncInventory {
        protocol: 1,
        ..SyncInventory::default()
    };
    assert!(a.export_missing(&old_inventory).is_err());
}

#[test]
fn concurrent_display_receipts_merge_for_one_turn() {
    let ad = tempfile::tempdir().unwrap();
    let bd = tempfile::tempdir().unwrap();
    let mut a = Store::open(ad.path().join("a.db")).unwrap();
    let mut b = Store::open(bd.path().join("b.db")).unwrap();
    let task = a
        .create_learning_task("task".into(), draft("数学"))
        .unwrap();
    let session = a.start_learning_session("session".into(), task.id).unwrap();
    let turn = a
        .begin_learning_turn(
            "help".into(),
            "提示".into(),
            vec![],
            None,
            Some(session.id),
            Some("hint".into()),
        )
        .unwrap();
    a.update_turn(&turn.turn.id, "一二三", "").unwrap();
    a.finish_turn(&turn.turn.id, "complete", None).unwrap();
    let batch = a.export_missing(&b.inventory().unwrap()).unwrap();
    b.import_batch(&batch).unwrap();
    let left = a.record_help_display(&turn.turn.id, 3).unwrap();
    let right = b.record_help_display(&turn.turn.id, 3).unwrap();
    assert_ne!(left.id, right.id);
    let to_b = a.export_missing(&b.inventory().unwrap()).unwrap();
    let to_a = b.export_missing(&a.inventory().unwrap()).unwrap();
    b.import_batch(&to_b).unwrap();
    a.import_batch(&to_a).unwrap();
    assert_eq!(a.snapshot().unwrap().help_displays.len(), 2);
    assert_eq!(b.snapshot().unwrap().help_displays.len(), 2);
    assert_eq!(a.record_help_display(&turn.turn.id, 3).unwrap(), left);
}

#[test]
fn task_selection_conflict_does_not_block_another_task() {
    let ad = tempfile::tempdir().unwrap();
    let bd = tempfile::tempdir().unwrap();
    let mut a = Store::open(ad.path().join("a.db")).unwrap();
    let mut b = Store::open(bd.path().join("b.db")).unwrap();
    let ta = a.create_learning_task("ta".into(), draft("代数")).unwrap();
    let tb = a.create_learning_task("tb".into(), draft("几何")).unwrap();
    let sa = a
        .start_learning_session("sa".into(), ta.id.clone())
        .unwrap();
    let sb = a
        .start_learning_session("sb".into(), tb.id.clone())
        .unwrap();
    let m = a.save_material(None, "资料".into(), "内容".into()).unwrap();
    a.save_task_selection(Some(ta.id.clone()), vec![m.id.clone()])
        .unwrap();
    b.import_batch(&a.export_missing(&b.inventory().unwrap()).unwrap())
        .unwrap();
    a.save_task_selection(Some(ta.id.clone()), vec![]).unwrap();
    let other = b
        .save_material(None, "第二份".into(), "内容".into())
        .unwrap();
    b.save_task_selection(Some(ta.id.clone()), vec![m.id.clone(), other.id])
        .unwrap();
    a.import_batch(&b.export_missing(&a.inventory().unwrap()).unwrap())
        .unwrap();
    assert!(a
        .begin_learning_turn(
            "blocked".into(),
            "Q".into(),
            vec![],
            None,
            Some(sa.id),
            None
        )
        .is_err());
    a.save_task_selection(Some(tb.id.clone()), vec![]).unwrap();
    assert!(a
        .begin_learning_turn(
            "other-task".into(),
            "Q".into(),
            vec![],
            None,
            Some(sb.id),
            None
        )
        .is_ok());
    let heads: Vec<_> = a
        .snapshot()
        .unwrap()
        .selection_heads
        .into_iter()
        .filter(|s| s.task_id.as_deref() == Some(ta.id.as_str()))
        .collect();
    assert_eq!(heads.len(), 2);
    a.finish_turn(
        &a.snapshot().unwrap().turns.last().unwrap().id,
        "canceled",
        None,
    )
    .unwrap();
    a.resolve_task_selection(Some(ta.id), &heads[0].id).unwrap();
}
