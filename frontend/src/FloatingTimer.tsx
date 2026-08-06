import { Grip, Minus, Pause, Play, Square, X } from "lucide-react";
import { createPortal } from "react-dom";
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from "react";
import type { Task, TimerSnapshot } from "./api";

const POSITION_KEY = "nautilus.v6.timer-position";
const SAFE_GAP = 12;
const HEADER_CLEARANCE = 74;
const DEFAULT_POSITION: NormalizedPosition = { xRatio: 1, yRatio: 0.05 };

type ScreenPosition = { x: number; y: number };
type NormalizedPosition = { xRatio: number; yRatio: number };
type StoredPosition =
  | { kind: "normalized"; value: NormalizedPosition }
  | { kind: "legacy"; value: ScreenPosition }
  | null;
type PositionBounds = { minX: number; maxX: number; minY: number; maxY: number };

function readPosition(): StoredPosition {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(POSITION_KEY) ?? "null") as {
      version?: unknown;
      xRatio?: unknown;
      yRatio?: unknown;
      x?: unknown;
      y?: unknown;
    } | null;
    if (
      parsed?.version === 2 &&
      typeof parsed.xRatio === "number" && Number.isFinite(parsed.xRatio) &&
      typeof parsed.yRatio === "number" && Number.isFinite(parsed.yRatio)
    ) {
      return {
        kind: "normalized",
        value: { xRatio: clamp01(parsed.xRatio), yRatio: clamp01(parsed.yRatio) },
      };
    }
    if (
      typeof parsed?.x === "number" && Number.isFinite(parsed.x) &&
      typeof parsed.y === "number" && Number.isFinite(parsed.y)
    ) {
      return { kind: "legacy", value: { x: parsed.x, y: parsed.y } };
    }
  } catch {
    // Invalid saved layout falls back to the safe default position.
  }
  return null;
}

export default function FloatingTimer({
  timer,
  task,
  busy,
  boundaryRef,
  onAction,
}: {
  timer: TimerSnapshot | null;
  task: Task | null;
  busy: boolean;
  boundaryRef: RefObject<HTMLElement | null>;
  onAction: (taskId: string, action: "pause" | "resume" | "finish") => void;
}) {
  const [minimized, setMinimized] = useState(false);
  const [hidden, setHidden] = useState(false);
  const [storedPosition] = useState(readPosition);
  const [position, setPosition] = useState<ScreenPosition | null>(null);
  const overlayRef = useRef<HTMLElement | null>(null);
  const normalizedRef = useRef<NormalizedPosition | null>(
    storedPosition?.kind === "normalized" ? storedPosition.value : null,
  );
  const legacyRef = useRef<ScreenPosition | null>(
    storedPosition?.kind === "legacy" ? storedPosition.value : null,
  );
  const positionRef = useRef<ScreenPosition | null>(null);
  const dragRef = useRef<{ offsetX: number; offsetY: number } | null>(null);

  useEffect(() => {
    if (timer) setHidden(false);
  }, [timer?.id]);

  useLayoutEffect(() => {
    if (!timer) return;
    let frame = 0;
    const placeInsideBoundary = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        const bounds = getPositionBounds(boundaryRef.current, overlayRef.current);
        if (!bounds) return;
        if (window.matchMedia("(max-width: 760px)").matches) {
          // Mobile uses a bottom-safe fixed bar; keep desktop drag coordinates untouched.
          setPosition({ x: 0, y: 0 });
          return;
        }

        let next: ScreenPosition;
        if (legacyRef.current) {
          const boundary = boundaryRef.current!.getBoundingClientRect();
          const legacyFitsCurrentBoundary =
            legacyRef.current.x >= SAFE_GAP &&
            legacyRef.current.x <= boundary.width - overlayRef.current!.offsetWidth - SAFE_GAP &&
            legacyRef.current.y >= HEADER_CLEARANCE &&
            legacyRef.current.y <= boundary.height - overlayRef.current!.offsetHeight - SAFE_GAP;
          next = legacyFitsCurrentBoundary
            ? clampPosition({
              x: boundary.left + legacyRef.current.x,
              y: boundary.top + legacyRef.current.y,
            }, bounds)
            : denormalizePosition(DEFAULT_POSITION, bounds);
          legacyRef.current = null;
          normalizedRef.current = normalizePosition(next, bounds);
          persistPosition(normalizedRef.current);
        } else {
          const normalized = normalizedRef.current ?? DEFAULT_POSITION;
          next = denormalizePosition(normalized, bounds);
          normalizedRef.current = normalizePosition(next, bounds);
        }
        positionRef.current = next;
        setPosition(next);
      });
    };

    placeInsideBoundary();
    const observer = new ResizeObserver(placeInsideBoundary);
    if (boundaryRef.current) observer.observe(boundaryRef.current);
    if (overlayRef.current) observer.observe(overlayRef.current);
    window.addEventListener("resize", placeInsideBoundary);
    window.visualViewport?.addEventListener("resize", placeInsideBoundary);
    window.visualViewport?.addEventListener("scroll", placeInsideBoundary);
    return () => {
      window.cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("resize", placeInsideBoundary);
      window.visualViewport?.removeEventListener("resize", placeInsideBoundary);
      window.visualViewport?.removeEventListener("scroll", placeInsideBoundary);
    };
  }, [boundaryRef, hidden, minimized, timer?.id]);

  if (!timer || !task || typeof document === "undefined") return null;

  const seconds = timer.remaining_seconds ?? timer.elapsed_seconds;
  const label = timer.phase === "break" ? "BREAK" : "FOCUS";
  const overlayStyle = position
    ? { left: `${position.x}px`, top: `${position.y}px` }
    : { left: "-9999px", top: "-9999px", visibility: "hidden" as const };

  function startDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    if (window.matchMedia("(max-width: 760px)").matches) return;
    const card = overlayRef.current;
    if (!card) return;
    const cardRect = card.getBoundingClientRect();
    dragRef.current = {
      offsetX: event.clientX - cardRect.left,
      offsetY: event.clientY - cardRect.top,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function drag(event: ReactPointerEvent<HTMLButtonElement>) {
    const start = dragRef.current;
    const bounds = getPositionBounds(boundaryRef.current, overlayRef.current);
    if (!start || !bounds) return;
    const next = clampPosition({
      x: event.clientX - start.offsetX,
      y: event.clientY - start.offsetY,
    }, bounds);
    positionRef.current = next;
    normalizedRef.current = normalizePosition(next, bounds);
    setPosition(next);
  }

  function endDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    if (!dragRef.current) return;
    dragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (normalizedRef.current) persistPosition(normalizedRef.current);
  }

  const content = hidden ? (
    <button
      ref={(node) => { overlayRef.current = node; }}
      className="v6-timer-restore"
      style={overlayStyle}
      type="button"
      onClick={() => setHidden(false)}
    >
      显示计时器 · {formatSeconds(seconds)}
    </button>
  ) : (
    <section
      ref={(node) => { overlayRef.current = node; }}
      className={`v6-floating-timer${minimized ? " is-minimized" : ""}`}
      style={overlayStyle}
      aria-label="活动学习计时"
    >
      <button
        className="v6-timer-drag"
        type="button"
        aria-label="拖动计时器"
        onPointerDown={startDrag}
        onPointerMove={drag}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        <Grip size={15} />
      </button>
      <div className="v6-timer-copy">
        <span>{label} / {timer.status === "paused" ? "PAUSED" : "LIVE"}</span>
        <strong>{formatSeconds(seconds)}</strong>
        <small>{task.title}</small>
      </div>
      <div className="v6-timer-actions">
        <button type="button" disabled={busy} onClick={() => onAction(timer.task_id, timer.status === "running" ? "pause" : "resume")} aria-label={timer.status === "running" ? "暂停计时" : "继续计时"}>
          {timer.status === "running" ? <Pause size={14} /> : <Play size={14} />}
        </button>
        <button type="button" disabled={busy} onClick={() => onAction(timer.task_id, "finish")} aria-label="结束计时"><Square size={13} /></button>
        <button type="button" onClick={() => setMinimized((value) => !value)} aria-label={minimized ? "展开计时器" : "最小化计时器"}><Minus size={14} /></button>
        <button type="button" onClick={() => setHidden(true)} aria-label="隐藏计时器"><X size={14} /></button>
      </div>
    </section>
  );

  return createPortal(content, document.body);
}

