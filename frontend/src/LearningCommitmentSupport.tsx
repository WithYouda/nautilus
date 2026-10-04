import { useState } from 'react';
import { ApiError, type PurgeReport } from './api';
import { AttachmentDialog } from './AttachmentReview';
import { organizationRequestKey } from './learning-organization-api';
import type { CommitmentCalibration } from './learning-commitment-api';

const reasons: Record<string, string> = {
  insufficient_real_execution: '真实执行记录仍少，先只安排较近的几步。', route_missing: '先明确当前学习路径。', new_context: '这个情境还需要实际尝试。',
  performance_conflict: '现有表现仍有分歧，需要先核对。', reported_burden: '已报告负担，先缩小近期范围。', comparable_effort_overrun: '可比任务实际投入较多，先留余量。',
  same_scope_supported: '同类任务已有一些可用记录。', representative_contexts_supported: '已有多个代表情境的记录。', repeated_rhythm_with_future_availability: '重复执行记录与本人可用时段支持近期日期安排。',
  future_capacity_insufficient: '给出的可用时段不足，先缩小安排。', route_paused: '先恢复学习路径。',
  performance_attempt_missing: '尚缺可用的表现尝试。', experienced_method_grain_pace_unknown: '本人对方法、大小或节奏的体验仍未知。', comparable_effective_effort_unknown: '可比任务的有效投入仍未知。',
  future_availability_missing: '未来可用时段仍未知。', availability_changed: '可用时段已变化。', route_requires_restore: '当前方向需要先恢复。', real_work_block_missing: '尚缺真实执行记录。',
  help_conditions_not_inferred: '帮助条件仍未知。', budget_and_session_span_do_not_supply_effective_effort: '预算和会话跨度不能说明有效投入。', personal_experience_missing: '本人体验尚未记录。', repeated_rhythm_or_future_capacity_unknown: '重复执行节奏或未来容量仍未知。',
};
const failures: Record<string, string> = {
  commitment_input_changed: '建议依据已变化，请重新更新近期安排。编辑内容仍保留。', commitment_source_unavailable: '相关依据已更正、隐藏或清除，请重新核对。',
  commitment_generation_running: '这个计划还有一次更新正在进行。请读取当前更新，等待或取消后再更新。',
  commitment_provider_unavailable: '请先为这个计划选择可用的 AI 模型。', provider_unavailable: 'AI 模型暂不可用，请检查计划的模型设置后重试。',
  path_generation_running: '相关对话仍在生成。请先等待或取消回答，再重新预览。已有记录保留。', path_anchor_unavailable: '原学习位置当前不可读取。可回看记录，或明确从当前可用任务开始。',
  commitment_calibration_scope: '这份建议超出了现有依据支持的范围，请重新更新。', commitment_calendar_not_supported: '当前依据只支持顺序与范围，请先保留日期未知。',
  commitment_effective_effort_unknown: '实际有效投入仍未知，请保留未知或预计范围。', commitment_capacity_exceeded: '建议超出了给出的可用时段或预算，请缩小范围。',
  commitment_ai_source_out_of_scope: '建议引用了本次输入以外的依据，请重新更新。', commitment_ai_item_out_of_scope: '建议引用了本次输入以外的任务，请重新更新。',
  invalid_json: 'AI 返回的内容无法读取，请重新更新。', invalid_proposal: 'AI 返回的安排不完整，请重新更新。', invalid_response_structure: 'AI 返回的安排格式不完整，请重新更新。',
  auth_error: '模型服务未通过授权，请检查提供方设置后重新更新。', rate_limited: '模型服务暂时限制请求，请稍后重新更新。',
  timeout: '模型服务未及时返回，可稍后重新更新。', network_error: '模型服务连接失败，请检查连接后重试。', endpoint_not_found: '模型服务地址不匹配，请检查提供方设置。', config_error: '模型配置不可用，请检查计划的模型设置。',
  request_error: '模型服务未接受这次请求，请检查模型设置后重试。', upstream_error: '模型服务暂未完成请求，可稍后重试。', output_truncated: '模型返回未完整，可重新更新或检查输出设置。', reasoning_only: '模型没有返回可用的安排，可重新更新。', content_filtered: '模型没有返回可用的安排，可重新更新。', protocol_error: '模型服务返回格式不匹配，请检查设置。', provider_error: '模型服务暂不可用，可检查连接后重试。', generation_failed: '这次建议生成未完成，可重新更新。', canceled: '已取消这次更新。',
};
export function commitmentFailure(value: unknown): string {
  const code = value instanceof ApiError ? value.kind : typeof value === 'string' ? value : '';
  return failures[code ?? ''] ?? (value instanceof Error ? value.message : typeof value === 'string' && value ? '这次建议未能完成，可重新更新。' : '操作未完成，请重试。');
}
export const commitmentConflict = (value: unknown) => value instanceof ApiError && value.status === 409 && value.kind !== 'path_generation_running' && value.kind !== 'path_anchor_unavailable';
export type CommitmentAttempt = { signature: string; key: string } | null;
export function commitmentKey(ref: { current: CommitmentAttempt }, body: unknown) {
  const signature = JSON.stringify(body);
  if (ref.current?.signature !== signature) ref.current = { signature, key: organizationRequestKey() };
  return ref.current.key;
}
export function CalibrationDetails({ value }: { value: CommitmentCalibration }) {
  const axes = { execution: '执行', performance: '表现', effort: '投入', experience: '体验', rhythm: '节奏' };
  const states = { covered: '已有依据', partial: '部分已知', unknown: '未知', conflict: '需要核对' };
  return <details className="commitment-calibration"><summary>安排范围与依据</summary><p>{value.range === 'dated' ? '支持在本人给出的时段中安排近期日期。' : value.range === 'extended' ? '已有一些同类记录，可适当多看几步。' : '先看较近的几步，再用实际记录调整。'}</p>
    {value.recommended_sessions > 0 && <p>这次建议先看 {value.recommended_sessions} 项；当前依据支持最多 {value.max_sessions} 项{value.horizon_days ? `，日期范围 ${value.horizon_days} 天` : ''}。</p>}
    <ul>{value.reason_codes.map(code => <li key={code}>{reasons[code] ?? '根据当前可用记录判断近期范围。'}</li>)}</ul>
    <dl className="commitment-axis-list">{value.axes.map(axis => <div key={axis.name}><dt>{axes[axis.name]}</dt><dd>{states[axis.state]}</dd></div>)}</dl>
    {!!value.unknowns.length && <details><summary>还不知道什么</summary><ul>{value.unknowns.map(code => <li key={code}>{reasons[code] ?? '部分可比记录仍未知。'}</li>)}</ul></details>}
    <p className="commitment-muted">只参考当前方向和可用记录；本人反馈按本人所述记录。</p>
  </details>;
}
export function CommitmentPurge({ title, description, retryNeeded, available, readStatus, purge, onDone }: {
  title: string; description: string; retryNeeded?: boolean; available: boolean; readStatus: () => Promise<PurgeReport>;
  purge: (key: string) => Promise<PurgeReport>; onDone?: () => Promise<void> | void;
}) {
  const [open, setOpen] = useState(false), [confirm, setConfirm] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(''), [report, setReport] = useState<PurgeReport | null>(null);
  async function read() { setBusy(true); setError(''); try { setReport(await readStatus()); } catch (reason) { setError(commitmentFailure(reason)); } finally { setBusy(false); } }
  async function clear() { setBusy(true); setError(''); try { setReport(await purge(organizationRequestKey())); setConfirm(false); await onDone?.(); } catch (reason) { setError(commitmentFailure(reason)); } finally { setBusy(false); } }
  if (!available) return null;
  const retry = report ? ['partial', 'pending'].includes(report.status) : retryNeeded;
  return <div className="commitment-purge"><button className="text-button" type="button" aria-expanded={open} onClick={() => { setOpen(!open); if (!open) void read(); }}>{retryNeeded ? '重查未完成的清除' : '内容清除'}</button>{open && <div>
    {busy && <p role="status">正在核对…</p>}{error && <p role="alert">{error}</p>}
    {report?.status === 'complete' ? <p>已清除管理范围内的内容。</p> : <button className="text-button text-button--danger" type="button" disabled={busy} onClick={() => setConfirm(true)}>{retry ? '重试清除' : title}</button>}
    {retry && <p>部分副本尚未清除，可重查状态或重试。</p>}{report && !!report.files.length && <details><summary>副本处理详情</summary><ul>{report.files.map((file, index) => <li key={index}>{file.name} · {file.status === 'cleared' ? '已清除' : '尚未清除'}</li>)}</ul>{report.external_limits.map((limit, index) => <p key={index}>{limit}</p>)}</details>}
    {(error || retry) && <button className="text-button" type="button" disabled={busy} onClick={() => void read()}>重新读取清除状态</button>}
  </div>}{confirm && <AttachmentDialog title={title} className="commitment-dialog commitment-purge-dialog" closeLabel="关闭清除确认" onClose={() => { if (!busy) setConfirm(false); }}><div className="commitment-dialog-body"><p>{description}</p>{error && <p role="alert">{error}</p>}</div><footer className="commitment-dialog-footer"><button className="button button--quiet" type="button" disabled={busy} onClick={() => setConfirm(false)}>取消</button><button className="button button--danger" type="button" disabled={busy} onClick={() => void clear()}>确认清除</button></footer></AttachmentDialog>}</div>;
}
