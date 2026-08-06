import type { ReactNode } from "react";
import { createPortal } from "react-dom";

/** Keep modal layers outside scrollable workspace positioning contexts. */
export default function DialogPortal({ children }: { children: ReactNode }) {
  if (typeof document === "undefined") return null;
  return createPortal(children, document.body);
}
