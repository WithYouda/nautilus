import { expect, test, type Page } from '@playwright/test';
import { authorize } from './fact-helpers';

const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAIAAABvFaqvAAAAIklEQVR4nGP8//8/AzUAE1VMGTVo1KBRg0YNGjVo1CCKAAAZ0QMtxqFhfwAAAABJRU5ErkJggg==', 'base64');
const readablePdf = Buffer.from('JVBERi0xLjMKJeLjz9MKMSAwIG9iago8PAovUHJvZHVjZXIgKHB5cGRmKQo+PgplbmRvYmoKMiAwIG9iago8PAovVHlwZSAvUGFnZXMKL0NvdW50IDEKL0tpZHMgWyA0IDAgUiBdCj4+CmVuZG9iagozIDAgb2JqCjw8Ci9UeXBlIC9DYXRhbG9nCi9QYWdlcyAyIDAgUgo+PgplbmRvYmoKNCAwIG9iago8PAovVHlwZSAvUGFnZQovUmVzb3VyY2VzIDw8Ci9Gb250IDw8Ci9GMSA1IDAgUgo+Pgo+PgovTWVkaWFCb3ggWyAwLjAgMC4wIDIyMCAxNjAgXQovUGFyZW50IDIgMCBSCi9Db250ZW50cyA2IDAgUgo+PgplbmRvYmoKNSAwIG9iago8PAovVHlwZSAvRm9udAovU3VidHlwZSAvVHlwZTEKL0Jhc2VGb250IC9IZWx2ZXRpY2EKPj4KZW5kb2JqCjYgMCBvYmoKPDwKL0xlbmd0aCA1Mwo+PgpzdHJlYW0KQlQgL0YxIDEyIFRmIDE1IDEwMCBUZCAoU3ludGhldGljIHJlYWRhYmxlIFBERikgVGogRVQKZW5kc3RyZWFtCmVuZG9iagp4cmVmCjAgNwowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAwMTUgMDAwMDAgbiAKMDAwMDAwMDA1NCAwMDAwMCBuIAowMDAwMDAwMTEzIDAwMDAwIG4gCjAwMDAwMDAxNjIgMDAwMDAgbiAKMDAwMDAwMDI5NCAwMDAwMCBuIAowMDAwMDAwMzY0IDAwMDAwIG4gCnRyYWlsZXIKPDwKL1NpemUgNwovUm9vdCAzIDAgUgovSW5mbyAxIDAgUgo+PgpzdGFydHhyZWYKNDY3CiUlRU9GCg==', 'base64');
const image = (name = '合成图片.png') => ({ name, mimeType: 'image/png', buffer: png });
async function configure(page: Page, model = 'mock-success') {
  expect((await page.request.put('/api/ai/provider', { data: { display_name: 'Attachment synthetic provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL, model, api_key: 'synthetic-attachment-key', enabled: true, request_timeout_seconds: 15, api_protocol: 'openai_compatible' } })).ok()).toBeTruthy();
  const providers = await (await page.request.get('/api/ai/providers')).json();
  const provider = providers.find((item: { enabled: boolean }) => item.enabled);
  const selected = provider.models.find((item: { model_id: string }) => item.model_id === model);
  expect(selected).toBeTruthy();
  return { provider, model: selected };
}
async function room(page: Page) {
  await page.reload(); await page.getByRole('button', { name: '学习室', exact: true }).click();
  await expect(page.locator('.ai-composer').getByRole('button', { name: '添加图片或文件' })).toBeEnabled();
  await page.getByRole('button', { name: '新建对话', exact: true }).click();
}
async function uploadImage(page: Page, name = '合成图片.png') {
  const composer = page.locator('.ai-composer:visible').last();
  await composer.getByRole('button', { name: '添加图片或文件' }).click();
  await expect(composer.getByRole('button', { name: '上传图片', exact: true })).toBeVisible();
  const request = page.waitForResponse(response => /\/api\/materials\/(conversation|discussion)\/[^/]+\/upload$/.test(response.url()) && response.request().method() === 'POST');
  await composer.getByLabel('选择上传图片').setInputFiles(image(name));
  const response = await request; expect(response.ok()).toBeTruthy();
  const saved = await response.json();
  await expect(composer.locator('.composer-attachment-card').filter({ hasText: name })).toContainText('当前参考');
  return saved;
}

test('left attachment picker, direct image model, original history and cancel reference', async ({ page }) => {
  test.setTimeout(90_000);
  const schema = await (await page.request.get(`http://127.0.0.1:${process.env.NAUTILUS_E2E_BACKEND_PORT ?? '8012'}/openapi.json`)).json();
  for (const path of ['/api/material-ocr/settings', '/api/material-ocr/{kind}/{scope_id}/versions/{version_id}', '/api/ai/providers/{provider_id}/models/{model_id}/image-capability']) expect(schema.paths[path]).toBeTruthy();
  await authorize(page); const config = await configure(page);
  expect((await page.request.put(`/api/ai/providers/${config.provider.id}/models/${config.model.id}/image-capability`, { data: { supports_image_input: null } })).ok()).toBeTruthy();
  expect((await page.request.put('/api/material-ocr/settings', { data: { provider_profile_id: null, provider_model_id: null } })).ok()).toBeTruthy();
  await room(page);
  let ocrStarts = 0; let purges = 0;
  page.on('request', request => { if (request.method() === 'POST' && /\/api\/material-ocr\/.*\/versions\/[^/]+$/.test(request.url())) ocrStarts++; if (request.method() === 'POST' && /\/purge$/.test(request.url())) purges++; });
  await page.getByRole('button', { name: '添加图片或文件' }).click(); await page.keyboard.press('Escape'); await expect(page.getByRole('button', { name: '添加图片或文件' })).toBeFocused();
  const saved = await uploadImage(page);
  expect(saved.content).toBeNull(); expect(saved.attachment.mode).toBe('image'); expect(ocrStarts).toBe(0);
  const scopeId = (await (await page.request.get('/api/ai/conversations')).json())[0].id;
  const plusBox = (await page.getByRole('button', { name: '添加图片或文件' }).boundingBox())!;
  const inputBox = (await page.getByLabel('输入学习问题').boundingBox())!;
  expect(plusBox.x + plusBox.width).toBeLessThan(inputBox.x);
  await expect(page.locator('.attachment-model-hint')).toContainText('图片能力未确认');
  await page.getByLabel('输入学习问题').fill('请直接看图');
  const rejected = page.waitForResponse(response => response.url().endsWith('/messages') && response.request().method() === 'POST');
  await page.getByLabel('输入学习问题').press('Enter'); expect((await rejected).status()).toBe(400);
  await expect(page.getByRole('alert').filter({ hasText: /图片.*未确认/ })).toBeVisible();
  await page.locator('.attachment-model-hint').getByRole('button', { name: '图片与 OCR 模型设置' }).click();
  const settings = page.getByRole('dialog', { name: '图片与 OCR 模型设置', exact: true });
  await settings.getByLabel('确认模型图片能力').selectOption(`${config.provider.id}::${config.model.id}`);
  await settings.getByLabel('图片输入能力').selectOption('true');
  await settings.getByRole('button', { name: '保存图片能力声明' }).click();
  await expect(settings.getByRole('status')).toContainText('声明不代表已成功测试');
  await page.keyboard.press('Escape');
  await expect(page.locator('.attachment-model-hint')).toContainText('当前模型支持图片');
  await page.locator('.ai-composer').screenshot({ path: '/tmp/nautilus-b3-composer-desktop.png' });
  await page.setViewportSize({ width: 390, height: 720 });
  const mobilePlus = (await page.getByRole('button', { name: '添加图片或文件' }).boundingBox())!; const mobileInput = (await page.getByLabel('输入学习问题').boundingBox())!; expect(mobilePlus.x + mobilePlus.width).toBeLessThan(mobileInput.x);
  await page.locator('.ai-composer').screenshot({ path: '/tmp/nautilus-b3-composer-mobile.png' });
  await page.setViewportSize({ width: 1280, height: 720 });
  const sent = page.waitForResponse(response => response.url().endsWith('/messages') && response.request().method() === 'POST');
  await page.getByLabel('输入学习问题').press('Enter'); expect((await sent).ok()).toBeTruthy();
  await expect.poll(async () => (await (await page.request.get(`/api/ai/conversations/${scopeId}`)).json()).active_run).toBeNull();
  const use = page.locator('.task-material-use').last(); await use.getByText(/本回答资料范围/).click();
  await use.getByText('查看保存的版本', { exact: true }).click();
  await use.getByRole('button', { name: '查看本次保存的原件与页面' }).click();
  const preview = page.getByRole('dialog', { name: /原件与保存版本/ });
  await expect(preview.locator('img')).toHaveAttribute('src', new RegExp(`/versions/${saved.id}/preview/1$`));
  await preview.screenshot({ path: '/tmp/nautilus-b3-attachment-original-desktop.png' });
  await page.keyboard.press('Escape'); await expect(use.getByRole('button', { name: '查看本次保存的原件与页面' })).toBeFocused();
  await page.locator('.composer-attachment-card').getByRole('button', { name: '取消参考' }).click();
  await expect(page.locator('.composer-attachment-card')).toContainText('已保存，未参考'); expect(purges).toBe(0);
  expect((await page.request.get(`/api/materials/conversation/${scopeId}/versions/${saved.id}/original`)).ok()).toBeTruthy();
  await page.reload(); await expect(page.locator('.composer-attachment-card')).toContainText('已保存，未参考');
});

test('OCR starts only explicitly, requires separate settings, editable reviewed derivative preserves original', async ({ page }) => {
  test.setTimeout(90_000);
  await authorize(page); const config = await configure(page);
  expect((await page.request.put(`/api/ai/providers/${config.provider.id}/models/${config.model.id}/image-capability`, { data: { supports_image_input: true } })).ok()).toBeTruthy();
  expect((await page.request.put('/api/material-ocr/settings', { data: { provider_profile_id: null, provider_model_id: null } })).ok()).toBeTruthy();
  await room(page); const saved = await uploadImage(page, '合成核对图.png');
  await page.locator('.composer-attachment-card').getByRole('button', { name: '识别与核对文字' }).click();
  const review = page.getByRole('dialog', { name: '识别与核对文字 · 合成核对图.png' });
  await expect(review.getByRole('button', { name: '确认文字并参考' })).toHaveCount(0);
  await review.getByRole('button', { name: '开始识别文字' }).click();
  await expect(review.getByRole('alert')).toContainText('请先在');
  await review.getByLabel('单独用于 OCR 的模型').selectOption(`${config.provider.id}::${config.model.id}`);
  await review.getByRole('button', { name: '保存 OCR 模型' }).click();
  await expect(review.getByRole('status')).toContainText('不会改变对话模型');
  await review.getByRole('button', { name: '开始识别文字' }).click();
  await expect(review.getByLabel('第 1 页文字')).toBeEnabled({ timeout: 15_000 });
  await review.getByLabel('第 1 页文字').fill('人工核对后的合成文字');
  await expect(review.getByRole('button', { name: '确认文字并参考' })).toBeDisabled();
  await review.getByRole('checkbox', { name: '我已对照原件核对第 1 页' }).check();
  await review.screenshot({ path: '/tmp/nautilus-b3-attachment-ocr-desktop.png' });
  await page.setViewportSize({ width: 390, height: 720 });
  await review.getByRole('button', { name: '确认文字并参考' }).scrollIntoViewIfNeeded();
  const box = (await review.boundingBox())!; expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x + box.width).toBeLessThanOrEqual(390);
  await review.screenshot({ path: '/tmp/nautilus-b3-attachment-ocr-mobile.png' });
  const confirmed = page.waitForResponse(response => response.url().endsWith('/confirm') && response.request().method() === 'POST');
  await review.getByRole('button', { name: '确认文字并参考' }).click(); const derived = await (await confirmed).json();
  expect(derived.attachment.origin).toBe('ocr'); expect(derived.attachment.source_version_id).toBe(saved.id);
  await expect(review.getByRole('status').filter({ hasText: '已保存核对后的文字版本' })).toBeVisible();
  await page.keyboard.press('Escape');
  const card = page.locator('.composer-attachment-card'); await expect(card).toContainText('已核对的 OCR 文字（派生版本）'); await expect(card).toContainText('当前参考');
  await card.getByRole('button', { name: '预览原件', exact: true }).click();
  const preview = page.getByRole('dialog', { name: /原件与保存版本/ });
  await expect(preview).toContainText('人工核对后的合成文字'); await expect(preview.locator('img')).toHaveAttribute('src', new RegExp(`/versions/${derived.id}/preview/1$`));
  await page.keyboard.press('Escape'); await page.setViewportSize({ width: 1280, height: 720 });
  await card.getByRole('button', { name: '修改核对文字' }).click(); const editor = page.getByRole('dialog', { name: '修改核对文字 · 合成核对图.png' });
  await expect(editor.getByRole('button', { name: '重新识别' })).toHaveCount(0);
  await editor.getByLabel('第 1 页文字').fill('再次人工核对的合成文字');
  await editor.getByRole('checkbox', { name: '我已对照原件核对第 1 页' }).check();
  const changed = page.waitForResponse(response => response.url().endsWith('/confirm') && response.request().method() === 'POST');
  await editor.getByRole('button', { name: '确认文字并参考' }).click(); const newer = await (await changed).json();
  expect(newer.id).not.toBe(derived.id); expect(newer.attachment.source_version_id).toBe(saved.id);
});

test('upload completion after scope switch cannot select into the new conversation; multiple errors stay clear', async ({ page }) => {
  test.setTimeout(60_000);
  await authorize(page); await configure(page); await room(page);
  await uploadImage(page, '先保存图.png');
  let release: (() => void) | undefined; const gate = new Promise<void>(resolve => { release = resolve; });
  let uploadedScope: string | undefined;
  await page.route('**/api/materials/conversation/*/upload', async route => {
    uploadedScope = route.request().url().split('/').at(-2); const response = await route.fetch(); await gate; await route.fulfill({ response });
  });
  await page.getByRole('button', { name: '添加图片或文件' }).click();
  await page.getByLabel('选择上传图片').setInputFiles(image('晚返回图.png'));
  await expect(page.getByRole('status').filter({ hasText: '正在保存附件' })).toBeVisible();
  await page.getByRole('button', { name: '新建对话', exact: true }).click(); release!();
  await expect(page.locator('.composer-attachment-card')).toHaveCount(0);
  await page.unroute('**/api/materials/conversation/*/upload');
  const state = await (await page.request.get(`/api/conversation-state/conversation/${uploadedScope}`)).json();
  // The completed file is saved to its original conversation, without altering its selection.
  const stored = await (await page.request.get(`/api/materials/conversation/${uploadedScope}`)).json();
  expect(stored.versions.some((item: { title: string }) => item.title === '晚返回图.png')).toBeTruthy();
  expect(JSON.stringify(state.source_scope)).not.toContain(stored.versions.find((item: { title: string }) => item.title === '晚返回图.png').id);
  await page.getByRole('button', { name: '添加图片或文件' }).click();
  await page.getByLabel('选择上传文件').setInputFiles([{ name: '可用.txt', mimeType: 'text/plain', buffer: Buffer.from('合成文字') }, { name: '不支持.exe', mimeType: 'application/octet-stream', buffer: Buffer.from('bad') }]);
  await expect(page.locator('.composer-attachment-card')).toContainText('可用.txt');
  await expect(page.getByRole('alert').filter({ hasText: '不支持.exe：暂不支持此文件格式' })).toBeVisible();
});

test('question discussion uses the same left picker and direct image reference', async ({ page }) => {
  test.setTimeout(120_000);
  await authorize(page); const config = await configure(page, 'mock-review');
  expect((await page.request.put(`/api/ai/providers/${config.provider.id}/models/${config.model.id}/image-capability`, { data: { supports_image_input: true } })).ok()).toBeTruthy();
  await page.reload(); await page.getByRole('button', { name: '学习首页', exact: true }).first().click();
  if (await (await page.request.get('/api/learning/return-review')).json()) await page.getByRole('button', { name: '创建', exact: true }).click();
  await page.getByLabel('学习目标', { exact: true }).fill('合成目标：图片附件讨论'); await page.getByRole('button', { name: '我想自己安排' }).click();
  await page.getByLabel('现在先做什么', { exact: true }).fill('合成附件讨论'); await page.getByRole('button', { name: '确认这份学习安排' }).click();
  await page.getByRole('button', { name: '进入学习室并开始这项任务' }).click(); await expect(page.locator('.ai-message--assistant').first()).toBeVisible();
  await page.getByRole('button', { name: '进入验证', exact: true }).click(); await page.getByRole('button', { name: '开始验证', exact: true }).click();
  await page.getByPlaceholder('写出你的判断、过程或结果').first().fill('合成答案1'); await page.getByPlaceholder('写出你的判断、过程或结果').nth(1).fill('合成答案2');
  await page.getByRole('button', { name: '保存作答并验证' }).click(); const first = page.getByRole('region', { name: '验证回看' }).getByRole('article', { name: '第 1 题回看' });
  await expect(first.getByText('合成逐题反馈：已说明过程和未知。')).toBeVisible(); await first.getByRole('button', { name: '讨论这道题' }).click();
  const discussion = page.getByRole('region', { name: '题目学习室' }); await expect(discussion.getByRole('button', { name: '添加图片或文件' })).toBeEnabled();
  const saved = await uploadImage(page, '讨论图片.png'); expect(saved.attachment.mode).toBe('image');
  await expect(discussion.locator('.attachment-model-hint')).toContainText('当前模型支持图片');
  await discussion.getByLabel('继续提问或回答拓展问题').fill('请看这张图');
  const sent = page.waitForResponse(response => /\/api\/learning\/discussions\/[^/]+\/messages$/.test(response.url()) && response.request().method() === 'POST');
  await discussion.getByLabel('继续提问或回答拓展问题').press('Enter'); const response = await sent; expect(response.ok()).toBeTruthy();
  expect(response.request().postDataJSON().source_scope.version_ids).toEqual([saved.id]);
});

test('readable PDF explicitly switches text and original-page input without a new version', async ({ page }) => {
  test.setTimeout(60_000);
  await authorize(page); const config = await configure(page);
  expect((await page.request.put(`/api/ai/providers/${config.provider.id}/models/${config.model.id}/image-capability`, { data: { supports_image_input: true } })).ok()).toBeTruthy();
  await room(page); await page.getByRole('button', { name: '添加图片或文件' }).click();
  const uploaded = page.waitForResponse(response => /\/upload$/.test(response.url()) && response.request().method() === 'POST');
  await page.getByLabel('选择上传文件').setInputFiles({ name: '可读原页.pdf', mimeType: 'application/pdf', buffer: readablePdf });
  const saved = await (await uploaded).json(); expect(saved.attachment.mode).toBe('text');
  const card = page.locator('.composer-attachment-card'); await expect(card).toContainText('当前参考');
  await card.getByLabel('本次参考方式：可读原页.pdf').selectOption('image');
  await expect(card).toContainText('原页图片参考');
  await page.getByLabel('输入学习问题').fill('请直接看保存的原页');
  const sent = page.waitForResponse(response => response.url().endsWith('/messages') && response.request().method() === 'POST');
  await page.getByLabel('输入学习问题').press('Enter'); const response = await sent; expect(response.ok()).toBeTruthy();
  expect(response.request().postDataJSON().source_scope.image_version_ids).toEqual([saved.id]);
  const scopeId = response.url().split('/').at(-2);
  await expect.poll(async () => (await (await page.request.get(`/api/ai/conversations/${scopeId}`)).json()).active_run).toBeNull();
  await card.getByLabel('本次参考方式：可读原页.pdf').selectOption('text'); await expect(card).toContainText('已读取文字');
  await card.getByRole('button', { name: '取消参考' }).click();
  const state = await (await page.request.get(`/api/conversation-state/conversation/${scopeId}`)).json(); expect(state.source_scope.image_version_ids ?? []).toEqual([]);
  const versions = await (await page.request.get(`/api/materials/conversation/${scopeId}`)).json(); expect(versions.versions).toHaveLength(1);
});


test('late upload preserves newest selection and saved selection conflict can be retried', async ({ page }) => {
  test.setTimeout(60_000);
  await authorize(page); await configure(page); await room(page); const first = await uploadImage(page, '先参考图.png');
  let release: (() => void) | undefined; const gate = new Promise<void>(resolve => { release = resolve; });
  let ready: (() => void) | undefined; const uploaded = new Promise<void>(resolve => { ready = resolve; });
  let second: { id: string; material_id: string } | undefined; let scopeId = '';
  await page.route('**/api/materials/conversation/*/upload', async route => {
    const response = await route.fetch(); second = await response.json(); scopeId = route.request().url().split('/').at(-2)!; ready!(); await gate; await route.fulfill({ response });
  });
  await page.getByRole('button', { name: '添加图片或文件' }).click(); await page.getByLabel('选择上传图片').setInputFiles(image('晚保存图.png')); await uploaded;
  await page.locator('.ai-composer').getByRole('button', { name: /^资料/ }).click();
  const panel = page.locator('.task-materials-panel'); const firstChoice = panel.getByRole('checkbox', { name: /先参考图.png/ });
  await firstChoice.click(); await expect(firstChoice).not.toBeChecked(); release!();
  await expect(page.locator('.composer-attachment-card').filter({ hasText: '晚保存图.png' })).toContainText('当前参考');
  await page.unroute('**/api/materials/conversation/*/upload');
  let state = await (await page.request.get(`/api/conversation-state/conversation/${scopeId}`)).json(); expect(state.source_scope.version_ids).toEqual([second!.id]); expect(state.source_scope.version_ids).not.toContain(first.id);
  await page.locator('.ai-composer').getByRole('button', { name: /^资料/ }).click();
  await page.route('**/api/conversation-state/conversation/*', async route => {
    if (route.request().method() !== 'PUT') return route.continue();
    await route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: 'conversation_state_conflict' }) }); await page.unroute('**/api/conversation-state/conversation/*');
  });
  await page.getByRole('button', { name: '添加图片或文件' }).click(); await page.getByLabel('选择上传图片').setInputFiles(image('已保存待参考.png'));
  const card = page.locator('.composer-attachment-card').filter({ hasText: '已保存待参考.png' }); await expect(card).toContainText('已保存，参考未确认');
  await card.getByRole('button', { name: '参考此版本' }).click(); await expect(card).toContainText('当前参考');
  state = await (await page.request.get(`/api/conversation-state/conversation/${scopeId}`)).json(); expect(state.source_scope.version_ids).toHaveLength(2); expect(state.source_scope.version_ids).toContain(second!.id);
});

