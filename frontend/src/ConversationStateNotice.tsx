import type useConversationState from './useConversationState';

type State = ReturnType<typeof useConversationState>;
const issueText: Record<string, string> = {
  path_unavailable: '原来选择的回答路径已不可用，请明确选择新的路径。',
  material_unavailable: '所选资料版本已不可用，请打开资料重新选择或明确取消参考。',
  search_unavailable: '所选搜索服务或参数已不可用，请重新选择服务或关闭联网。',
};
export default function ConversationStateNotice({ state, onSelectPath }: { state: State; onSelectPath?: () => void }) {
  return <>
    {state.migration && <section className="conversation-state-notice" aria-label="沿用浏览器学习状态">
      <p>这个浏览器保存了以前的回答路径、资料或联网选择。确认后，它们会保存到服务端，供其他设备继续使用。</p>
      {state.migration.unreadable && <p role="alert">旧浏览器记录无法完整读取，请选择“不沿用，重新选择”；不会自动覆盖服务端。</p>}
      <p>资料：{state.migration.source_scope.mode === 'only' ? '只依据所选资料' : state.migration.source_scope.mode === 'reference' ? '参考所选资料' : '未指定'}，{state.migration.source_scope.version_ids.length} 个版本；联网：{state.migration.search_override ? { off: '关闭', external: '外部服务', native: '模型内置' }[state.migration.search_override.mode] : '沿用默认'}。</p>
      <button type="button" className="button" disabled={state.busy || state.migration.unreadable} onClick={state.confirmMigration}>确认沿用这个浏览器的状态</button>{' '}
      <button type="button" className="button button--quiet" disabled={state.busy} onClick={state.discardMigration}>不沿用，重新选择</button>
    </section>}
    {state.notice && <p role="status">{state.notice}</p>}
    {state.error && <p role="alert">{state.error} <button type="button" className="button button--quiet" onClick={() => void state.retryLoad()}>重新读取学习状态</button></p>}
    {state.snapshot.issues.length > 0 && <section className="conversation-state-notice" role="alert">
      <p>保存的学习条件有失效项。请重新选择后再发送；系统不会自动更换回答路径、资料或搜索服务。</p>
      <ul>{state.snapshot.issues.map(issue => <li key={issue}>{issueText[issue] ?? '一项学习条件不可用，请重新选择。'}</li>)}</ul>
      {onSelectPath && state.snapshot.issues.includes('path_unavailable') && <><p>你可以选择最新可用的回答路径；没有可用历史时，从新问题开始。</p><button type="button" className="button button--quiet" disabled={!state.ready} onClick={onSelectPath}>使用最新可用路径</button></>}
    </section>}
  </>;
}
