import { expect, test, type Page } from '@playwright/test';
import { authorize } from './fact-helpers';

const mockBase = process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL ?? 'http://127.0.0.1:8013/v1';
const fakeKey = 'synthetic-search-test-key-only';
const script = `function search(query,maxResults){ return {answer:'Synthetic answer for '+query,items:[{title:'Synthetic source',url:'https://example.com/search-proof',text:'Synthetic page content',publishedDate:'2026-01-01'}]}; }`;

async function settings(page: Page) {
  await page.getByRole('button', { name: '搜索设置', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '联网搜索设置' });
  await expect(dialog.getByRole('button', { name: '新增' })).toBeEnabled();
  return dialog;
}

async function setProvider(page: Page, model = 'mock-success') {
  const response = await page.request.put('/api/ai/provider', { data: {
    display_name: 'Synthetic mock provider', base_url: mockBase, model,
    api_key: fakeKey, enabled: true, request_timeout_seconds: 15, api_protocol: 'openai_compatible',
  } });
  expect(response.ok()).toBeTruthy();
}

async function openPicker(page: Page) {
  await page.locator('.ai-composer').getByRole('button', { name: /联网搜索：/ }).click();
  return page.getByRole('dialog', { name: '联网搜索选择' });
}

async function setCustomSearch(page: Page) {
  const before = await (await page.request.get('/api/search/settings')).json();
  const service = { id: crypto.randomUUID(), kind: 'custom_js', name: 'Synthetic JS', options: { name: '', search_script: script, scrape_script: '' }, secret_updates: {} };
  const response = await page.request.put('/api/search/settings', { data: {
    revision: before.revision, services: [service], selected_service_id: service.id,
    result_size: 5, timeout_seconds: 15, max_requests: 1,
  } });
  expect(response.ok()).toBeTruthy();
  return service.id as string;
}

test.beforeEach(async ({ page }) => {
  await authorize(page);
  const conversations = await (await page.request.get('/api/ai/conversations')).json();
  for (const conversation of conversations) expect((await page.request.delete(`/api/ai/conversations/${conversation.id}`)).ok()).toBeTruthy();
});

