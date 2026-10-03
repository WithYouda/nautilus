import { openAnswerSources } from './answer-source-helpers';
import { expect, test, type Page } from '@playwright/test';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, join } from 'node:path';
import { authorize } from './fact-helpers';

const ORIGINAL = '# 合成知识库笔记\nKNOWLEDGE_B2_MARKER\n第一版证据只说明合成输入。\n第四行\n第五行\n第六行\n第七行\n第八行\n第九行\n';
const UPDATED = ORIGINAL.replace('第一版证据只说明合成输入。', '第二版证据增加合成边界。');
const mockUrl = process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL ?? 'http://127.0.0.1:8013/v1';

async function provider(page: Page, model: string) {
  expect((await page.request.put('/api/ai/provider', { data: {
    display_name: 'Knowledge retrieval mock', base_url: mockUrl, model,
    api_key: 'synthetic-knowledge-key', enabled: true, request_timeout_seconds: 15,
    api_protocol: 'openai_compatible',
  } })).ok()).toBeTruthy();
}

async function connect(page: Page, vault: string) {
  const previous = (await (await page.request.get('/api/obsidian/connection')).json()).connection;
  const response = await page.request.put('/api/obsidian/connection', { data: { root_path: vault, expected_revision: previous?.revision ?? null } });
  expect(response.ok()).toBeTruthy();
  return (await response.json()).connection;
}

async function openRoom(page: Page) {
  await expect(page.getByRole('button', { name: '退出会话' })).toBeVisible();
  const entry = page.getByRole('button', { name: '学习室', exact: true });
  if (await entry.count()) await entry.click();
  await expect(page.locator('.ai-composer').getByRole('button', { name: /联网搜索/ })).toBeEnabled();
}

async function sendRoom(page: Page, text: string) {
  const sent = page.waitForRequest(request => request.url().endsWith('/messages') && request.method() === 'POST');
  await page.getByLabel('输入学习问题').fill(text);
  await page.getByLabel('输入学习问题').press('Enter');
  const request = await sent;
  const response = await request.response();
  expect(response!.ok()).toBeTruthy();
  const { run } = await response!.json();
  await expect.poll(async () => (await (await page.request.get(`/api/ai/conversations/${run.conversation_id}`)).json()).active_run).toBeNull();
  await expect(page.locator('.ai-composer').getByRole('button', { name: /^资料/ })).toBeEnabled();
  const detail = await (await page.request.get(`/api/ai/conversations/${run.conversation_id}`)).json();
  return { request, run, answer: detail.messages.find((item: { role: string; ai_run_id: string }) => item.role === 'assistant' && item.ai_run_id === run.id) };
}