function getPositionBounds(boundary: HTMLElement | null, overlay: HTMLElement | null): PositionBounds | null {
  if (!boundary || !overlay) return null;
  const boundaryRect = boundary.getBoundingClientRect();
  const visualViewport = window.visualViewport;
  const viewportLeft = visualViewport?.offsetLeft ?? 0;
  const viewportTop = visualViewport?.offsetTop ?? 0;
  const viewportRight = viewportLeft + (visualViewport?.width ?? window.innerWidth);
  const viewportBottom = viewportTop + (visualViewport?.height ?? window.innerHeight);
  const minX = Math.max(boundaryRect.left + SAFE_GAP, viewportLeft + SAFE_GAP);
  const rightEdge = Math.min(boundaryRect.right - SAFE_GAP, viewportRight - SAFE_GAP);
  const minY = Math.max(boundaryRect.top + HEADER_CLEARANCE, viewportTop + SAFE_GAP);
  const bottomEdge = Math.min(boundaryRect.bottom - SAFE_GAP, viewportBottom - SAFE_GAP);
  return {
    minX,
    maxX: Math.max(minX, rightEdge - overlay.offsetWidth),
    minY,
    maxY: Math.max(minY, bottomEdge - overlay.offsetHeight),
  };
}

function clampPosition(position: ScreenPosition, bounds: PositionBounds): ScreenPosition {
  return {
    x: Math.min(bounds.maxX, Math.max(bounds.minX, position.x)),
    y: Math.min(bounds.maxY, Math.max(bounds.minY, position.y)),
  };
}

function normalizePosition(position: ScreenPosition, bounds: PositionBounds): NormalizedPosition {
  const availableX = bounds.maxX - bounds.minX;
  const availableY = bounds.maxY - bounds.minY;
  return {
    xRatio: availableX > 0 ? clamp01((position.x - bounds.minX) / availableX) : 0,
    yRatio: availableY > 0 ? clamp01((position.y - bounds.minY) / availableY) : 0,
  };
}

function denormalizePosition(position: NormalizedPosition, bounds: PositionBounds): ScreenPosition {
  return clampPosition({
    x: bounds.minX + clamp01(position.xRatio) * (bounds.maxX - bounds.minX),
    y: bounds.minY + clamp01(position.yRatio) * (bounds.maxY - bounds.minY),
  }, bounds);
}

function persistPosition(position: NormalizedPosition) {
  try {
    window.localStorage.setItem(POSITION_KEY, JSON.stringify({
      version: 2,
      xRatio: clamp01(position.xRatio),
      yRatio: clamp01(position.yRatio),
    }));
  } catch {
    // The timer remains bounded even when browser storage is unavailable.
  }
}

function clamp01(value: number) {
  return Math.min(1, Math.max(0, value));
}

function formatSeconds(value: number) {
  const safe = Math.max(0, Math.floor(value));
  const minutes = Math.floor(safe / 60).toString().padStart(2, "0");
  const seconds = (safe % 60).toString().padStart(2, "0");
  return `${minutes}:${seconds}`;
}
