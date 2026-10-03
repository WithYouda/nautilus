import { useEffect, useId, useRef, useState } from 'react';
import { getMaterialOcrSettings, listAiProviders, saveMaterialOcrSettings, setModelImageCapability, type AiProvider, type MaterialOcrSettings } from './api';
import { attachmentError } from './AttachmentSupport';
import './styles/composer-attachments.css';

export default function ImageModelSettings() {
  const [providers, setProviders] = useState<AiProvider[]>([]);
  const [ocr, setOcr] = useState<MaterialOcrSettings>({ provider_profile_id: null, provider_model_id: null });
  const [modelKey, setModelKey] = useState('');
  const [support, setSupport] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const mounted = useRef(true);
  const prefix = useId();
  useEffect(() => {
    mounted.current = true;
    void Promise.all([listAiProviders(), getMaterialOcrSettings()]).then(([profiles, settings]) => { if (mounted.current) { setProviders(profiles); setOcr(settings); } })
      .catch(reason => { if (mounted.current) setError(attachmentError(reason)); }).finally(() => { if (mounted.current) setLoading(false); });
    return () => { mounted.current = false; };
  }, []);
  const models = providers.flatMap(provider => (provider.models ?? []).map(model => ({ provider, model, key: `${provider.id}::${model.id}` })));
  const selected = models.find(item => item.key === modelKey);
  async function declare() {
    if (!selected) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await setModelImageCapability(selected.provider.id, selected.model.id, support === '' ? null : support === 'true');
      if (!mounted.current) return;
      setProviders(previous => previous.map(provider => provider.id !== selected.provider.id ? provider : { ...provider, models: provider.models?.map(model => model.id === result.model.id ? result.model : model) }));
      setNotice('图片能力声明已保存。此声明不代表已成功测试模型。'); window.dispatchEvent(new Event('nautilus:image-settings-changed'));
    } catch (reason) { if (mounted.current) setError(attachmentError(reason)); }
    finally { if (mounted.current) setBusy(false); }
  }
  async function saveOcr() {
    setBusy(true); setError(''); setNotice('');
    try {
      const saved = await saveMaterialOcrSettings(ocr);
      if (!mounted.current) return;
      setOcr(saved); setNotice('识别模型已保存。开始识别时才会调用，不会改变对话模型。'); window.dispatchEvent(new Event('nautilus:image-settings-changed'));
    } catch (reason) { if (mounted.current) setError(attachmentError(reason)); }
    finally { if (mounted.current) setBusy(false); }
  }
  return <section className="image-model-settings" aria-label="图片与 OCR 模型">
    <h3>图片与 OCR 模型</h3>
    <p>按模型文档确认图片输入能力。对话模型仍由你在学习室选择；识别模型单独设置。</p>
    {loading ? <p role="status">正在读取模型…</p> : <>
      <label htmlFor={`${prefix}-model`}>确认模型图片能力</label><select id={`${prefix}-model`} value={modelKey} disabled={busy} onChange={event => {
        setModelKey(event.target.value); const next = models.find(item => item.key === event.target.value); const value = next?.model.capabilities.supports_image_input;
        setSupport(value == null ? '' : String(value)); setNotice('');
      }}><option value="">选择要确认的模型</option>{models.map(({ provider, model, key }) => <option key={key} value={key}>{provider.display_name} · {model.display_name} · {model.capabilities.supports_image_input == null ? '图片能力未确认' : model.capabilities.supports_image_input ? '支持图片' : '不支持图片'}</option>)}</select>
      {selected && <><label htmlFor={`${prefix}-support`}>图片输入能力</label><select id={`${prefix}-support`} value={support} disabled={busy} onChange={event => setSupport(event.target.value)}><option value="">图片能力未确认</option><option value="true">支持图片输入</option><option value="false">不支持图片输入</option></select><button className="button button--quiet" type="button" disabled={busy} onClick={() => void declare()}>保存图片能力声明</button></>}
      <label htmlFor={`${prefix}-ocr`}>单独用于 OCR 的模型</label><select id={`${prefix}-ocr`} value={ocr.provider_profile_id && ocr.provider_model_id ? `${ocr.provider_profile_id}::${ocr.provider_model_id}` : ''} disabled={busy} onChange={event => {
        const [provider, model] = event.target.value.split('::'); setOcr({ provider_profile_id: provider || null, provider_model_id: model || null });
      }}><option value="">暂不设置</option>{models.filter(({ provider, model }) => provider.enabled && provider.has_api_key && model.enabled && model.discovery_status !== 'unavailable' && model.capabilities.supports_image_input === true).map(({ provider, model, key }) => <option key={key} value={key}>{provider.display_name} · {model.display_name}</option>)}</select>
      <small>只有明确支持图片且可用的模型能用于 OCR。识别文字不等于理解图表或核实内容。</small>
      <button className="button button--quiet" type="button" disabled={busy} onClick={() => void saveOcr()}>保存 OCR 模型</button>
    </>}
    {error && <p className="form-error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
  </section>;
}
