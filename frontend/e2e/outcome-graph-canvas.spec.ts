import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { expect, test } from '@playwright/test';
import { authorize } from './fact-helpers';
import type { OutcomeGraphData } from '../src/api';
import { GRAPH_NODE_HEIGHT, layoutOutcomeGraph } from '../src/OutcomeGraphLayout';

test('shared contained outcomes remain one node with separate parents and parallel relations fit above the cards', () => {
  const nodes = ['parent-a', 'parent-b', 'shared', 'standalone'].map(id => ({ id, title: id, behavior: id, kind: id.startsWith('parent') ? 'composite' as const : 'atomic' as const, labels: [] }));
  const edges = [
    { id: 'a', source: 'parent-a', target: 'shared', kind: 'contains', label: '包含' },
    { id: 'b', source: 'parent-b', target: 'shared', kind: 'contains', label: '包含' },
    ...['prerequisite', 'equivalent', 'overlap'].map(kind => ({ id: kind, source: 'shared', target: 'standalone', kind, label: kind })),
  ];
  const graph = layoutOutcomeGraph(nodes, edges);
  expect(graph.positions.size).toBe(4);
  expect(Math.abs(graph.positions.get('parent-a')!.y - graph.positions.get('parent-b')!.y)).toBeGreaterThan(GRAPH_NODE_HEIGHT);
  expect(graph.lines.every(line => line.y >= 13 && line.y + 13 < graph.height)).toBeTruthy();
  expect(graph.positions.get('shared')!.x).toBeGreaterThan(graph.positions.get('parent-a')!.x);
});

