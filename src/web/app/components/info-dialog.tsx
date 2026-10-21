"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { Asset } from "./chat-panel";

export function InfoDialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  return <dialog ref={ref} className="info-dialog" aria-labelledby="dialog-title" onCancel={e => { e.preventDefault(); onClose(); }} onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
    <div className="dialog-content">
      <div className="dialog-header"><h2 id="dialog-title">{title}</h2><button className="icon-button" onClick={onClose} aria-label="Đóng"><Asset name="close" /></button></div>
      {children}
    </div>
  </dialog>;
}
