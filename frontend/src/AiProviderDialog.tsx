import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, CheckCircle2, ChevronDown, LoaderCircle, PlugZap, Plus, RefreshCw, X } from "lucide-react";
import {
  createAiProvider,
  discoverAiProviderModels,
  listAiProviders,
  testAiProviderProfile,
  testAiProvider,
  updateAiProvider,
  actionableProviderError,
  type AiProvider,
  type AiProviderInput,
} from "./api";
import DialogPortal from "./DialogPortal";
import useDismissibleLayer from "./useDismissibleLayer";

const modelCache = new Map<string, { models: string[]; savedAt: number }>();
const CLIENT_CACHE_TTL_MS = 10 * 60 * 1000;

async function cacheKey(baseUrl: string, draftKey: string) {
  const normalizedBaseUrl = baseUrl.trim().replace(/\/+$/, "");
  if (!draftKey) return `${normalizedBaseUrl}:saved`;
  if (!crypto.subtle) return "";
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(draftKey));
  const fingerprint = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${normalizedBaseUrl}:${fingerprint}`;
}

export default function AiProviderDialog({
  open,
  provider,
  onClose,
  onChanged,
}: {
  open: boolean;
  provider: AiProvider | null;
  onClose: () => void;
  onChanged: (provider: AiProvider) => void;
}) {
  const [displayName, setDisplayName] = useState("OpenAI 兼容提供方");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [isDefault, setIsDefault] = useState(false);
  const [timeoutSeconds, setTimeoutSeconds] = useState(60);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const [modelsOpen, setModelsOpen] = useState(false);
  const [testDialogOpen, setTestDialogOpen] = useState(false);
  const [testModel, setTestModel] = useState("");
  const [testedModels, setTestedModels] = useState<Set<string>>(new Set());
  const [modelNotice, setModelNotice] = useState("");
  const [error, setError] = useState("");
  const [testMessage, setTestMessage] = useState("");
  const [providerList, setProviderList] = useState<AiProvider[]>([]);
  const [selectedProviderId, setSelectedProviderId] = useState<string | null>(provider?.id ?? null);
  const [providerListLoading, setProviderListLoading] = useState(false);
  const modelBoxRef = useRef<HTMLDivElement | null>(null);

  function applyProvider(next: AiProvider | null) {
    setSelectedProviderId(next?.id ?? null);
    setDisplayName(next?.display_name ?? "OpenAI 兼容提供方");
    setBaseUrl(next?.base_url ?? "");
    setModel(next?.model ?? "");
    setApiKey("");
    setEnabled(next?.enabled ?? true);
    setIsDefault(next?.is_default ?? false);
    setTimeoutSeconds(next?.request_timeout_seconds ?? 60);
    setModels([]);
    setModelsOpen(false);
    setTestDialogOpen(false);
    setTestModel(next?.model ?? "");
    setTestedModels(next?.last_test_status === "succeeded" && next.model ? new Set([next.model]) : new Set());
    setModelNotice("");
    setError("");
    setTestMessage("");
  }

  useEffect(() => {
    if (!open) return;
    applyProvider(provider);
    setProviderListLoading(true);
    void listAiProviders()
      .then((items) => {
        setProviderList(items);
        const preferred = provider?.id ? items.find((item) => item.id === provider.id) : items.find((item) => item.is_default) ?? items[0];
        if (preferred) applyProvider(preferred);
      })
      .catch(() => setProviderList(provider ? [provider] : []))
      .finally(() => setProviderListLoading(false));
  }, [open, provider?.id]);

  const dismissModels = useCallback(() => setModelsOpen(false), []);
  useDismissibleLayer(modelsOpen, [modelBoxRef], dismissModels);

  const selectableModels = useMemo(
    () => Array.from(new Set([model.trim(), ...models].filter(Boolean))),
    [model, models],
  );
  const selectedProvider = providerList.find((item) => item.id === selectedProviderId) ?? (provider?.id === selectedProviderId ? provider : null);

  if (!open) return null;

  function runtimePayload(selectedModel?: string) {
    return {
      base_url: baseUrl.trim(),
      model: selectedModel,
      ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
      request_timeout_seconds: timeoutSeconds,
    };
  }

  async function loadModels(forceRefresh = false) {
    if (!baseUrl.trim() || (!apiKey.trim() && !selectedProvider?.has_api_key)) {
      setModelsOpen(true);
      setModelNotice("填写 Base URL 和 API Key 后可自动获取；也可以直接手动填写模型名称。");
      return;
    }
    const key = await cacheKey(baseUrl, apiKey.trim());
    const cached = key ? modelCache.get(key) : undefined;
    if (!forceRefresh && cached && Date.now() - cached.savedAt < CLIENT_CACHE_TTL_MS) {
      setModels(cached.models);
      setModelNotice(`已使用缓存的 ${cached.models.length} 个模型`);
      setModelsOpen(true);
      return;
    }
    setDiscovering(true);
    setError("");
    setModelNotice("");
    try {
      const result = await discoverAiProviderModels({
        base_url: baseUrl.trim(),
        ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
        request_timeout_seconds: timeoutSeconds,
        force_refresh: forceRefresh,
      });
      setModels(result.models);
      if (key) modelCache.set(key, { models: result.models, savedAt: Date.now() });
      setModelNotice(result.models.length
        ? `${result.cached ? "已读取缓存" : "已获取"} ${result.models.length} 个模型`
        : "提供方没有返回模型，可继续手动填写。");
      setModelsOpen(true);
    } catch (reason: unknown) {
      setModels([]);
      setModelsOpen(true);
      setModelNotice(reason instanceof Error ? `${reason.message}；仍可手动填写。` : "无法获取模型；仍可手动填写。");
    } finally {
      setDiscovering(false);
    }
  }

  function handleClose() {
    setApiKey("");
    setError("");
    setTestMessage("");
    setTestDialogOpen(false);
    onClose();
  }

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setTestMessage("");
    const payload: AiProviderInput = {
      display_name: displayName.trim() || "OpenAI 兼容提供方",
      base_url: baseUrl.trim(),
      model: model.trim(),
      enabled,
      request_timeout_seconds: timeoutSeconds,
      ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
    };
    try {
      const result = selectedProviderId
        ? await updateAiProvider(selectedProviderId, { ...payload, is_default: isDefault })
        : await createAiProvider({ ...payload, is_default: isDefault || providerList.length === 0 });
      setApiKey("");
      const nextProviders = providerList.some((item) => item.id === result.provider.id)
        ? providerList.map((item) => item.id === result.provider.id ? result.provider : item)
        : [...providerList, result.provider];
      setProviderList(nextProviders);
      onChanged(nextProviders.find((item) => item.is_default) ?? provider ?? result.provider);
      setTestMessage("配置已保存。建议连接测试通过后再开始对话。");
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "AI 提供方保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function openTestDialog() {
    setError("");
    setTestMessage("");
    setModelsOpen(false);
    if (!models.length) await loadModels(false);
    setTestModel(model.trim());
    setModelsOpen(false);
    setTestDialogOpen(true);
  }

  async function handleTest() {
    const selected = testModel.trim();
    if (!selected) {
      setError("请选择或填写要测试的模型");
      return;
    }
    setTesting(true);
    setError("");
    setTestMessage("");
    try {
      const result = selectedProviderId
        ? await testAiProviderProfile(selectedProviderId, runtimePayload(selected))
        : await testAiProvider(runtimePayload(selected));
      if (result.provider && (result.provider.is_default || !provider)) onChanged(result.provider);
      if (result.ok) {
        setTestedModels((previous) => new Set(previous).add(selected));
        setTestMessage(`连接成功 · ${result.model ?? selected} · ${result.latency_ms ?? 0} ms`);
        setTestDialogOpen(false);
      } else {
        setError(actionableProviderError(result.kind, result.message));
      }
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "AI 提供方连接测试失败");
    } finally {
      setTesting(false);
    }
  }

  return (
    <DialogPortal>
      <div className="dialog-backdrop" role="presentation" onMouseDown={handleClose}>
        <section className="ai-provider-dialog" role="dialog" aria-modal="true" aria-labelledby="ai-provider-dialog-title" onMouseDown={(event) => event.stopPropagation()}>
          <header className="dialog-header">
            <div><p className="eyebrow">AI SETTINGS</p><h2 id="ai-provider-dialog-title">AI 提供方设置</h2></div>
            <button className="icon-button" type="button" onClick={handleClose} aria-label="关闭 AI 提供方设置" title="关闭"><X size={18} /></button>
          </header>

          <div className="ai-provider-list" aria-label="已配置的 AI 提供方">
            <div className="ai-provider-list-header"><span>已配置提供方</span><button type="button" className="button button--quiet button--with-icon" onClick={() => applyProvider(null)}><Plus size={14} />新增</button></div>
            {providerListLoading ? <p className="form-hint">正在加载提供方…</p> : providerList.length === 0 ? <p className="form-hint">还没有保存的提供方。</p> : <div className="ai-provider-list-items">
              {providerList.map((item) => <button key={item.id} type="button" className={`ai-provider-list-item ${selectedProviderId === item.id ? "is-selected" : ""}`} onClick={() => applyProvider(item)}>
                <span><strong>{item.display_name}</strong><small>{item.model}{item.is_default ? " · 默认" : ""}</small></span><span className={`ai-provider-list-status ${item.enabled && item.has_api_key ? "is-ready" : ""}`}>{item.enabled && item.has_api_key ? "可用" : "需配置"}</span>
              </button>)}
            </div>}
          </div>

          <form className="ai-provider-form" onSubmit={handleSave}>
            <div className="field-grid field-grid--two">
              <label className="field"><span>显示名称</span><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} maxLength={80} /></label>
              <label className="field"><span>启用状态</span><select value={enabled ? "enabled" : "disabled"} onChange={(event) => setEnabled(event.target.value === "enabled")}><option value="enabled">启用</option><option value="disabled">停用</option></select></label>
              <label className="field"><span>默认提供方</span><select value={isDefault ? "default" : "normal"} onChange={(event) => setIsDefault(event.target.value === "default")}><option value="normal">否</option><option value="default">是</option></select></label>
              <label className="field field--wide"><span>Base URL</span><input type="url" value={baseUrl} onChange={(event) => { setBaseUrl(event.target.value); setModels([]); setModelNotice(""); }} placeholder="https://api.example.com/v1" maxLength={300} required /></label>
              <div className="field ai-model-field" ref={modelBoxRef}>
                <span>模型</span>
                <div className="ai-model-combobox">
                  <input
                    role="combobox"
                    aria-label="模型"
                    aria-expanded={modelsOpen}
                    aria-controls="ai-model-options"
                    value={model}
                    onChange={(event) => setModel(event.target.value)}
                    onFocus={() => void loadModels(false)}
                    placeholder="选择或手动填写模型"
                    maxLength={120}
                    required
                  />
                  {testedModels.has(model.trim()) && <span className="ai-model-tested" aria-label="该模型连接测试成功"><Check size={12} /></span>}
                  <button type="button" className="ai-model-toggle" onClick={() => void loadModels(false)} aria-label="展开模型列表">{discovering ? <LoaderCircle size={15} className="ai-status-spinner" /> : <ChevronDown size={15} />}</button>
                </div>
                {modelsOpen && (
                  <div className="ai-model-options" id="ai-model-options" role="listbox">
                    <div className="ai-model-options-meta"><span>{modelNotice || "选择模型或继续手动输入"}</span><button type="button" onClick={() => void loadModels(true)} disabled={discovering}><RefreshCw size={12} />刷新</button></div>
                    {models.map((item) => (
                      <button key={item} type="button" role="option" aria-selected={item === model} onClick={() => { setModel(item); setModelsOpen(false); }}>
                        <span>{item}</span>{testedModels.has(item) && <span className="ai-model-tested"><Check size={12} /></span>}
                      </button>
                    ))}
                    <button type="button" className="ai-model-manual" onClick={() => setModelsOpen(false)}>手动填写其他模型名称</button>
                  </div>
                )}
              </div>
              <label className="field"><span>超时（秒）</span><input type="number" min="5" max="600" value={timeoutSeconds} onChange={(event) => setTimeoutSeconds(Number(event.target.value))} required /></label>
              <label className="field field--wide"><span>API Key</span><input type="password" value={apiKey} onChange={(event) => { setApiKey(event.target.value); setModels([]); setModelNotice(""); }} placeholder={selectedProvider?.has_api_key ? `已保存 ${selectedProvider.api_key_masked}；留空则保留` : "首次配置必须填写"} autoComplete="off" required={!selectedProvider?.has_api_key} /></label>
            </div>

            <p className="form-hint">点击模型输入框会从 Base URL 获取模型并缓存；获取失败时仍可手动填写。密钥只交给本地服务处理。</p>
            <p className="form-hint">联网搜索尚未接入。模型官网的搜索功能不会随 API 自动启用；当前回答和出题不包含实时检索。</p>
            {provider?.credential_error && <p className="form-error" role="alert">{provider.credential_error}</p>}
            {error && <p className="form-error" role="alert">{error}</p>}

            <footer className="dialog-actions ai-provider-actions">
              <button className="button button--quiet button--with-icon" type="button" disabled={testing || saving || (!apiKey.trim() && !selectedProvider?.has_api_key)} onClick={() => void openTestDialog()}><PlugZap size={15} />连接测试</button>
              {testMessage && <p className="ai-provider-success" role="status"><CheckCircle2 size={16} />{testMessage}</p>}
              <span className="ai-provider-action-spacer" />
              <button className="button button--quiet" type="button" onClick={handleClose}>取消</button>
              <button className="button button--dark" disabled={saving}>{saving ? "正在保存" : "保存配置"}</button>
            </footer>
          </form>
        </section>

        {testDialogOpen && (
          <section className="ai-model-test-dialog" role="dialog" aria-modal="true" aria-labelledby="ai-model-test-title" onMouseDown={(event) => event.stopPropagation()}>
            <header className="dialog-header"><div><p className="eyebrow">CONNECTION TEST</p><h2 id="ai-model-test-title">选择要测试的模型</h2></div><button className="icon-button" type="button" onClick={() => setTestDialogOpen(false)} aria-label="关闭模型测试"><X size={18} /></button></header>
            <div className="ai-model-test-body">
              <p>选择一个已发现模型，或在下方直接填写模型名称。本次测试不会自动保存配置。</p>
              {modelNotice && <p className="form-hint ai-model-test-notice" role="status">{modelNotice}</p>}
              <div className="ai-model-test-grid">
                {selectableModels.map((item) => <button key={item} type="button" className={testModel === item ? "is-selected" : ""} onClick={() => setTestModel(item)}><span>{item}</span>{testedModels.has(item) && <span className="ai-model-tested"><Check size={12} /></span>}</button>)}
              </div>
              <label className="field"><span>测试模型</span><input value={testModel} onChange={(event) => setTestModel(event.target.value)} placeholder="也可以手动填写" maxLength={120} /></label>
              <div className="dialog-actions"><button className="button button--quiet" type="button" onClick={() => setTestDialogOpen(false)}>取消</button><button className="button button--dark button--with-icon" type="button" disabled={testing || !testModel.trim()} onClick={() => void handleTest()}>{testing ? <LoaderCircle size={15} className="ai-status-spinner" /> : <PlugZap size={15} />}{testing ? "正在测试" : "测试所选模型"}</button></div>
            </div>
          </section>
        )}
      </div>
    </DialogPortal>
  );
}