test('当前对话明确选择知识库，严格范围检索并保留旧回答证据', async ({ page }) => {
  test.setTimeout(120_000);
  const vault = mkdtempSync(join(tmpdir(), 'nautilus-knowledge-vault.'));
  const note = join(vault, '合成笔记.md');
  writeFileSync(note, ORIGINAL);
  try {
    await authorize(page);
    await provider(page, 'mock-knowledge-tools');
    const connection = await connect(page, vault);
    await page.reload();
    await openRoom(page);
    await page.getByRole('button', { name: '新建对话', exact: true }).click();
    const materials = page.locator('.ai-composer').getByRole('button', { name: /^资料/ });
    const panel = page.locator('.task-materials-panel');
    await materials.click();
    const knowledge = panel.getByRole('region', { name: '本对话知识库' });
    const choice = knowledge.getByRole('checkbox', { name: /本对话使用 Obsidian 知识库/ });
    await expect(choice).not.toBeChecked();
    await expect(choice).toBeEnabled();
    await choice.click();
    await expect(choice).toBeChecked();
    const strict = panel.getByRole('checkbox', { name: '只依据所选资料（严格范围）' });
    await expect(strict).toBeEnabled();
    await strict.click();
    await expect(strict).toBeChecked();

    // Removing the last manual note keeps the explicitly selected knowledge base and strict mode.
    await panel.getByLabel('标题', { exact: true }).fill('合成手动资料');
    await panel.getByLabel('正文', { exact: true }).fill('仅用于验证手动资料选择。');
    await panel.getByRole('button', { name: '保存版本' }).click();
    const manual = panel.getByRole('checkbox', { name: '合成手动资料 · 文本资料' });
    await expect(manual).toBeChecked();
    await manual.click();
    await expect(manual).not.toBeChecked();
    await expect(strict).toBeChecked();
    await expect(panel.getByText(/当前参考 0 份资料，共 0 字，并使用所选知识库/)).toBeVisible();
    await knowledge.scrollIntoViewIfNeeded();
    await page.screenshot({ path: '/tmp/nautilus-b2-knowledge-selector-desktop.png' });
    await page.setViewportSize({ width: 390, height: 720 });
    await knowledge.scrollIntoViewIfNeeded();
    await expect(choice).toBeVisible();
    await page.screenshot({ path: '/tmp/nautilus-b2-knowledge-selector-mobile.png' });
    await page.setViewportSize({ width: 1280, height: 720 });
    await materials.click();

    const first = await sendRoom(page, '请检索知识库并解释 KNOWLEDGE_B2_MARKER。');
    const selection = { kind: 'obsidian_local', connection_id: connection.connection_id, connection_revision: connection.revision };
    expect(first.request.postDataJSON().source_scope).toEqual({ mode: 'only', version_ids: [], knowledge_base: selection });
    expect(first.answer.source_scope.selection_version_ids).toEqual([]);
    expect(first.answer.source_scope.knowledge_references.length).toBeGreaterThan(0);
    expect(first.answer.source_scope.knowledge_base_name).toBe(basename(vault));
    expect(first.answer.generation_trace.parts.filter((part: { type: string; name: string }) => part.type === 'tool').map((part: { name: string }) => part.name))
      .toEqual(['search_knowledge_base', 'read_knowledge_note']);
    expect(first.answer.generation_trace.parts.every((part: { result?: unknown }) => !JSON.stringify(part.result ?? {}).includes('第一版证据'))).toBeTruthy();
    const versionId = first.answer.source_scope.knowledge_references[0].version_id;
    const state = await (await page.request.get(`/api/conversation-state/conversation/${first.run.conversation_id}`)).json();
    expect(state.source_scope).toEqual({ mode: 'only', version_ids: [], knowledge_base: selection });
    const saved = await (await page.request.get(`/api/materials/conversation/${first.run.conversation_id}`)).json();
    expect(saved.versions.find((version: { id: string }) => version.id === versionId).library).toBe(false);
    expect((await (await page.request.get('/api/materials/library')).json()).versions.some((version: { id: string }) => version.id === versionId)).toBe(false);

    const firstUse = await openAnswerSources(page, page.locator('.task-material-use').first());
    await expect(firstUse).not.toContainText('本次知识库读取');
    await firstUse.getByRole('button', { name: '查看内容', exact: true }).click();
    const evidence = page.getByRole('dialog', { name: '合成笔记', exact: true });
    await expect(evidence).toContainText('第一版证据只说明合成输入。');
    await expect(evidence.getByRole('link', { name: '在 Obsidian 打开' })).toHaveAttribute('href', `obsidian://open?vault=${encodeURIComponent(basename(vault))}&file=${encodeURIComponent('合成笔记')}`);
    await evidence.screenshot({ path: '/tmp/nautilus-answer-sources-evidence-desktop.png' });
    await page.setViewportSize({ width: 390, height: 720 });
    await evidence.screenshot({ path: '/tmp/nautilus-answer-sources-evidence-mobile.png' });
    await page.keyboard.press('Escape');
    await expect(firstUse).toBeVisible();
    await firstUse.getByRole('button', { name: '关闭回答资料范围', exact: true }).click();
    await expect(firstUse).toHaveCount(0);
    await page.setViewportSize({ width: 1280, height: 720 });
    await expect(page.getByRole('button', { name: /^检索本地知识库/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /^读取知识库笔记/ })).toBeVisible();

    writeFileSync(note, UPDATED);
    const second = await sendRoom(page, '请重新检索 KNOWLEDGE_B2_MARKER 并解释现在的笔记。');
    expect(second.answer.source_scope.knowledge_references[0].version_id).not.toBe(versionId);
    const historical = await (await page.request.get(`/api/ai/conversations/${first.run.conversation_id}`)).json();
    const old = historical.messages.find((item: { id: string }) => item.id === first.answer.id);
    expect(old.source_scope.knowledge_references).toEqual(first.answer.source_scope.knowledge_references);
    expect(readFileSync(note, 'utf8')).toBe(UPDATED);

    await page.reload();
    await openRoom(page);
    await materials.click();
    await expect(choice).toBeChecked();
    await expect(strict).toBeChecked();
    await expect(panel.getByText(/当前参考 0 份资料/)).toBeVisible();
    await materials.click();
    expect((await page.request.post('/api/obsidian/connection/disconnect', { data: { expected_revision: connection.revision } })).ok()).toBeTruthy();
    await page.reload();
    await openRoom(page);
    await expect(page.getByText('所选资料版本或知识库连接已不可用，请打开资料重新选择或明确取消参考。')).toBeVisible();
    await materials.click();
    await expect(choice).toBeChecked();
    await expect(knowledge.getByRole('alert')).toContainText('原来选择的知识库连接已断开或更改');
    await expect(page.getByLabel('输入学习问题')).toBeDisabled();
    await materials.click();
    const review = await openAnswerSources(page, page.locator('.task-material-use').first());
    await review.getByRole('button', { name: '查看内容', exact: true }).click();
    await expect(page.getByRole('dialog', { name: '合成笔记', exact: true })).toContainText('第一版证据只说明合成输入。');
    expect(readFileSync(note, 'utf8')).toBe(UPDATED);
  } finally { rmSync(vault, { recursive: true, force: true }); }
});