test('failed OCR page stays a draft and allows explicit manual correction against original', async ({ page }) => {
  test.setTimeout(60_000);
  await authorize(page); const config = await configure(page, 'mock-error');
  expect((await page.request.put(`/api/ai/providers/${config.provider.id}/models/${config.model.id}/image-capability`, { data: { supports_image_input: true } })).ok()).toBeTruthy();
  expect((await page.request.put('/api/material-ocr/settings', { data: { provider_profile_id: config.provider.id, provider_model_id: config.model.id } })).ok()).toBeTruthy();
  await room(page); const original = await uploadImage(page, '识别失败原图.png');
  await page.locator('.composer-attachment-card').getByRole('button', { name: '识别与核对文字' }).click(); const review = page.getByRole('dialog', { name: '识别与核对文字 · 识别失败原图.png' });
  await review.getByRole('button', { name: '开始识别文字' }).click(); await expect(review.getByRole('alert').filter({ hasText: '这一页识别失败' })).toBeVisible({ timeout: 20_000 });
  await expect(review.getByRole('button', { name: '确认文字并参考' })).toBeDisabled();
  await review.getByLabel('第 1 页文字').fill('根据原图手动补充的合成文字'); await review.getByRole('checkbox', { name: '我已对照原件核对第 1 页' }).check();
  const confirmed = page.waitForResponse(response => response.url().endsWith('/confirm') && response.request().method() === 'POST'); await review.getByRole('button', { name: '确认文字并参考' }).click();
  const saved = await (await confirmed).json(); expect(saved.attachment.source_version_id).toBe(original.id); expect(saved.attachment.pages[0].reviewed).toBe(true);
  await expect(review.getByText('该页曾识别失败，文字已由你补充并核对。')).toBeVisible();
});


