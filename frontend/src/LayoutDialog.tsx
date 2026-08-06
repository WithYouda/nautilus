import { FormEvent, useEffect, useState } from "react";
import { ArrowDown, ArrowUp, Pencil, Trash2, X } from "lucide-react";
import {
  applyLayoutTemplate,
  deleteLayoutTemplate,
  renameLayoutTemplate,
  saveLayoutTemplate,
  updateLayout,
  type LayoutConfig,
  type LayoutModule,
  type LayoutModuleId,
  type LayoutTemplate,
} from "./api";
import DialogPortal from "./DialogPortal";

const moduleLabels: Record<LayoutModuleId, { title: string; detail: string }> = {
  summary: { title: "今日概览", detail: "任务、时长和完成进度" },
  tasks: { title: "今日任务", detail: "当天可执行任务队列" },
  timer: { title: "专注计时", detail: "番茄钟与普通计时" },
  context: { title: "任务位置", detail: "目标到任务的四层路径" },
};

export default function LayoutDialog({
  open,
  layout,
  templates,
  onClose,
  onChanged,
}: {
  open: boolean;
  layout: LayoutConfig;
  templates: LayoutTemplate[];
  onClose: () => void;
  onChanged: (layout: LayoutConfig, templates?: LayoutTemplate[]) => void;
}) {
  const [modules, setModules] = useState<LayoutModule[]>(layout.modules);
  const [templateName, setTemplateName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) setModules(layout.modules.map((module) => ({ ...module })));
  }, [open, layout.modules]);

  if (!open) return null;

  function move(index: number, offset: -1 | 1) {
    setModules((current) => {
      const target = index + offset;
      if (target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "布局操作失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveLayout() {
    await run(async () => {
      const next = await updateLayout(modules);
      onChanged(next);
      onClose();
    });
  }

  async function handleSaveTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await run(async () => {
      const nextLayout = await updateLayout(modules);
      const saved = await saveLayoutTemplate(templateName.trim());
      setTemplateName("");
      onChanged(nextLayout, [...templates, saved]);
    });
  }

  return (
    <DialogPortal>
      <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}>
        <section className="layout-dialog" role="dialog" aria-modal="true" aria-labelledby="layout-dialog-title" onMouseDown={(event) => event.stopPropagation()}>
        <header className="dialog-header">
          <div><p className="eyebrow">首页设置</p><h2 id="layout-dialog-title">驾驶舱布局</h2></div>
          <button className="icon-button" onClick={onClose} title="关闭" aria-label="关闭"><X size={18} /></button>
        </header>

        <div className="layout-dialog-body">
          <section className="layout-section">
            <div className="layout-section-heading"><h3>模块</h3><span>显示与顺序</span></div>
            <div className="module-settings">
              {modules.map((module, index) => (
                <div className="module-setting" key={module.id}>
                  <label className="visibility-toggle">
                    <input
                      type="checkbox"
                      checked={module.visible}
                      onChange={(event) => setModules((current) => current.map((item) => item.id === module.id ? { ...item, visible: event.target.checked } : item))}
                    />
                    <span><strong>{moduleLabels[module.id].title}</strong><small>{moduleLabels[module.id].detail}</small></span>
                  </label>
                  <div className="order-actions">
                    <button className="icon-button icon-button--bordered" disabled={index === 0} onClick={() => move(index, -1)} title="上移" aria-label={`${moduleLabels[module.id].title}上移`}><ArrowUp size={15} /></button>
                    <button className="icon-button icon-button--bordered" disabled={index === modules.length - 1} onClick={() => move(index, 1)} title="下移" aria-label={`${moduleLabels[module.id].title}下移`}><ArrowDown size={15} /></button>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="layout-section">
            <div className="layout-section-heading"><h3>布局模板</h3><span>应用后仍可继续修改</span></div>
            <div className="template-list">
              {templates.map((template) => (
                <div className="template-row" key={template.id}>
                  {editingId === template.id ? (
                    <input className="template-name-input" value={editingName} onChange={(event) => setEditingName(event.target.value)} autoFocus />
                  ) : (
                    <span className="template-name"><strong>{template.name}</strong><small>{template.is_system ? "系统模板" : "个人模板"}</small></span>
                  )}
                  <div className="template-actions">
                    {editingId === template.id ? (
                      <button className="button button--quiet" disabled={busy || !editingName.trim()} onClick={() => void run(async () => {
                        const renamed = await renameLayoutTemplate(template.id, editingName.trim());
                        onChanged(layout, templates.map((item) => item.id === renamed.id ? renamed : item));
                        setEditingId(null);
                      })}>保存</button>
                    ) : (
                      <button className="button button--quiet" disabled={busy} onClick={() => void run(async () => {
                        const next = await applyLayoutTemplate(template.id);
                        setModules(next.modules);
                        onChanged(next);
                      })}>应用</button>
                    )}
                    {!template.is_system && editingId !== template.id && (
                      <>
                        <button className="icon-button" onClick={() => { setEditingId(template.id); setEditingName(template.name); }} title="重命名" aria-label={`重命名${template.name}`}><Pencil size={15} /></button>
                        <button className="icon-button" disabled={busy} onClick={() => void run(async () => {
                          await deleteLayoutTemplate(template.id);
                          onChanged(layout, templates.filter((item) => item.id !== template.id));
                        })} title="删除模板" aria-label={`删除${template.name}`}><Trash2 size={15} /></button>
                      </>
                    )}
                  </div>
                </div>
              ))}
            </div>
            <form className="save-template-form" onSubmit={handleSaveTemplate}>
              <input value={templateName} onChange={(event) => setTemplateName(event.target.value)} placeholder="个人模板名称" maxLength={80} required />
              <button className="button button--quiet" disabled={busy || !templateName.trim()}>另存为模板</button>
            </form>
          </section>

          {error && <p className="form-error layout-error" role="alert">{error}</p>}
        </div>
        <footer className="layout-dialog-actions">
          <button className="button button--quiet" onClick={onClose}>取消</button>
          <button className="button button--dark" disabled={busy} onClick={() => void handleSaveLayout()}>{busy ? "正在保存" : "保存布局"}</button>
        </footer>
        </section>
      </div>
    </DialogPortal>
  );
}