test('all 19 catalog services expose their fields and save without echoing secrets', async ({ page }) => {
  test.setTimeout(60_000);
  const catalog = await (await page.request.get('/api/search/catalog')).json() as Array<{kind:string; label:string; fields:Array<{key:string;label:string;type:string;required?:boolean}>}>;
  expect(catalog).toHaveLength(19);
  const dialog = await settings(page);
  const initialServiceCount = await dialog.locator('.search-service-row').count();
  const seenKinds = new Set<string>();
  for (const kind of catalog) {
    await dialog.getByLabel('新增服务类型').selectOption(kind.kind);
    await dialog.getByRole('button', { name: '新增' }).click();
    const selected = dialog.locator('.search-service-row.is-selected');
    await expect(selected).toContainText(kind.label);
    seenKinds.add(kind.kind);
    for (const field of kind.fields) {
      const wrapper = dialog.locator('.search-fields .field').filter({ hasText: field.label }).first();
      await expect(wrapper).toBeVisible();
      if (field.type === 'secret' && field.required) await wrapper.locator('input').fill(fakeKey);
      if (kind.kind === 'searxng' && field.key === 'url') await wrapper.locator('input').fill('https://example.com/searx');
      if (kind.kind === 'custom_js' && field.key === 'search_script') await wrapper.locator('textarea').fill(script);
    }
  }
  expect(seenKinds.size).toBe(19);
  await expect(dialog.locator('.search-service-row')).toHaveCount(initialServiceCount + 19);
  await dialog.locator('.search-service-row').filter({ hasText: 'Perplexity' }).first().getByRole('button', { name: /Perplexity/ }).first().click();
  const tokenLabel = catalog.find(item => item.kind === 'perplexity')!.fields.find(field => field.key === 'max_tokens')!.label;
  const tokenField = dialog.locator('.search-fields .field').filter({ hasText: tokenLabel }).first().locator('input');
  await tokenField.fill('128');
  await tokenField.fill('');
  await dialog.getByRole('button', { name: '保存设置' }).click();
  await expect(dialog).toHaveCount(0);
  const saved = await (await page.request.get('/api/search/settings')).json();
  expect(saved.services).toHaveLength(initialServiceCount + 19);
  for (const item of catalog) {
    const savedService = saved.services.find((service: {kind:string}) => service.kind === item.kind);
    expect(savedService, item.kind).toBeTruthy();
    for (const field of item.fields) {
      if (field.type === 'secret') { if (field.required) expect(savedService.has_secrets[field.key]).toBe(true); }
      else expect(savedService.options).toHaveProperty(field.key);
    }
  }
  expect(saved.services.find((item: {kind:string}) => item.kind === 'perplexity')?.options.max_tokens).toBeNull();
  expect(JSON.stringify(saved)).not.toContain(fakeKey);
  expect(saved.services.find((item: {kind:string}) => item.kind === 'tavily')?.has_secrets.api_key).toBe(true);
  await page.reload();
  const reopened = await settings(page);
  await expect(reopened.locator('.search-service-row')).toHaveCount(initialServiceCount + 19);
  await reopened.locator('.search-service-row').filter({ hasText: 'Tavily' }).first().getByRole('button', { name: /Tavily/ }).first().click();
  const keyLabel = catalog.find(item => item.kind === 'tavily')!.fields.find(field => field.key === 'api_key')!.label;
  const secret = reopened.locator('.search-fields .field').filter({ hasText: keyLabel }).first().locator('input');
  await expect(secret).toHaveValue('');
  await expect(secret).toHaveAttribute('type', 'password');
  await page.screenshot({ path: '/tmp/nautilus-search-settings-e2e.png' });
  // Clearing a credential must be saveable without immediately replacing it.
  await reopened.locator('.search-fields .field').filter({ hasText: keyLabel }).first().getByRole('button', { name: '清除', exact: true }).click();
  await reopened.getByRole('button', { name: '保存设置' }).click();
  await expect(reopened).toHaveCount(0);
  const cleared = await (await page.request.get('/api/search/settings')).json();
  expect(cleared.services.find((item: {kind:string}) => item.kind === 'tavily')?.has_secrets.api_key).toBeFalsy();
});

test('reorder and deleting the selected instance clear the default without switching vendors', async ({ page }) => {
  const catalog = await (await page.request.get('/api/search/catalog')).json() as Array<{kind:string; fields:Array<{key:string;label:string}>}>;
  const scriptLabel = catalog.find(item => item.kind === 'custom_js')!.fields.find(field => field.key === 'search_script')!.label;
  const dialog = await settings(page);
  await dialog.getByLabel('新增服务类型').selectOption('custom_js');
  await dialog.getByRole('button', { name: '新增' }).click();
  await dialog.getByLabel('显示名称').fill('Temporary JS');
  await dialog.locator('.search-fields .field').filter({ hasText: scriptLabel }).locator('textarea').fill(script);
  await dialog.getByText('默认外部服务').click();
  await dialog.getByRole('button', { name: '保存设置' }).click();
  const before = await (await page.request.get('/api/search/settings')).json();
  const selectedId = before.selected_service_id;
  expect(before.services[0].id).toBe(selectedId);
  const reopened = await settings(page);
  await reopened.locator('.search-service-row').filter({ hasText: 'Temporary JS' }).getByRole('button', { name: '下移Temporary JS' }).click();
  await reopened.locator('.search-service-row').filter({ hasText: 'Temporary JS' }).getByRole('button', { name: 'Temporary JS' }).first().click();
  await reopened.getByRole('button', { name: '删除实例' }).click();
  await reopened.getByRole('button', { name: '保存设置' }).click();
  const after = await (await page.request.get('/api/search/settings')).json();
  expect(after.selected_service_id).toBeNull();
  expect(after.services.some((item: {id:string}) => item.id === selectedId)).toBe(false);
});