test('purged original stops an open OCR poll and removes displayed pages', async ({ page }) => {
  test.setTimeout(60_000);
  await authorize(page); const config = await configure(page);
  expect((await page.request.put(`/api/ai/providers/${config.provider.id}/models/${config.model.id}/image-capability`, { data: { supports_image_input: true } })).ok()).toBeTruthy();
  expect((await page.request.put('/api/material-ocr/settings', { data: { provider_profile_id: config.provider.id, provider_model_id: config.model.id } })).ok()).toBeTruthy();
  await room(page); const saved = await uploadImage(page, '随后清除的原图.png');
  const scopeId = (await (await page.request.get('/api/ai/conversations')).json())[0].id;
  await page.locator('.composer-attachment-card').getByRole('button', { name: '识别与核对文字' }).click(); const review = page.getByRole('dialog', { name: '识别与核对文字 · 随后清除的原图.png' });
  const started = page.waitForResponse(response => /\/api\/material-ocr\/.*\/versions\/[^/]+$/.test(response.url()) && response.request().method() === 'POST');
  await review.getByRole('button', { name: '开始识别文字' }).click(); expect((await started).ok()).toBeTruthy();
  expect((await page.request.post(`/api/materials/conversation/${scopeId}/${saved.material_id}/purge`, { data: { confirmation: 'PURGE' } })).ok()).toBeTruthy();
  const unavailable = page.getByRole('dialog', { name: '附件已不可用' }); await expect(unavailable).toBeVisible({ timeout: 10_000 });
  await expect(unavailable.locator('img, textarea')).toHaveCount(0);
  await page.evaluate(({ kind, id }) => window.dispatchEvent(new CustomEvent('nautilus:materials-changed', { detail: { kind, id } })), { kind: 'conversation', id: scopeId });
  await expect(page.getByRole('dialog')).toHaveCount(0); await expect(page.locator('.composer-attachment-card')).toHaveCount(0);
});
