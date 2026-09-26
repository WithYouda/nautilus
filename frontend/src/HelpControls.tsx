import type { HelpRequestKind } from './api';

const choices: Array<[HelpRequestKind, string]> = [
  ['hint', '给个提示'], ['explain_step', '只解释这一步'],
  ['example', '换个例子'], ['try_first', '让我先试试'],
];

export default function HelpControls({ onChoose, disabled }: { onChoose: (kind: HelpRequestKind, text: string) => void; disabled?: boolean }) {
  return <div className="help-controls" aria-label="提问方式">
    {choices.map(([kind, label]) => <button key={kind} className="button button--quiet button--compact" type="button" disabled={disabled} onClick={() => onChoose(kind, label)}>{label}</button>)}
  </div>;
}