test('real demo graph has containment layout, labeled edge inspection, pan/zoom and a recoverable mobile drawer', async ({ page }) => {
  test.setTimeout(90_000);
  await authorize(page);
  expect((await page.request.get('/api/learning/outcome-graph')).ok()).toBeTruthy();
  const fixture = JSON.parse(execFileSync(resolve('../.venv/bin/python'), [resolve('../scripts/seed-outcome-graph-demo.py'), '--data-dir', process.env.NAUTILUS_E2E_DATA_DIR!, '--demo'], { cwd: resolve('..'), encoding: 'utf8', env: { ...process.env, PYTHONPATH: resolve('../backend'), PYTHONDONTWRITEBYTECODE: '1' } }));
  await page.setViewportSize({ width: 1600, height: 1100 });
  await page.goto(`/?view=records&graph_plan=${fixture.plan_id}`);
  await page.getByRole('button', { name: '成果图', exact: true }).click();
  await expect(page.locator('.outcome-graph__node')).toHaveCount(10);
  const graph = await (await page.request.get(`/api/learning/outcome-graph?plan_id=${fixture.plan_id}`)).json() as OutcomeGraphData;
  const positions = await page.locator('.outcome-graph__node').evaluateAll(elements => Object.fromEntries(elements.map(element => [element.getAttribute('data-outcome'), { x: parseFloat((element as HTMLElement).style.left), y: parseFloat((element as HTMLElement).style.top) }])));
  for (const relation of graph.relations.filter(item => item.relation_type === 'contains')) expect(positions[relation.target_outcome_id].x).toBeGreaterThan(positions[relation.source_outcome_id].x);
  for (const kind of ['contains', 'prerequisite', 'equivalent', 'overlap']) await expect(page.locator(`.outcome-graph__line--${kind}`).first()).toBeAttached();
  const isolated = fixture.outcome_ids.unicode;
  expect(graph.relations.some(item => [item.source_outcome_id, item.target_outcome_id].includes(isolated))).toBeFalsy();
  await expect(page.getByRole('complementary', { name: '成果详情' })).toHaveCount(0);
  await page.screenshot({ path: '/tmp/nautilus-d1-graph-map-desktop.png', fullPage: true });
  const space = page.locator('.outcome-graph__space'), viewport = page.getByRole('group', { name: '成果关系图', exact: true });
  const initial = await space.getAttribute('data-graph-transform');
  await page.getByRole('button', { name: '放大成果图', exact: true }).click();
  expect(await space.getAttribute('data-graph-transform')).not.toEqual(initial);
  const bounds = (await viewport.boundingBox())!;
  const beforePan = await space.getAttribute('data-graph-transform');
  const blank = await viewport.evaluate(element => {
    const box = element.getBoundingClientRect();
    for (let y = 50; y < box.height - 80; y += 40) for (let x = 20; x < box.width - 100; x += 40) {
      const target = document.elementFromPoint(box.left + x, box.top + y);
      if (target && element.contains(target) && !target.closest('[data-graph-interactive]')) return { x: box.left + x, y: box.top + y };
    }
    throw new Error('No blank canvas space found');
  });
  await page.mouse.move(blank.x, blank.y); await page.mouse.down(); await page.mouse.move(blank.x + 82, blank.y + 26, { steps: 8 }); await page.mouse.up();
  expect(await space.getAttribute('data-graph-transform')).not.toEqual(beforePan);
  await expect(page.locator('.outcome-graph__inspector')).toHaveCount(0);
  const beforeWheel = await space.getAttribute('data-graph-transform');
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2); await page.mouse.wheel(0, 200);
  await expect(space).not.toHaveAttribute('data-graph-transform', beforeWheel!);
  await page.getByRole('button', { name: '查看全图', exact: true }).click();
  const relation = graph.relations.find(item => item.relation_type === 'equivalent')!;
  const relationButton = page.locator(`[data-relation="${relation.id}"] [role="button"]`);
  await relationButton.focus(); await page.keyboard.press('Enter');
  const details = page.getByRole('complementary', { name: '关系详情', exact: true });
  await expect(details).toContainText('演示：两个声明');
  await details.getByText('来源与不确定处', { exact: true }).click(); await expect(details).toContainText('成果声明');
  await details.getByText('关系历史（1）', { exact: true }).click(); await expect(details).toContainText('保存关系');
  await page.getByRole('button', { name: '关闭关系详情', exact: true }).click();
  const selected = page.locator(`[data-outcome="${fixture.outcome_ids.extract}"]`);
  await selected.focus(); await selected.click();
  await expect(page.getByRole('complementary', { name: '成果详情', exact: true })).toContainText('不同表现');
  await page.screenshot({ path: '/tmp/nautilus-d1-graph-inspector-desktop.png', fullPage: true });
  await page.getByRole('button', { name: '关闭成果详情', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await expect(page.getByRole('button', { name: '查看全图', exact: true })).toBeInViewport({ ratio: 1 });
  await page.screenshot({ path: '/tmp/nautilus-d1-graph-map-mobile.png', fullPage: true });
  await selected.focus(); await selected.click();
  let drawer = page.getByRole('dialog', { name: '成果详情', exact: true });
  await expect(drawer).toBeVisible();
  await page.keyboard.press('Shift+Tab'); expect(await drawer.evaluate(element => element.contains(document.activeElement))).toBeTruthy();
  await page.screenshot({ path: '/tmp/nautilus-d1-graph-drawer-mobile.png', fullPage: true });
  await page.keyboard.press('Escape'); await expect(drawer).toHaveCount(0); await expect(selected).toBeFocused();
  await selected.click(); drawer = page.getByRole('dialog', { name: '成果详情', exact: true }); await expect(drawer).toBeVisible();
  await drawer.getByRole('button', { name: '添加关系', exact: true }).click();
  const edit = page.getByRole('dialog', { name: '添加关系', exact: true }); await expect(edit).toBeVisible();
  await page.keyboard.press('Escape'); await expect(edit).toHaveCount(0); await expect(drawer).toBeVisible();
  expect(await drawer.evaluate(element => element.contains(document.activeElement))).toBeTruthy();
  await drawer.getByRole('button', { name: '查看原始依据', exact: true }).click();
  const review = page.getByRole('region', { name: '单成果依据回看' }); await expect(review).toBeVisible();
  await review.getByRole('button', { name: '查看这个版本的原始产出', exact: true }).first().click(); await expect(review.getByLabel('原始产出版本')).toContainText('演示/合成');
  await review.getByRole('button', { name: '返回成果图', exact: true }).click(); await expect(page.getByRole('dialog', { name: '成果详情', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '关闭成果详情', exact: true }).click();
});
