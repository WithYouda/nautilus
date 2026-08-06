import { useEffect, useRef, type RefObject } from "react";

export default function useDismissibleLayer(
  open: boolean,
  refs: Array<RefObject<HTMLElement | null>>,
  onDismiss: () => void,
) {
  const refsRef = useRef(refs);
  refsRef.current = refs;
  useEffect(() => {
    if (!open) return;

    const isInside = (target: EventTarget | null) =>
      target instanceof Node && refsRef.current.some((ref) => ref.current?.contains(target));

    const handlePointerDown = (event: PointerEvent) => {
      if (!isInside(event.target)) onDismiss();
    };
    const handleFocusIn = (event: FocusEvent) => {
      if (!isInside(event.target)) onDismiss();
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onDismiss();
    };

    document.addEventListener("pointerdown", handlePointerDown, true);
    document.addEventListener("focusin", handleFocusIn, true);
    document.addEventListener("keydown", handleKeyDown, true);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown, true);
      document.removeEventListener("focusin", handleFocusIn, true);
      document.removeEventListener("keydown", handleKeyDown, true);
    };
  }, [open, onDismiss]);
}
