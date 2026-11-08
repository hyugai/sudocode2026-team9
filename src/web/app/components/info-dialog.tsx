"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { Asset } from "./chat-panel";

export function InfoDialog({ title, onClose, children, drawer = false, className = "" }: { title: string; onClose: () => void; children: ReactNode; drawer?: boolean; className?: string }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog?.showModal();
    return () => {
      dialog?.close();
      // React can detach the dialog before native focus restoration runs.
      if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true });
    };
  }, []);
  return <dialog ref={ref} className={`info-dialog${drawer ? " account-drawer" : ""} ${className}`} aria-labelledby="dialog-title" onCancel={e => { e.preventDefault(); onClose(); }} onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
    <div className="dialog-content">
      <div className="dialog-header"><h2 id="dialog-title">{title}</h2><button className="icon-button" onClick={onClose} aria-label="Đóng"><Asset name="close" /></button></div>
      {children}
    </div>
  </dialog>;
}