test('custom JS source stays with its answer version across reload; off sends no search selection', async ({ page }) => {
  await setProvider(page, 'mock-search-tools');
  const serviceId = await setCustomSearch(page);
  await page.reload();
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  const picker = await openPicker(page);
  await picker.getByRole('button', { name: /外部服务/ }).click();
  await expect(page.locator('.ai-composer').getByRole('button', { name: '联网搜索：Synthetic JS' })).toBeVisible();
  const composer = page.getByLabel('输入学习问题');
  await composer.fill('Synthetic search question');
  const firstRequest = page.waitForRequest(request => request.url().endsWith('/messages') && request.method() === 'POST');
  await composer.press('Enter');
  const sent = await firstRequest;
  expect(sent.postDataJSON().search).toMatchObject({ mode: 'external', service_id: serviceId });
  const response = await sent.response();
  const { run } = await response!.json();
  const answer = page.locator('.ai-message--assistant').first();
  await expect(answer).toContainText('完成');
  const source = answer.getByRole('group', { name: '联网搜索结果' });
  await expect(source).toContainText('1 条来源');
  await source.locator('summary').first().click();
  await expect(source.getByRole('link', { name: 'Synthetic source' })).toHaveAttribute('href', 'https://example.com/search-proof');
  await source.getByText('检索过程', { exact: false }).click();
  await expect(source).toContainText('Nautilus search reference');
  await page.screenshot({ path: '/tmp/nautilus-search-results-e2e.png' });
  const saved = await (await page.request.get(`/api/ai/conversations/${run.conversation_id}`)).json();
  const firstAssistant = saved.messages.find((message: {role:string}) => message.role === 'assistant');
  expect(firstAssistant.search_trace?.items?.[0]?.title).toBe('Synthetic source');
  await (await openPicker(page)).getByRole('button', { name: /^关闭 不使用联网搜索/ }).click();
  const secondRequest = page.waitForRequest(request => request.url().endsWith('/messages') && request.method() === 'POST');
  await answer.getByRole('button', { name: '重新生成', exact: true }).click();
  expect((await secondRequest).postDataJSON().search).toBeUndefined();
  await expect(answer.getByLabel('回答 2/2')).toBeVisible();
  await expect(page.locator('.ai-message--assistant .search-results')).toHaveCount(0);
  await answer.getByRole('button', { name: '上一个回答' }).click();
  await expect(page.locator('.ai-message--assistant .search-results')).toHaveCount(1);
  await page.reload();
  await expect(page.locator('.ai-message--assistant .search-results')).toHaveCount(1);
  await expect(page.locator('.ai-message--assistant .search-results')).toContainText('1 条来源');
  await page.screenshot({ path: '/tmp/nautilus-search-compact-composer-e2e.png' });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator('.ai-composer .search-controls')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: '/tmp/nautilus-search-compact-composer-mobile-e2e.png' });
});

test('switching external services clears advanced parameters while mode toggles keep filters', async ({ page }) => {
  await setProvider(page);
  const customId = await setCustomSearch(page);
  const previous = await (await page.request.get('/api/search/settings')).json();
  const exaId = crypto.randomUUID();
  const saved = await page.request.put('/api/search/settings', { data: {
    ...previous,
    revision: previous.revision,
    services: [
      { id: exaId, kind: 'exa', name: 'Exa synthetic', options: {}, secret_updates: { api_key: fakeKey } },
      ...previous.services,
    ],
    selected_service_id: exaId,
  } });
  expect(saved.ok()).toBeTruthy();
  await page.reload();
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  let picker = await openPicker(page);
  await picker.getByRole('button', { name: /外部服务/ }).click();
  picker = await openPicker(page);
  await picker.getByRole('button', { name: '展开高级参数' }).click();
  await picker.getByRole('combobox', { name: /搜索类型/ }).selectOption('deep');
  await picker.getByRole('button', { name: /^关闭 不使用联网搜索/ }).click();
  picker = await openPicker(page);
  await picker.getByRole('button', { name: /外部服务/ }).click();
  picker = await openPicker(page);
  await expect(picker.getByRole('combobox', { name: /搜索类型/ })).toHaveValue('deep');
  await picker.getByRole('button', { name: 'Synthetic JS', exact: true }).click();
  const composer = page.getByLabel('输入学习问题');
  await composer.fill('Synthetic cross-service test');
  const sentRequest = page.waitForRequest(request => request.url().endsWith('/messages') && request.method() === 'POST');
  await composer.press('Enter');
  const payload = (await sentRequest).postDataJSON();
  expect(payload.search.service_id).toBe(customId);
  expect(payload.search.parameters).toBeUndefined();
  await expect(page.locator('.ai-message--assistant').first()).toContainText('完成');
});

