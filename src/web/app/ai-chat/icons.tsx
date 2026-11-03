import type { ReactNode } from "react";

type IconName = "arrowLeft" | "arrowUp" | "arrowUpRight" | "brain" | "chat" | "check" | "chevron" | "close" | "compare" | "copy" | "dislike" | "document" | "like" | "menu" | "message" | "mic" | "micOff" | "more" | "note" | "panel" | "paperclip" | "phone" | "plan" | "plus" | "search" | "share" | "shield" | "sliders" | "spark" | "wave";

export function Icon({ name }: { name: IconName }) {
  const paths: Record<IconName, ReactNode> = {
    arrowLeft: <path d="m15 18-6-6 6-6M9 12h11" />, arrowUp: <path d="m7 11 5-5 5 5M12 6v12" />, arrowUpRight: <path d="M7 17 17 7M8 7h9v9" />,
    brain: <><path d="M9.5 4.5A3 3 0 0 0 6 7.5v.3A3.5 3.5 0 0 0 5 14a3 3 0 0 0 4.5 4.5"/><path d="M14.5 4.5A3 3 0 0 1 18 7.5v.3a3.5 3.5 0 0 1 1 6.2 3 3 0 0 1-4.5 4.5M12 4v16M8 10h4M12 15h4"/></>,
    chat: <path d="M20 15a3 3 0 0 1-3 3H8l-4 3V7a3 3 0 0 1 3-3h10a3 3 0 0 1 3 3Z" />, check: <path d="m6 12 4 4 8-9" />, chevron: <path d="m9 18 6-6-6-6" />,
    close: <path d="m6 6 12 12M18 6 6 18" />, compare: <><path d="M8 3v18M4 7l4-4 4 4M16 21V3M12 17l4 4 4-4"/></>,
    copy: <><rect x="8" y="8" width="11" height="11" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></>,
    dislike: <path d="M7 10v9M3 10h4l3-6h6a2 2 0 0 1 2 2v4h2a2 2 0 0 1 2 2l-2 5H10" />, document: <><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v5h5M9 13h6M9 17h4"/></>,
    like: <path d="M7 14V5M3 14h4l3 6h6a2 2 0 0 0 2-2v-4h2a2 2 0 0 0 2-2l-2-5H10" />, menu: <path d="M4 7h16M4 12h16M4 17h16" />,
    message: <><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z"/><path d="M8 9h8M8 13h5"/></>,
    mic: <><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11v1a7 7 0 0 0 14 0v-1M12 19v3M8 22h8"/></>,
    micOff: <><path d="m4 4 16 16M9 9v2a3 3 0 0 0 4.6 2.5M15 9V6a3 3 0 0 0-5.6-1.5M5 11v1a7 7 0 0 0 11.5 5.4M12 19v3M8 22h8"/></>,
    more: <><circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></>, note: <><path d="M5 3h14v18H5zM9 7h6M9 11h6M9 15h4"/></>,
    panel: <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/></>, paperclip: <path d="m20 12-8 8a6 6 0 0 1-8-8l9-9a4 4 0 0 1 6 6l-9 9a2 2 0 0 1-3-3l8-8" />,
    phone: <path d="M6 15c4-3 8-3 12 0l2-3c-5-4-11-4-16 0z" />, plan: <><path d="M5 4h14v16H5zM9 8h6M9 12h6M9 16h3"/></>,
    plus: <path d="M12 5v14M5 12h14" />, search: <><circle cx="11" cy="11" r="7"/><path d="m16 16 5 5"/></>, share: <><circle cx="18" cy="5" r="2"/><circle cx="6" cy="12" r="2"/><circle cx="18" cy="19" r="2"/><path d="m8 11 8-5M8 13l8 5"/></>,
    shield: <path d="M12 3 5 6v5c0 5 3 8 7 10 4-2 7-5 7-10V6z" />, sliders: <><path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/></>,
    spark: <path d="m12 2 1.8 6.2L20 10l-6.2 1.8L12 18l-1.8-6.2L4 10l6.2-1.8zM19 17l.7 2.3L22 20l-2.3.7L19 23l-.7-2.3L16 20l2.3-.7z" />,
    wave: <path d="M3 12h2l2-6 3 12 3-14 3 12 2-4h3" />,
  };
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}
