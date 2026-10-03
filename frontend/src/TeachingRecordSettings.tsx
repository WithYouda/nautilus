import { useEffect, useRef, useState } from 'react';
import {
  ApiError, checkTeachingSupport, getTeachingSupport, listAiProviders,
  type AiProvider, type TeachingSupport, type TeachingSupportState,
} from './api';

const supportLabels: Record<TeachingSupportState, string> = {
  supported: '可记录', unchecked: '未检查', unavailable: '暂不可记录',
};

function checkFailure(kinds: string[]): string {
  if (kinds.includes('auth_error')) return '提供方拒绝了检查，请核对凭据与模型权限。';
  if (kinds.includes('timeout')) return '检查超时，可稍后重试。';
  if (kinds.includes('network_error')) return '检查未能连接提供方，可稍后重试。';
  if (kinds.includes('rate_limited')) return '提供方暂时限制了请求，可稍后重试。';
  return '部分检查未完成，可稍后重试。';
}

export default function TeachingRecordSettings({ provider }: { provider: AiProvider | null }) {
  const [expanded, setExpanded] = useState(false);
  const [providers, setProviders] = useState<AiProvider[]>([]);
  const [modelKey, setModelKey] = useState('');
  const [support, setSupport] = useState<TeachingSupport | null>(null);
  const [loadingModels, setLoadingModels] = useState(false);
  const [loadingSupport, setLoadingSupport] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const generation = useRef(0);
  const pending = useRef<AbortController | null>(null);
  const models = providers.flatMap(profile => (profile.models ?? []).filter(model =>
    profile.enabled && profile.has_api_key && !profile.credential_error && model.enabled && model.discovery_status !== 'unavailable')
    .map(model => ({ provider: profile, model, key: `${profile.id}::${model.id}` })));
  const selected = models.find(item => item.key === modelKey);

  useEffect(() => {
    if (!expanded) return;
    let active = true;
    setLoadingModels(true); setError('');
    void listAiProviders().then(profiles => {
      if (!active) return;
      setProviders(profiles);
      const usable = profiles.flatMap(profile => (profile.models ?? []).filter(model =>
        profile.enabled && profile.has_api_key && !profile.credential_error && model.enabled && model.discovery_status !== 'unavailable')
        .map(model => ({ profile, model, key: `${profile.id}::${model.id}` })));
      setModelKey(previous => usable.some(item => item.key === previous) ? previous :
        usable.find(item => item.profile.id === provider?.id && item.model.id === provider.default_model_id)?.key ??
        usable.find(item => item.profile.is_default && item.model.id === item.profile.default_model_id)?.key ??
        usable[0]?.key ?? '');
    }).catch(reason => { if (active) setError(reason instanceof Error ? reason.message : '无法读取模型。'); })
      .finally(() => { if (active) setLoadingModels(false); });
    return () => { active = false; };
  }, [expanded, provider?.id, provider?.default_model_id]);

  useEffect(() => {
    const epoch = ++generation.current;
    pending.current?.abort(); pending.current = null;
    setSupport(null); setNotice(''); setBusy(false); setLoadingSupport(false);
    if (!expanded || !modelKey) return;
    const [providerId, modelId] = modelKey.split('::');
    const controller = new AbortController();
    pending.current = controller;
    setLoadingSupport(true); setError('');
    void getTeachingSupport(providerId, modelId, controller.signal).then(value => {
      if (epoch === generation.current && !controller.signal.aborted) setSupport(value);
    }).catch(reason => {
      if (epoch === generation.current && !controller.signal.aborted)
        setError(reason instanceof Error ? reason.message : '无法读取教学记录支持。');
    }).finally(() => {
      if (epoch === generation.current && !controller.signal.aborted) setLoadingSupport(false);
      if (pending.current === controller) pending.current = null;
    });
    return () => { ++generation.current; controller.abort(); };
  }, [expanded, modelKey]);

  useEffect(() => () => { ++generation.current; pending.current?.abort(); }, []);

  async function check() {
    if (!selected || busy || loadingSupport) return;
    const epoch = ++generation.current;
    const controller = new AbortController();
    pending.current?.abort(); pending.current = controller;
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await checkTeachingSupport(selected.provider.id, selected.model.id, controller.signal);
      if (epoch !== generation.current || controller.signal.aborted) return;
      setSupport(result.support);
      const failures = Object.values(result.failures);
      setNotice(failures.length ? `${checkFailure(failures)}${result.updated ? '' : '已保留此前结果。'}` : '检查已完成。');
    } catch (reason) {
      if (epoch !== generation.current || controller.signal.aborted) return;
      setError(reason instanceof ApiError && reason.status === 409 ? reason.message :
        reason instanceof Error ? reason.message : '检查未完成，请稍后重试。');
    } finally {
      if (epoch === generation.current && !controller.signal.aborted) setBusy(false);
      if (pending.current === controller) pending.current = null;
    }
  }

  return <details className="teaching-record-settings" onToggle={event => {
    const next = event.currentTarget.open;
    if (!next) { ++generation.current; pending.current?.abort(); }
    setExpanded(next);
  }}>
    <summary>教学记录</summary>
    {expanded && <>
      {loadingModels ? <p role="status">正在读取模型…</p> : models.length ? <>
        <label className="field"><span>检查模型</span><select aria-label="检查模型" value={modelKey} onChange={event => {
          ++generation.current; pending.current?.abort(); setModelKey(event.target.value); setError('');
        }}>{models.map(item => <option key={item.key} value={item.key}>{item.provider.display_name} · {item.model.display_name}</option>)}</select></label>
        {loadingSupport ? <p role="status">正在读取支持状态…</p> : support && <>
          <p>普通对话：{supportLabels[support.plain]}<br />外部搜索和知识库：{supportLabels[support.tools]}</p>
        </>}
        <button className="button button--quiet" type="button" disabled={!selected || loadingSupport || busy} onClick={() => void check()}>{busy ? '正在检查…' : '检查支持'}</button>
        <small className="form-hint">发送两次简短检查，不使用对话内容。</small>
      </> : <p>请先在提供方设置中添加可用模型。</p>}
      {error && <p className="form-error" role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
    </>}
  </details>;
}
