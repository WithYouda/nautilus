import { AlertTriangle, Save } from "lucide-react";
import DialogPortal from "./DialogPortal";

export default function UnsavedChangesDialog({
  busy,
  onSave,
  onDiscard,
  onContinue,
}: {
  busy: boolean;
  onSave: () => void;
  onDiscard: () => void;
  onContinue: () => void;
}) {
  return (
    <DialogPortal>
      <div className="dialog-backdrop" role="presentation">
        <section className="confirm-dialog unsaved-dialog" role="dialog" aria-modal="true" aria-labelledby="unsaved-title">
          <div className="confirm-icon confirm-icon--warning"><AlertTriangle size={20} /></div>
          <h2 id="unsaved-title">当前修改还没有保存</h2>
          <p>保存后继续当前操作，或放弃本次修改。选择继续编辑会留在当前节点。</p>
          <div className="confirm-actions confirm-actions--three">
            <button className="button button--quiet" type="button" disabled={busy} onClick={onContinue}>继续编辑</button>
            <button className="button button--danger" type="button" disabled={busy} onClick={onDiscard}>放弃修改</button>
            <button className="button button--accent button--with-icon" type="button" disabled={busy} onClick={onSave}>
              <Save size={15} />{busy ? "保存中" : "保存并继续"}
            </button>
          </div>
        </section>
      </div>
    </DialogPortal>
  );
}
