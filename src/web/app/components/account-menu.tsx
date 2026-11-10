"use client";

import { useEffect, useId, useRef, type RefObject } from "react";
import { AccountQuickLinks, type AccountView } from "./account-content";

export function AccountMenu({ open, onOpenChange, activeView, className = "", triggerRef: suppliedTriggerRef }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  activeView?: AccountView | "orders";
  className?: string;
  triggerRef?: RefObject<HTMLButtonElement | null>;
}) {
  const menuRef = useRef<HTMLDivElement>(null);
  const internalTriggerRef = useRef<HTMLButtonElement>(null);
  const triggerRef = suppliedTriggerRef ?? internalTriggerRef;
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: Event) => {
      if (event.target instanceof Node && !menuRef.current?.contains(event.target)) onOpenChange(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      onOpenChange(false);
      triggerRef.current?.focus({ preventScroll: true });
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("focusin", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("focusin", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open, onOpenChange, triggerRef]);

  return <div className={`account-menu ${className}`} ref={menuRef}>
    <button type="button" ref={triggerRef} className="account-trigger" aria-label="Mở menu tài khoản" title="Tài khoản" aria-controls={menuId} aria-expanded={open} onClick={() => onOpenChange(!open)} onKeyDown={event => {
      if (event.key !== "ArrowDown") return;
      event.preventDefault();
      onOpenChange(true);
      requestAnimationFrame(() => menuRef.current?.querySelector<HTMLAnchorElement>(".account-quick-links a")?.focus());
    }}>
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.41667" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="10" cy="6.66667" r="3.33333" />
        <path d="M3.33333 18.3333V16.6667a6.66667 6.66667 0 0 1 13.33334 0v1.6666" />
      </svg>
      <span>Tài khoản</span>
    </button>
    {open && <div id={menuId} className="account-popover"><AccountQuickLinks activeView={activeView} onNavigate={() => onOpenChange(false)} /></div>}
  </div>;
}