test('Google search suggestions stay visible outside collapsed sources and cannot run scripts in the parent', async ({ page }) => {
  await setProvider(page);
  await page.reload();
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  const composer = page.getByLabel('输入学习问题');
  await composer.fill('Synthetic Google suggestion display');
  const request = page.waitForRequest(candidate => candidate.url().endsWith('/messages') && candidate.method() === 'POST');
  await composer.press('Enter');
  const response = await (await request).response();
  const { run } = await response!.json();
  await expect(page.locator('.ai-message--assistant').first()).toContainText('完成');
  await page.route(`**/api/ai/conversations/${run.conversation_id}`, async route => {
    const original = await route.fetch();
    const data = await original.json();
    const assistant = data.messages.find((message: {id:string}) => message.id === run.response_message_id);
    expect(assistant).toBeTruthy();
    assistant.search_trace = { mode: 'native', status: 'succeeded', service_name: 'Google', items: [{ title: 'Synthetic Google source', url: 'https://example.com/a', text: 'Citation' }], search_suggestions_html: '<div id="suggestion">Suggested search terms</div><a href="https://example.com/related">Related</a><script>parent.document.body.setAttribute("data-search-script", "ran")</script>' };
    await route.fulfill({ response: original, contentType: 'application/json', body: JSON.stringify(data) });
  });
  await page.reload();
  const card = page.locator('.ai-message--assistant .search-results');
  await expect(card).toBeVisible();
  await expect(card).not.toHaveAttribute('open', '');
  const frame = page.locator('iframe[title="Google 搜索建议"]');
  await expect(frame).toBeVisible();
  await expect(frame).toHaveAttribute('sandbox', 'allow-popups allow-popups-to-escape-sandbox');
  await expect(frame).toHaveAttribute('referrerpolicy', 'no-referrer');
  await expect(page.frameLocator('iframe[title="Google 搜索建议"]').locator('#suggestion')).toHaveText('Suggested search terms');
  expect(await page.locator('body').getAttribute('data-search-script')).toBeNull();
});

test('an unconfirmed send replays the same ID and original search choice after mode changes', async ({ page }) => {
  await setProvider(page);
  const serviceId = await setCustomSearch(page);
  await page.reload();
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  await (await openPicker(page)).getByRole('button', { name: /外部服务/ }).click();
  await expect(page.locator('.ai-composer').getByRole('button', { name: '联网搜索：Synthetic JS' })).toBeVisible();
  const query = 'Synthetic ambiguous delivery';
  const requests: Array<{client_message_id:string; search?: {mode:string;service_id?:string}}> = [];
  let conversationId = '';
  await page.route('**/api/ai/conversations/*/messages', async route => {
    requests.push(route.request().postDataJSON());
    if (requests.length === 1) {
      const accepted = await route.fetch();
      expect(accepted.status()).toBe(202);
      conversationId = (await accepted.json()).run.conversation_id;
      await route.abort('failed');
    } else {
      await route.continue();
    }
  });
  const composer = page.getByLabel('输入学习问题');
  await composer.fill(query);
  await composer.press('Enter');
  await expect(composer).toHaveValue(query);
  await expect.poll(() => requests.length).toBe(1);
  await composer.fill('Changed after uncertain delivery');
  await composer.press('Enter');
  await expect.poll(() => requests.length).toBe(1);
  await expect(page.getByRole('alert')).toContainText('上次发送结果尚未确认');
  await composer.fill(query);
  await (await openPicker(page)).getByRole('button', { name: /^关闭 不使用联网搜索/ }).click();
  await composer.press('Enter');
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[0].client_message_id).toBe(requests[1].client_message_id);
  expect(requests[0].search).toMatchObject({ mode: 'external', service_id: serviceId });
  expect(requests[1].search).toEqual(requests[0].search);
  const saved = await (await page.request.get(`/api/ai/conversations/${conversationId}`)).json();
  expect(saved.messages.filter((message: {role:string;client_message_id:string}) => message.role === 'user' && message.client_message_id === requests[0].client_message_id)).toHaveLength(1);
});
