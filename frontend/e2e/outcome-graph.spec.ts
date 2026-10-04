import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { expect, test, type Page, type Locator } from '@playwright/test';
import { authorize } from './fact-helpers';
import type { OutcomeGraphData, OutcomeRelation } from '../src/api';

const graphApi = '/api/learning/outcome-graph';
test.beforeEach(async ({ page }) => { page.setDefaultTimeout(12_000); });
type Fixture = { support_outcome_id: string; no_standard_outcome_id: string; other_plan_outcome_id: string; plan_id: string; other_plan_id: string; artifact_id: string; criterion_id: string };

async function seed(page: Page, prefix: string): Promise<Fixture> {
  const auth = await (await page.request.get('/api/auth/status')).json();
  const output = execFileSync(resolve('../.venv/bin/python'), [resolve('../backend/tests/seed_outcome_graph.py'), '--data-dir', process.env.NAUTILUS_E2E_DATA_DIR!, '--owner-id', auth.identity.id, '--prefix', prefix], {
    cwd: resolve('..'), encoding: 'utf8', env: { ...process.env, PYTHONPATH: resolve('../backend'), PYTHONDONTWRITEBYTECODE: '1' },
  });
  return JSON.parse(output);
}
async function provider(page: Page, model = 'mock-success') {
  const response = await page.request.put('/api/ai/provider', { data: { display_name: 'Synthetic graph provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL, model, api_key: 'synthetic-test-only', enabled: true, request_timeout_seconds: 15 } });
  expect(response.ok()).toBeTruthy();
}
async function graph(page: Page) {
  await page.goto('/?view=records');
  await page.getByRole('button', { name: '成果图', exact: true }).click();
  await expect(page.getByRole('region', { name: '成果图', exact: true })).toBeVisible();
  await expect(page.getByText('正在读取成果图…', { exact: true })).toHaveCount(0);
}
const node = (page: Page, title: string) => page.locator('.outcome-graph__node').filter({ has: page.getByText(title, { exact: true }) });
async function select(page: Page, title: string) { const target = node(page, title); await target.focus(); await target.click(); }
const inspector = (page: Page) => page.getByRole('complementary', { name: '成果详情', exact: true });
async function create(page: Page, title: string, kind = 'composite') {
  const drawer = page.locator('.outcome-graph__drawer'); if (await drawer.count()) await drawer.getByRole('button', { name: '关闭成果详情', exact: true }).click();
  await page.getByRole('button', { name: '新建成果', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '新建成果', exact: true });
  await dialog.getByRole('combobox', { name: '成果类型', exact: true }).selectOption(kind);
  await dialog.getByLabel('关于什么', { exact: true }).fill(title);
  await dialog.getByLabel('希望能够做什么', { exact: true }).fill(`能够解释并实践${title}`);
  await dialog.getByRole('button', { name: '创建成果', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  const data = await (await page.request.get(graphApi)).json() as OutcomeGraphData;
  return data.nodes.find(item => item.object_description === title)!;
}
async function relationship(page: Page, kind: string, target: string, context: string, source?: string) {
  await inspector(page).getByRole('button', { name: '添加关系', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '添加关系', exact: true });
  await dialog.getByRole('combobox', { name: '关系', exact: true }).selectOption(kind);
  const cross = dialog.getByRole('checkbox', { name: '包含其他计划的成果' });
  if (await cross.count()) await cross.check();
  if (source) await dialog.getByRole('combobox', { name: kind === 'contains' ? '综合成果' : kind === 'prerequisite' ? '前置成果' : '第一个成果', exact: true }).selectOption(source);
  await dialog.getByRole('combobox', { name: kind === 'contains' ? '组成成果' : kind === 'prerequisite' ? '后续成果' : '第二个成果', exact: true }).selectOption(target);
  await dialog.getByText('情境、说明与来源', { exact: true }).click();
  await dialog.getByLabel('适用情境', { exact: true }).fill(context);
  await dialog.getByRole('textbox', { name: '为什么关联', exact: true }).fill('合成组织说明：依据成果声明关联。');
  return dialog;
}
function writable(relation: OutcomeRelation) {
  return { source_outcome_id: relation.source_outcome_id, target_outcome_id: relation.target_outcome_id, relation_type: relation.relation_type, context_key: relation.context_key, rationale: relation.rationale, uncertainty: relation.uncertainty,
    source_refs: relation.source_refs.map(({ kind, id, version, url }) => ({ kind, ...(id ? { id } : {}), ...(version ? { version } : {}), ...(url ? { url } : {}) })) };
}
async function noOverflow(page: Page) { expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy(); }

test('manual composition, standard coverage, original evidence, CAS and revoked history persist on desktop and mobile', async ({ page }) => {
  test.setTimeout(90_000);
  await authorize(page);
  // Confirm the actual isolated service route before any dependent UI journey.
  const ready = await page.request.get(graphApi); expect(ready.ok()).toBeTruthy();
  const fixture = await seed(page, 'manual');
  const before = await (await page.request.get(`${graphApi}`)).json() as OutcomeGraphData;
  const supported = before.nodes.find(item => item.id === fixture.support_outcome_id)!;
  const missing = before.nodes.find(item => item.id === fixture.no_standard_outcome_id)!;
  await graph(page);
  await page.getByRole('combobox', { name: '计划范围', exact: true }).selectOption(fixture.plan_id);
  await expect(node(page, supported.object_description)).toBeVisible();
  await expect(page.locator(`[data-outcome="${fixture.other_plan_outcome_id}"]`)).toHaveCount(0);
  const composite = await create(page, '合成综合成果：独立完成数据分析项目');
  let dialog = await relationship(page, 'contains', fixture.support_outcome_id, '合成数据分析项目');
  await dialog.getByRole('button', { name: '保存关系', exact: true }).click(); await expect(dialog).toHaveCount(0);
  dialog = await relationship(page, 'contains', fixture.no_standard_outcome_id, '合成数据分析项目');
  await dialog.getByRole('button', { name: '保存关系', exact: true }).click(); await expect(dialog).toHaveCount(0);
  await select(page, supported.object_description);
  const details = inspector(page);
  await expect(details).toContainText('已有支持'); await expect(details).toContainText('不同表现'); await expect(details).toContainText('尚无依据');
  await details.getByText('标准来源与范围', { exact: true }).first().click();
  await expect(details).toContainText('已批准'); await expect(details).toContainText('v1');
  await details.getByRole('button', { name: '查看原始依据', exact: true }).click();
  const review = page.getByRole('region', { name: '单成果依据回看' });
  await review.getByRole('button', { name: '查看这个版本的原始产出', exact: true }).first().click();
  await expect(review.locator('[aria-label="原始产出版本"]')).toContainText('sample: D142');
  await review.getByRole('button', { name: '返回成果图', exact: true }).click();
  await select(page, missing.object_description); await expect(inspector(page)).toContainText('没有合格标准');
  await select(page, composite.object_description); await expect(inspector(page)).toContainText('整体实践仍待验证');
  await page.setViewportSize({ width: 1440, height: 1000 }); await noOverflow(page);
  await page.screenshot({ path: '/tmp/nautilus-d1-desktop.png', fullPage: true });
  await page.getByRole('combobox', { name: '计划范围', exact: true }).selectOption(fixture.plan_id);
  await expect(node(page, composite.object_description)).toBeVisible();
  await page.getByLabel('查找成果', { exact: true }).fill('合成综合成果'); await expect(page.locator('.outcome-graph__node')).toHaveCount(1);
  await page.getByLabel('查找成果', { exact: true }).fill('');
  await page.reload(); await expect(node(page, composite.object_description)).toBeVisible();
  await select(page, composite.object_description);
  await inspector(page).getByRole('button', { name: `${composite.object_description} 包含 ${supported.object_description}`, exact: true }).click();
  const relationDetails = page.getByRole('complementary', { name: '关系详情', exact: true });
  await relationDetails.getByRole('button', { name: '调整关系', exact: true }).click();
  const edit = page.getByRole('dialog', { name: '调整关系', exact: true });
  await edit.getByRole('textbox', { name: '为什么关联', exact: true }).fill('合成当前页面修改');
  const state = await (await page.request.get(graphApi)).json() as OutcomeGraphData;
  const relation = state.relations.find(item => item.source_outcome_id === composite.id && item.target_outcome_id === supported.id)!;
  const concurrent = await page.request.post(`${graphApi}/relations/${relation.id}/revise`, { data: { ...writable(relation), rationale: '合成另一个页面修改', expected_revision: relation.revision, request_key: 'manual-concurrent-update' } }); expect(concurrent.ok()).toBeTruthy();
  await edit.getByRole('button', { name: '保存关系', exact: true }).click();
  await expect(edit.getByRole('alert')).toContainText('其他页面更新');
  await edit.getByRole('button', { name: '重新读取关系', exact: true }).click();
  await edit.getByRole('textbox', { name: '为什么关联', exact: true }).fill('合成重新读取后确认');
  await edit.getByRole('button', { name: '保存关系', exact: true }).click(); await expect(edit).toHaveCount(0);
  await relationDetails.getByText('关系历史（3）', { exact: true }).click(); await expect(relationDetails).toContainText('合成另一个页面修改');
  await relationDetails.getByRole('button', { name: '撤销关系', exact: true }).click(); await relationDetails.getByRole('button', { name: '确认撤销', exact: true }).click();
  await expect(relationDetails).toContainText('已撤销');
  await page.reload(); await page.getByRole('combobox', { name: '计划范围', exact: true }).selectOption('all'); await select(page, composite.object_description);
  await expect(inspector(page)).toContainText('已撤销');
  const after = await (await page.request.get(graphApi)).json() as OutcomeGraphData;
  expect(after.nodes.find(item => item.id === fixture.support_outcome_id)!.evidence_links).toEqual(supported.evidence_links);
  await page.setViewportSize({ width: 390, height: 844 }); await noOverflow(page);
  await page.screenshot({ path: '/tmp/nautilus-d1-mobile.png', fullPage: true });
  await page.getByRole('button', { name: '关闭成果详情', exact: true }).click();
  await page.getByRole('button', { name: '新建成果', exact: true }).click();
  const keyboardDialog = page.getByRole('dialog', { name: '新建成果', exact: true });
  await page.keyboard.press('Shift+Tab'); expect(await keyboardDialog.evaluate(element => element.contains(document.activeElement))).toBeTruthy();
  await page.keyboard.press('Escape'); await expect(keyboardDialog).toHaveCount(0); await expect(page.getByRole('button', { name: '新建成果', exact: true })).toBeFocused();
});

test('four manual relationships, cross-plan selection, duplicate/cycle and request failure recovery', async ({ page }) => {
  test.setTimeout(60_000); await authorize(page); await graph(page);
  const a = await create(page, '合成四类：基础能力', 'atomic'), b = await create(page, '合成四类：应用能力', 'atomic'), c = await create(page, '合成四类：整体能力');
  let dialog = await relationship(page, 'contains', a.id, '四类包含'); await dialog.getByRole('button', { name: '保存关系', exact: true }).click(); await expect(dialog).toHaveCount(0);
  await select(page, a.object_description);
  dialog = await relationship(page, 'prerequisite', b.id, '四类前置'); await dialog.getByRole('button', { name: '保存关系', exact: true }).click(); await expect(dialog).toHaveCount(0);
  dialog = await relationship(page, 'equivalent', b.id, '四类等价'); await dialog.getByRole('button', { name: '保存关系', exact: true }).click(); await expect(dialog).toHaveCount(0);
  dialog = await relationship(page, 'overlap', b.id, '四类重叠');
  await page.route(`**${graphApi}/relations`, route => route.fulfill({ status: 503, json: { detail: '合成保存失败，请重试。' } }));
  await dialog.getByRole('button', { name: '保存关系', exact: true }).click(); await expect(dialog.getByRole('alert')).toContainText('合成保存失败');
  await page.unroute(`**${graphApi}/relations`); await dialog.getByRole('button', { name: '保存关系', exact: true }).click(); await expect(dialog).toHaveCount(0);
  let data = await (await page.request.get(graphApi)).json() as OutcomeGraphData;
  expect(data.relations.filter(item => [a.id,b.id,c.id].includes(item.source_outcome_id) && [a.id,b.id,c.id].includes(item.target_outcome_id)).map(item => item.relation_type).sort()).toEqual(['contains','equivalent','overlap','prerequisite']);
  dialog = await relationship(page, 'overlap', b.id, '四类重叠'); await dialog.getByRole('button', { name: '保存关系', exact: true }).click(); await expect(dialog.getByRole('alert')).toContainText('已经存在'); await dialog.getByRole('button', { name: '取消', exact: true }).click();
  const d = await create(page, '合成四类：第二个整体'); dialog = await relationship(page, 'contains', c.id, '包含循环检查'); await dialog.getByRole('button', { name: '保存关系', exact: true }).click(); await expect(dialog).toHaveCount(0);
  await select(page, c.object_description); dialog = await relationship(page, 'contains', d.id, '包含循环检查'); await dialog.getByRole('button', { name: '保存关系', exact: true }).click(); await expect(dialog.getByRole('alert')).toContainText('循环'); await dialog.getByRole('button', { name: '取消', exact: true }).click();
  data = await (await page.request.get(graphApi)).json() as OutcomeGraphData; expect(data.nodes.find(item => item.id === a.id)!.evidence_links).toEqual([]);
  await page.setViewportSize({ width:390,height:844 }); await noOverflow(page);
});

async function selectedSuggestion(page: Page, titles: string[]): Promise<Locator> {
  const drawer = page.locator('.outcome-graph__drawer'); if (await drawer.count()) await drawer.getByRole('button', { name: '关闭成果详情', exact: true }).click();
  await page.getByRole('button', { name:'AI 关系建议',exact:true }).click();
  const dialog = page.getByRole('dialog', { name:'AI 关系建议',exact:true });
  const chooser = dialog.locator('details').first();
  if (!(await chooser.evaluate(element => element.hasAttribute('open')))) await chooser.locator('summary').click();
  for (const title of titles) await dialog.getByRole('checkbox', { name: new RegExp(title) }).check();
  await dialog.getByRole('button', { name:'分析选中成果',exact:true }).click();
  return dialog;
}
test('AI only selected outcomes, saved candidate adopt/edit/reject, cancel/failure/retry and refresh', async ({ page }) => {
  test.setTimeout(90_000); await authorize(page); await provider(page); await graph(page);
  const comp = await create(page,'合成AI：综合成果'), a = await create(page,'合成AI：第一成果','atomic'), b = await create(page,'合成AI：第二成果','atomic'), c = await create(page,'合成AI：第三成果','atomic');
  const before = await (await page.request.get(graphApi)).json() as OutcomeGraphData;
  let dialog = await selectedSuggestion(page,[comp.object_description,a.object_description,b.object_description,c.object_description]);
  await expect(dialog.getByRole('status')).toContainText('建议已保存');
  let data = await (await page.request.get(graphApi)).json() as OutcomeGraphData;
  const run = data.runs[0]; expect(run.outcome_ids.sort()).toEqual([comp.id,a.id,b.id,c.id].sort()); expect(data.relations).toEqual(before.relations);
  expect(run.candidates.length).toBeGreaterThanOrEqual(3);
  await page.getByRole('button',{name:'关闭 AI 关系建议'}).click(); await page.reload(); await page.getByRole('button',{name:'AI 关系建议',exact:true}).click();
  dialog=page.getByRole('dialog',{name:'AI 关系建议',exact:true});
  await expect(dialog.getByRole('status')).toContainText('建议已保存');
  let candidates=dialog.locator('.outcome-graph__candidate');
  await candidates.nth(0).getByRole('button',{name:'采用',exact:true}).click(); await expect(candidates.nth(0)).toContainText('已采用');
  await candidates.nth(1).getByRole('button',{name:'调整后采用',exact:true}).click();
  const edit=page.getByRole('dialog',{name:'调整并采用建议',exact:true});
  const details=edit.locator('details'); if (!(await details.evaluate(element => element.hasAttribute('open')))) await details.locator('summary').click();
  await edit.getByRole('textbox',{name:'为什么关联',exact:true}).fill('合成用户调整后的关系依据'); await edit.getByRole('button',{name:'确认采用',exact:true}).click(); await expect(edit).toHaveCount(0);
  dialog=page.getByRole('dialog',{name:'AI 关系建议',exact:true}); candidates=dialog.locator('.outcome-graph__candidate'); await candidates.nth(2).getByRole('button',{name:'拒绝',exact:true}).click(); await expect(candidates.nth(2)).toContainText('已拒绝');
  await page.screenshot({path:'/tmp/nautilus-d1-ai-desktop.png',fullPage:true}); await page.setViewportSize({width:390,height:844}); await noOverflow(page); await page.screenshot({path:'/tmp/nautilus-d1-ai-mobile.png',fullPage:true});
  await page.getByRole('button',{name:'关闭 AI 关系建议'}).click();
  data=await (await page.request.get(graphApi)).json() as OutcomeGraphData; expect(data.relations.filter(item=>item.candidate_id && run.candidates.some(candidate=>candidate.id===item.candidate_id))).toHaveLength(2);
  dialog=await selectedSuggestion(page,[comp.object_description,a.object_description]); await expect(dialog.getByRole('status')).toContainText('建议已保存'); await expect(dialog).toContainText('暂时没有可采用的关系建议');
  expect((await (await page.request.get(graphApi)).json() as OutcomeGraphData).relations).toEqual(data.relations);
  await page.getByRole('button',{name:'关闭 AI 关系建议'}).click();
  await provider(page,'mock-error');
  dialog=await selectedSuggestion(page,[comp.object_description,c.object_description]); await expect(dialog.getByRole('status')).toContainText('分析失败'); await expect(dialog).toContainText('AI 暂时无法生成关系建议');
  await provider(page,'mock-slow'); await dialog.getByRole('button',{name:'重新分析这组成果',exact:true}).click(); await expect(dialog.getByRole('button',{name:'取消分析',exact:true})).toBeVisible(); await dialog.getByRole('button',{name:'取消分析',exact:true}).click(); await expect(dialog.getByRole('status')).toContainText('已取消');
  // A failed poll must resume after explicit reread even while run id/status are unchanged.
  await page.route(`**${graphApi}/suggestions/*`, async route => { if (route.request().method() === 'GET') await route.fulfill({ status:503,json:{detail:'合成读取中断'} }); else await route.continue(); });
  await dialog.getByRole('button',{name:'重新分析这组成果',exact:true}).click(); await expect(dialog.getByRole('alert')).toContainText('合成读取中断');
  await page.unroute(`**${graphApi}/suggestions/*`); await dialog.getByRole('button',{name:'重新读取分析',exact:true}).click(); await expect(dialog.getByRole('status')).toContainText('建议已保存');
  const after=await (await page.request.get(graphApi)).json() as OutcomeGraphData; expect(after.relations).toEqual(data.relations);
  await dialog.getByText('先前的分析',{exact:true}).click(); await dialog.getByRole('combobox',{name:'选择分析记录',exact:true}).selectOption(run.id);
  await dialog.getByText('更多操作',{exact:true}).click(); await dialog.getByRole('button',{name:'清除这次分析内容',exact:true}).click();
  let confirmation=page.getByRole('dialog',{name:'清除这次分析内容？',exact:true}); await expect(confirmation).toContainText('已经采用的关联仍保留');
  await page.keyboard.press('Escape'); await expect(confirmation).toHaveCount(0); await expect(dialog).toBeVisible();
  await dialog.getByRole('button',{name:'清除这次分析内容',exact:true}).click();
  confirmation=page.getByRole('dialog',{name:'清除这次分析内容？',exact:true});
  const partial={status:'partial',files:[{name:'合成受管理副本',status:'failed',reason:'合成清除中断'}],external_limits:[]};
  await page.route(`**${graphApi}/suggestions/${run.id}/purge`,async route=>{const result=await route.fetch(); const body=await result.json(); await route.fulfill({response:result,json:{...body,purge_report:partial}});});
  await page.route(`**${graphApi}/suggestions/${run.id}/purge-status`,route=>route.fulfill({json:partial}));
  await confirmation.getByRole('button',{name:'确认清除',exact:true}).click(); await expect(confirmation).toHaveCount(0);
  await expect(dialog.getByLabel('内容清除结果')).toContainText('部分内容未能清除');
  await page.unroute(`**${graphApi}/suggestions/${run.id}/purge`); await page.unroute(`**${graphApi}/suggestions/${run.id}/purge-status`);
  await dialog.getByRole('button',{name:'重试清除',exact:true}).click(); await expect(dialog.getByLabel('内容清除结果')).toContainText('受管理副本已清除');
  const purged=await (await page.request.get(graphApi)).json() as OutcomeGraphData; const adopted=purged.relations.filter(item=>item.candidate_id && run.candidates.some(candidate=>candidate.id===item.candidate_id));
  expect(adopted).toHaveLength(2); expect(adopted.every(item=>item.status==='active' && item.available===false && !item.rationale)).toBeTruthy();
  await page.getByRole('button',{name:'关闭 AI 关系建议'}).click();
  const openDrawer=page.locator('.outcome-graph__drawer'); if(await openDrawer.count()) await openDrawer.getByRole('button',{name:'关闭成果详情',exact:true}).click();
  await select(page,comp.object_description);
  await inspector(page).getByRole('button',{name:`${comp.object_description} 包含 ${a.object_description}`,exact:true}).click();
  const relationDetails=page.getByRole('complementary',{name:'关系详情',exact:true}); await relationDetails.getByText('更多操作',{exact:true}).click(); await relationDetails.getByRole('button',{name:'彻底清除关系说明',exact:true}).click();
  confirmation=page.getByRole('dialog',{name:'清除这项关系说明？',exact:true}); await confirmation.getByRole('button',{name:'确认清除',exact:true}).click(); await expect(confirmation).toHaveCount(0); await expect(relationDetails.getByLabel('内容清除结果')).toContainText('受管理副本已清除');
});
