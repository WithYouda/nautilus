import type { GraphEdgeDisplay, GraphNodeDisplay } from './OutcomeGraphCanvas';

export const GRAPH_NODE_WIDTH = 224;
export const GRAPH_NODE_HEIGHT = 96;
const COLUMN_STEP = 320;
const ROW_STEP = 118;
const MARGIN = 40;
export type GraphPosition = { x: number; y: number };
export type GraphLine = GraphEdgeDisplay & { path: string; x: number; y: number };

/** Containment determines levels. Other relations never invent a parent or duplicate a node. */
export function layoutOutcomeGraph(nodes: GraphNodeDisplay[], edges: GraphEdgeDisplay[]) {
  const positions = new Map<string, GraphPosition>();
  const ids = new Set(nodes.map(node => node.id));
  const contains = edges.filter(edge => edge.kind === 'contains' && ids.has(edge.source) && ids.has(edge.target));
  const neighbors = new Map(nodes.map(node => [node.id, new Set<string>()]));
  for (const edge of contains) { neighbors.get(edge.source)!.add(edge.target); neighbors.get(edge.target)!.add(edge.source); }
  const visited = new Set<string>();
  const groups: string[][] = [];
  for (const node of nodes) {
    if (visited.has(node.id) || !neighbors.get(node.id)!.size) continue;
    const group: string[] = [], pending = [node.id];
    while (pending.length) { const id = pending.pop()!; if (visited.has(id)) continue; visited.add(id); group.push(id); pending.push(...neighbors.get(id)!); }
    groups.push(group);
  }
  let offsetY = MARGIN, maximumX = MARGIN + GRAPH_NODE_WIDTH;
  for (const group of groups) {
    const groupIds = new Set(group), incoming = new Map(group.map(id => [id, 0])), depth = new Map(group.map(id => [id, 0]));
    const links = contains.filter(edge => groupIds.has(edge.source));
    for (const edge of links) incoming.set(edge.target, incoming.get(edge.target)! + 1);
    const pending = group.filter(id => incoming.get(id) === 0);
    while (pending.length) {
      const id = pending.shift()!;
      for (const edge of links.filter(link => link.source === id)) {
        depth.set(edge.target, Math.max(depth.get(edge.target)!, depth.get(id)! + 1));
        incoming.set(edge.target, incoming.get(edge.target)! - 1);
        if (incoming.get(edge.target) === 0) pending.push(edge.target);
      }
    }
    const layers: string[][] = [];
    // Keep the API order within a level until a real parent position can order it.
    for (const node of nodes) if (groupIds.has(node.id)) (layers[depth.get(node.id)!] ??= []).push(node.id);
    const parentOrder = (id: string) => {
      const parents = links.filter(edge => edge.target === id).map(edge => layers[depth.get(edge.source)!].indexOf(edge.source));
      return parents.length ? parents.reduce((a, b) => a + b, 0) / parents.length : 0;
    };
    for (const layer of layers) layer.sort((a, b) => parentOrder(a) - parentOrder(b));
    const groupHeight = Math.max(...layers.map(layer => layer.length)) * ROW_STEP - (ROW_STEP - GRAPH_NODE_HEIGHT);
    layers.forEach((layer, level) => layer.forEach((id, index) => {
      positions.set(id, { x: MARGIN + level * COLUMN_STEP, y: offsetY + (groupHeight - (layer.length * ROW_STEP - (ROW_STEP - GRAPH_NODE_HEIGHT))) / 2 + index * ROW_STEP });
    }));
    for (let level = layers.length - 2; level >= 0; level--) {
      for (const id of layers[level]) {
        const children = links.filter(edge => edge.source === id).map(edge => positions.get(edge.target)!);
        if (children.length) positions.get(id)!.y = children.reduce((total, position) => total + position.y, 0) / children.length;
      }
      // Shared children are valid: keep each parent's identity visible in its own card.
      let previousY = offsetY - ROW_STEP;
      for (const id of [...layers[level]].sort((a, b) => positions.get(a)!.y - positions.get(b)!.y)) {
        const position = positions.get(id)!; position.y = Math.max(position.y, previousY + ROW_STEP); previousY = position.y;
      }
    }
    maximumX = Math.max(maximumX, MARGIN + (layers.length - 1) * COLUMN_STEP + GRAPH_NODE_WIDTH);
    offsetY = Math.max(...group.map(id => positions.get(id)!.y + GRAPH_NODE_HEIGHT)) + 60;
  }
  // Nodes outside containment stay separate. Real cross-relations are still drawn between them.
  const remaining = nodes.filter(node => !visited.has(node.id));
  const columns = Math.min(3, remaining.length);
  const vacant = [...positions.values()].filter(position => position.x === MARGIN).sort((a, b) => a.y - b.y);
  let vacantY = MARGIN;
  remaining.forEach((node, index) => {
    while (vacant.some(position => Math.abs(position.y - vacantY) < ROW_STEP)) vacantY += ROW_STEP;
    const inVacancy = groups.length > 0 && vacantY + GRAPH_NODE_HEIGHT < offsetY - 60;
    const x = inVacancy ? MARGIN : MARGIN + (index % columns) * COLUMN_STEP;
    const y = inVacancy ? vacantY : offsetY + Math.floor(index / columns) * ROW_STEP;
    positions.set(node.id, { x, y }); maximumX = Math.max(maximumX, x + GRAPH_NODE_WIDTH);
    if (inVacancy) { vacant.push({ x, y }); vacantY += ROW_STEP; }
  });
  offsetY = Math.max(...[...positions.values()].map(position => position.y + GRAPH_NODE_HEIGHT));
  const archOrder = new Map<string, number>();
  let topShift = 0;
  const needsTopLane = (edge: GraphEdgeDisplay) => {
    const a = positions.get(edge.source), b = positions.get(edge.target);
    return !!a && !!b && (Math.abs(a.x - b.x) > COLUMN_STEP || (edge.kind !== 'contains' && Math.abs(a.x - b.x) > 1 && Math.abs(a.y - b.y) >= GRAPH_NODE_HEIGHT));
  };
  const topLaneCount = edges.filter(needsTopLane).length;
  if (topLaneCount) topShift = Math.max(0, 40 + topLaneCount * 26 - Math.min(...[...positions.values()].map(position => position.y)));
  for (const edge of edges) {
    const a = positions.get(edge.source), b = positions.get(edge.target);
    if (!a || !b || edge.kind === 'contains' || Math.abs(a.y - b.y) >= GRAPH_NODE_HEIGHT) continue;
    const pair = [edge.source, edge.target].sort().join(':');
    const order = archOrder.get(pair) ?? 0; archOrder.set(pair, order + 1);
    topShift = Math.max(topShift, 16 - (Math.min(a.y, b.y) - 38 - order * 30));
  }
  if (topShift) { for (const position of positions.values()) position.y += topShift; offsetY += topShift; }
  const pairOrder = new Map<string, number>();
  const lines: GraphLine[] = [];
  let topLane = 0;
  for (const edge of edges) {
    const a = positions.get(edge.source), b = positions.get(edge.target);
    if (!a || !b) continue;
    const pair = [edge.source, edge.target].sort().join(':');
    const order = pairOrder.get(pair) ?? 0; pairOrder.set(pair, order + 1);
    if (needsTopLane(edge)) {
      const rightward = b.x > a.x;
      const x1 = a.x + (rightward ? GRAPH_NODE_WIDTH : 0), x2 = b.x + (rightward ? 0 : GRAPH_NODE_WIDTH);
      const y1 = a.y + GRAPH_NODE_HEIGHT / 2, y2 = b.y + GRAPH_NODE_HEIGHT / 2;
      const corridor1 = x1 + (rightward ? 22 : -22), corridor2 = x2 + (rightward ? -22 : 22), laneY = 16 + topLane++ * 26;
      // Vertical corridors lie between columns; the connecting lane lies above every card.
      lines.push({ ...edge, path: `M ${x1} ${y1} L ${corridor1} ${y1} L ${corridor1} ${laneY} L ${corridor2} ${laneY} L ${corridor2} ${y2} L ${x2} ${y2}`, x: (corridor1 + corridor2) / 2, y: laneY });
    } else if (edge.kind === 'contains') {
      const x1 = a.x + GRAPH_NODE_WIDTH, y1 = a.y + GRAPH_NODE_HEIGHT / 2;
      const x2 = b.x, y2 = b.y + GRAPH_NODE_HEIGHT / 2;
      const middle = (x1 + x2) / 2 + order * 16;
      lines.push({ ...edge, path: `M ${x1} ${y1} C ${middle} ${y1}, ${middle} ${y2}, ${x2} ${y2}`, x: middle, y: (y1 + y2) / 2 });
    } else if (Math.abs(a.y - b.y) < GRAPH_NODE_HEIGHT) {
      const x1 = a.x + GRAPH_NODE_WIDTH / 2, x2 = b.x + GRAPH_NODE_WIDTH / 2;
      const top = Math.min(a.y, b.y) - 38 - order * 30;
      lines.push({ ...edge, path: `M ${x1} ${a.y} C ${x1} ${top}, ${x1} ${top}, ${(x1 + x2) / 2} ${top} S ${x2} ${top}, ${x2} ${b.y}`, x: (x1 + x2) / 2, y: top });
    } else {
      // Route beside the occupied columns instead of through the cards between endpoints.
      const right = maximumX + 44 + lines.filter(line => line.kind !== 'contains').length * 20;
      const x1 = a.x + GRAPH_NODE_WIDTH, y1 = a.y + GRAPH_NODE_HEIGHT / 2;
      const x2 = b.x + GRAPH_NODE_WIDTH, y2 = b.y + GRAPH_NODE_HEIGHT / 2;
      const side = Math.abs(a.x - b.x) < 1 ? a.x + GRAPH_NODE_WIDTH + 42 + lines.filter(line => line.kind !== 'contains').length * 30 : right;
      lines.push({ ...edge, path: `M ${x1} ${y1} C ${side} ${y1}, ${side} ${y1}, ${side} ${(y1 + y2) / 2} S ${side} ${y2}, ${x2} ${y2}`, x: side, y: (y1 + y2) / 2 });
      maximumX = Math.max(maximumX, side + 26);
    }
  }
  return { positions, lines, width: maximumX + MARGIN, height: offsetY + MARGIN };
}
