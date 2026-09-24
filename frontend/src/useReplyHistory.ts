import { useEffect, useState } from 'react';

type Node = { id: string; parentId: string | null };
const storageKey = (scope: string) => `nautilus.reply-selection.v1:${scope}`;
function savedSelection(scope: string) {
  try { return window.localStorage.getItem(storageKey(scope)); } catch { return null; }
}

// An answer version owns its descendants. Selecting an older version restores
// that path; regenerating it creates a new leaf without erasing the old path.
export default function useReplyHistory(scope: string, nodes: Node[], activeId?: string | null) {
  const [following, setFollowing] = useState(true);
  useEffect(() => { setFollowing(true); }, [scope, activeId]);
  const [choices, setChoices] = useState<Record<string, string>>({});
  function select(id: string) {
    setChoices(previous => ({ ...previous, [scope]: id }));
    try { window.localStorage.setItem(storageKey(scope), id); } catch { /* Optional view state. */ }
  }
  useEffect(() => { if (activeId) select(activeId); }, [scope, activeId]);
  const byId = new Map(nodes.map(node => [node.id, node]));
  let leaf: string | null = activeId ?? choices[scope] ?? savedSelection(scope);
  if (!leaf || !byId.has(leaf)) leaf = nodes.at(-1)?.id ?? null;
  const path: string[] = [];
  const seen = new Set<string>();
  let cursor: string | null = leaf;
  while (cursor && byId.has(cursor) && !seen.has(cursor)) {
    seen.add(cursor); path.unshift(cursor); cursor = byId.get(cursor)!.parentId;
  }
  function switchVersion(id: string) {
    setFollowing(false);
    const visited = new Set<string>();
    while (!visited.has(id)) {
      visited.add(id);
      const child = nodes.filter(node => node.parentId === id).at(-1);
      if (!child) break;
      id = child.id;
    }
    select(id);
  }
  return { path, leaf, select, switchVersion, following };
}
