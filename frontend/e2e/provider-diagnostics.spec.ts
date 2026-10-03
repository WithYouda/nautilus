import { expect, test } from '@playwright/test';
import type { DiagnosticEntry } from '../src/diagnostics';
import { authorize } from './fact-helpers';

test('provider diagnostics explain retries, recovery and final results without mixing HTTP and AI runs', async ({ page }) => {
  await authorize(page);
  await page.getByRole('button', { name: '设置', exact: true }).click();
  const settings = page.getByRole('dialog', { name: '设置', exact: true });
  await settings.getByText('高级设置', { exact: true }).click();
  await expect(settings.getByLabel('开启诊断日志')).not.toBeChecked();
  await settings.getByLabel('开启诊断日志').click();
  await expect(settings.getByLabel('开启诊断日志')).toBeChecked();

  const common = { at: '2026-10-03T04:00:00Z', module: 'ai', scope_kind: 'conversation' as const, provider_kind: 'openai_compatible', target_host: 'model.example', max_attempts: 3 };
  const entries: DiagnosticEntry[] = [
    { ...common, id: 'retry-dns', level: 'warning', event: 'provider.retry', run_id: 'run-recovered', phase: 'initial_response', request_seq: 1, attempt: 1, retry_delay_ms: 500, code: 'dns_temporary', error_stage: 'dns', error_type: 'ConnectError', cause_type: 'gaierror', errno: -3 },
    { ...common, id: 'retry-connect', level: 'warning', event: 'provider.retry', run_id: 'run-recovered', phase: 'initial_response', request_seq: 1, attempt: 2, retry_delay_ms: 1000, code: 'connection_refused', error_stage: 'connect', error_type: 'ConnectError', cause_type: 'ConnectionRefusedError', errno: 111 },
    { ...common, id: 'recovered', level: 'info', event: 'provider.recovered', run_id: 'run-recovered', phase: 'initial_response', request_seq: 1, attempt: 3, result: 'connected' },
    { at: common.at, id: 'run-success', module: 'ai', level: 'info', event: 'ai.run_finished', scope_kind: 'conversation', run_id: 'run-recovered', result: 'succeeded' },
    { ...common, id: 'failed-continuation', level: 'error', event: 'provider.failed', run_id: 'run-failed', request_id: 'http-continuation', phase: 'tool_continuation', request_seq: 2, attempt: 1, result: 'failed', code: 'read_timeout', error_stage: 'read', error_type: 'ReadTimeout' },
    { at: common.at, id: 'run-failure', module: 'ai', level: 'error', event: 'ai.run_finished', scope_kind: 'conversation', run_id: 'run-failed', result: 'failed', code: 'read_timeout' },
    { ...common, id: 'failed-history', level: 'error', event: 'provider.failed', scope_kind: 'discussion', run_id: 'run-history', phase: 'history_selection', request_seq: 1, attempt: 1, result: 'failed', status: 401, code: 'http_auth', error_stage: 'http' },
    { ...common, id: 'failed-title', level: 'error', event: 'provider.failed', run_id: 'run-title', phase: 'title', request_seq: 1, attempt: 1, result: 'failed', code: 'tls_certificate', error_stage: 'tls', error_type: 'ConnectError', cause_type: 'SSLCertVerificationError', errno: 1 },
    { ...common, id: 'failed-request', level: 'error', event: 'provider.failed', run_id: 'run-request', phase: 'provider_request', request_seq: 1, attempt: 1, result: 'failed', code: 'pool_timeout', error_stage: 'pool', error_type: 'PoolTimeout' },
    { at: common.at, id: 'run-canceled', module: 'ai', level: 'info', event: 'ai.run_finished', scope_kind: 'discussion', run_id: 'run-canceled', result: 'canceled', code: 'canceled' },
    { at: common.at, id: 'http-not-found', module: 'ai', level: 'warning', event: 'request.finished', method: 'GET', route: '/api/ai/conversations/{conversation_id}', status: 404, duration_ms: 12, code: 'HTTP_404', request_id: 'http-404' },
    { at: common.at, id: 'purge-partial', module: 'materials', level: 'warning', event: 'material.purge', result: 'partial', cleared_count: 7, failed_count: 2, request_id: 'http-purge-partial' },
    { at: common.at, id: 'purge-complete', module: 'materials', level: 'info', event: 'material.purge', result: 'complete', cleared_count: 9, failed_count: 0, request_id: 'http-purge-complete' },
  ];
  await page.route('**/api/diagnostics', async route => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({ json: { enabled: true, storage_error: false, retention_bytes: 4 * 1024 * 1024, entries: entries.map(entry => ({ ...entry, message: 'private-provider-message', request_body: 'private-prompt-body', api_key: 'private-key-value' })) } });
  });
  await settings.getByRole('button', { name: '打开日志窗口' }).click();
  const panel = page.getByRole('dialog', { name: '诊断日志', exact: true });
  await expect(panel).toBeVisible();
  await panel.getByRole('button', { name: '最大化日志' }).click();
  await panel.getByRole('button', { name: '暂停刷新' }).click();
  await expect(panel.locator('article')).toHaveCount(entries.length);

  const firstRetry = panel.locator('article').filter({ hasText: 'dns_temporary' });
  await expect(firstRetry).toContainText('模型服务连接失败，准备重试');
  await expect(firstRetry).toContainText('普通对话');
  await expect(firstRetry).toContainText('阶段：首次模型请求');
  await expect(firstRetry).toContainText('模型请求第1轮');
  await expect(firstRetry).toContainText('目标：model.example');
  await expect(firstRetry).toContainText('接口：OpenAI 兼容接口');
  await expect(firstRetry).toContainText('第1/3次');
  await expect(firstRetry).toContainText('下次等待500ms');
  await expect(firstRetry).toContainText('域名解析暂时失败');
  await expect(firstRetry).toContainText('失败阶段：域名解析');
  await firstRetry.getByText('技术详情', { exact: true }).click();
  await expect(firstRetry.getByText('异常类型：ConnectError', { exact: true })).toBeVisible();
  await expect(firstRetry.getByText('底层异常：gaierror', { exact: true })).toBeVisible();
  await expect(firstRetry.getByText('系统错误号 errno：-3', { exact: true })).toBeVisible();
  const secondRetry = panel.locator('article').filter({ hasText: 'connection_refused' });
  await expect(secondRetry).toContainText('连接被拒绝');
  await expect(secondRetry).toContainText('第2/3次');
  await expect(secondRetry).toContainText('下次等待1000ms');

  const recovered = panel.locator('article').filter({ hasText: '模型服务连接已恢复' });
  await expect(recovered).toContainText('第3/3次');
  await expect(recovered).toContainText('连接成功');
  await expect(recovered).not.toContainText('成功完成');
  await expect(recovered).not.toContainText('下次等待');
  await expect(recovered).toContainText('AI 运行编号：run-recovered');
  const success = panel.locator('article').filter({ hasText: '成功完成' });
  await expect(success).toContainText('AI 运行结束');
  await expect(success).toContainText('AI 运行编号：run-recovered');
  await expect(success).not.toContainText('未全部完成');

  const continuation = panel.locator('article').filter({ hasText: 'HTTP 请求编号：http-continuation' });
  await expect(continuation).toContainText('模型请求失败，不再重试 · 失败');
  await expect(continuation).toContainText('阶段：工具结果续接');
  await expect(continuation).toContainText('模型请求第2轮');
  await expect(continuation).toContainText('读取响应超时');
  await expect(continuation).toContainText('read_timeout');
  await expect(continuation).toContainText('AI 运行编号：run-failed');
  await expect(continuation).not.toContainText('下次等待');
  const failure = panel.locator('article').filter({ hasText: 'AI 运行结束 · 失败' });
  await expect(failure).toContainText('AI 运行编号：run-failed');
  await expect(failure).not.toContainText('未全部完成');
  await expect(panel.locator('article').filter({ hasText: 'run-history' })).toContainText('题目讨论');
  await expect(panel.locator('article').filter({ hasText: 'run-history' })).toContainText('阶段：历史记录筛选');
  await expect(panel.locator('article').filter({ hasText: 'http_auth' })).toContainText('模型服务拒绝认证');
  await expect(panel.locator('article').filter({ hasText: 'run-title' })).toContainText('阶段：生成标题');
  await expect(panel.locator('article').filter({ hasText: 'tls_certificate' })).toContainText('安全证书验证失败');
  await expect(panel.locator('article').filter({ hasText: 'run-request' })).toContainText('阶段：模型请求');
  await expect(panel.locator('article').filter({ hasText: 'pool_timeout' })).toContainText('等待可用连接超时');
  const canceled = panel.locator('article').filter({ hasText: 'AI 运行结束 · 已取消' });
  await expect(canceled).toContainText('请求已取消');
  await expect(canceled).not.toContainText('未全部完成');

  const http = panel.locator('article').filter({ hasText: 'HTTP_404' });
  await expect(http).toContainText('请求结束 · GET /api/ai/conversations/{conversation_id} · 404 · 12 ms');
  await expect(http).toContainText('HTTP 请求编号：http-404');
  await expect(http).not.toContainText('AI 运行编号');
  await expect(panel.locator('article').filter({ hasText: 'http-purge-partial' })).toContainText('资料清除 · 未全部完成');
  await expect(panel.locator('article').filter({ hasText: 'http-purge-partial' })).toContainText('完成 7 项，失败 2 项');
  await expect(panel.locator('article').filter({ hasText: 'http-purge-complete' })).toContainText('资料清除 · 完成');
  await expect(panel.locator('article').filter({ hasText: 'http-purge-complete' })).toContainText('完成 9 项，失败 0 项');
  await expect(panel).not.toContainText('private-provider-message');
  await expect(panel).not.toContainText('private-prompt-body');
  await expect(panel).not.toContainText('private-key-value');
  await panel.getByLabel('级别', { exact: true }).selectOption('error');
  await expect(panel).not.toContainText('准备重试');
  await expect(panel).not.toContainText('成功完成');
  await expect(panel).toContainText('AI 运行结束 · 失败');

  await panel.getByRole('button', { name: '最小化日志' }).click();
  await page.unroute('**/api/diagnostics');
  await page.getByRole('button', { name: '设置', exact: true }).click();
  await settings.getByText('高级设置', { exact: true }).click();
  await settings.getByLabel('开启诊断日志').click();
  await expect(settings.getByLabel('开启诊断日志')).not.toBeChecked();
});