test('题目讨论可以只选知识库，并在本次回答回看实际保存证据', async ({ page }) => {
  test.setTimeout(150_000);
  const vault = mkdtempSync(join(tmpdir(), 'nautilus-knowledge-discussion.'));
  writeFileSync(join(vault, '合成笔记.md'), ORIGINAL);
  try {
    await authorize(page);
    await provider(page, 'mock-review');
    const connection = await connect(page, vault);
    await page.reload();
    await page.getByRole('button', { name: '学习首页', exact: true }).first().click();
    if (await (await page.request.get('/api/learning/return-review')).json()) await page.getByRole('button', { name: '创建', exact: true }).click();
    await page.getByLabel('学习目标', { exact: true }).fill('合成知识库讨论目标');
    await page.getByRole('button', { name: '我想自己安排' }).click();
    await page.getByLabel('现在先做什么', { exact: true }).fill('合成知识库讨论任务');
    await page.getByRole('button', { name: '确认这份学习安排' }).click();
    await page.getByRole('button', { name: '进入学习室并开始这项任务' }).click();
    await expect(page.locator('.ai-message--assistant').first()).toBeVisible();
    await page.getByRole('button', { name: '进入验证', exact: true }).click();
    await page.getByRole('button', { name: '开始验证', exact: true }).click();
    await page.getByPlaceholder('写出你的判断、过程或结果').first().fill('合成作答：先定位，再检查边界。');
    await page.getByPlaceholder('写出你的判断、过程或结果').nth(1).fill('合成第二题作答：检查空输入。');
    await page.getByRole('button', { name: '保存作答并验证' }).click();
    await page.getByRole('region', { name: '验证回看' }).getByRole('article', { name: '第 1 题回看' }).getByRole('button', { name: '讨论这道题' }).click();
    await provider(page, 'mock-knowledge-tools');
    await page.reload();
    const discussion = page.getByRole('region', { name: '题目学习室' });
    const materials = discussion.locator('.ai-composer').getByRole('button', { name: /^资料/ });
    await materials.click();
    const panel = discussion.locator('.task-materials-panel');
    const choice = panel.getByRole('checkbox', { name: /本对话使用 Obsidian 知识库/ });
    await choice.click();
    await expect(choice).toBeChecked();
    const strict = panel.getByRole('checkbox', { name: '只依据所选资料（严格范围）' });
    await strict.click();
    await expect(strict).toBeChecked();
    await materials.click();
    const sent = page.waitForRequest(request => request.url().includes('/api/learning/discussions/') && request.url().endsWith('/messages') && request.method() === 'POST');
    await discussion.getByLabel('继续提问或回答拓展问题').fill('请检索 KNOWLEDGE_B2_MARKER，解释合成笔记。');
    await discussion.getByLabel('继续提问或回答拓展问题').press('Enter');
    const request = await sent;
    expect(request.postDataJSON().source_scope).toEqual({ mode: 'only', version_ids: [], knowledge_base: { kind: 'obsidian_local', connection_id: connection.connection_id, connection_revision: connection.revision } });
    const id = new URL(page.url()).searchParams.get('discussion');
    await expect.poll(async () => (await (await page.request.get(`/api/learning/discussions/${id}`)).json()).turns.at(-1)?.status).toBe('succeeded');
    const use = await openAnswerSources(page, discussion.locator('.task-material-use').last());
    await expect(use).not.toContainText('本次知识库读取');
    await use.getByRole('button', { name: '查看内容', exact: true }).click();
    await expect(page.getByRole('dialog', { name: '合成笔记', exact: true })).toContainText('第一版证据只说明合成输入。');
    const state = await (await page.request.get(`/api/conversation-state/discussion/${id}`)).json();
    expect(state.source_scope.version_ids).toEqual([]);
    expect(state.source_scope.knowledge_base.connection_id).toBe(connection.connection_id);
    expect(readFileSync(join(vault, '合成笔记.md'), 'utf8')).toBe(ORIGINAL);
  } finally { rmSync(vault, { recursive: true, force: true }); }
});
