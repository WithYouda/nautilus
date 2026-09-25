import { useEffect, useRef, useState } from 'react';

type Node = { id: string; parentId: string | null; groupId?: string };
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
  const paths = useRef<Record<string, Record<string, string>>>({});
  if (!paths.current[scope]) {
    let saved: Record<string, string> = {};
    try {
      const value = JSON.parse(window.localStorage.getItem(`${storageKey(scope)}:paths`) ?? '{}');
      if (value && typeof value === 'object' && !Array.isArray(value)) {
        saved = Object.fromEntries(Object.entries(value).filter((entry): entry is [string, string] => typeof entry[1] === 'string'));
      }
    } catch { /* Optional view state. */ }
    paths.current[scope] = saved;
  }
  const remembered = paths.current[scope];
  const byId = new Map(nodes.map(node => [node.id, node]));
  function ancestry(id: string | null) {
    const result: string[] = [];
    const seen = new Set<string>();
    while (id && byId.has(id) && !seen.has(id)) {
      seen.add(id); result.unshift(id); id = byId.get(id)!.parentId;
    }
    return result;
  }
  function select(id: string) {
    for (const ancestor of ancestry(id)) {
      remembered[ancestor] = id;
      const group = byId.get(ancestor)?.groupId;
      if (group) remembered[`group:${group}`] = ancestor;
    }
    setChoices(previous => ({ ...previous, [scope]: id }));
    try {
      window.localStorage.setItem(storageKey(scope), id);
      window.localStorage.setItem(`${storageKey(scope)}:paths`, JSON.stringify(remembered));
    } catch { /* Optional view state. */ }
  }
  useEffect(() => { if (activeId) select(activeId); }, [scope, activeId]);
  let leaf: string | null = activeId ?? choices[scope] ?? savedSelection(scope);
  if (!leaf || !byId.has(leaf)) leaf = nodes.at(-1)?.id ?? null;
  const path = ancestry(leaf);
  function switchVersion(id: string) {
    setFollowing(false);
    const visited = new Set<string>();
    while (!visited.has(id)) {
      visited.add(id);
      // Return to the last viewed descendant, including an older answer version.
      // Only IDs are stored, and every restored relation is checked against live data.
      const saved = remembered[id];
      if (saved && byId.has(saved) && ancestry(saved).includes(id)) { id = saved; break; }
      const child = nodes.filter(node => node.parentId === id).at(-1);
      if (!child) break;
      id = child.id;
    }
    select(id);
  }
  function preferredVersion(groupId: string, fallback: string) {
    const id = remembered[`group:${groupId}`];
    return id && byId.get(id)?.groupId === groupId ? id : fallback;
  }
  return { path, leaf, select, switchVersion, preferredVersion, following };
}
