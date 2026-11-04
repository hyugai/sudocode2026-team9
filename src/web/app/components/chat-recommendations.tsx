"use client";

import { useEffect, useId, useRef, useSyncExternalStore } from "react";
import { chatRecommendations } from "@/utils/chat-recommendations";

const motionQuery = "(prefers-reduced-motion: reduce)";
const subscribeToMotion = (onChange: () => void) => {
  const media = matchMedia(motionQuery);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
};
const reducedMotionSnapshot = () => matchMedia(motionQuery).matches;
const serverMotionSnapshot = () => true;

export function ChatRecommendations({ disabled, onSelect }: { disabled: boolean; onSelect: (text: string) => void }) {
  const reducedMotion = useSyncExternalStore(subscribeToMotion, reducedMotionSnapshot, serverMotionSnapshot);
  const regionRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const groupRef = useRef<HTMLDivElement>(null);
  const hintId = useId();

  useEffect(() => {
    const region = regionRef.current;
    const viewport = viewportRef.current;
    const group = groupRef.current;
    if (!region || !viewport || !group || reducedMotion || disabled) return;

    let frame = 0;
    let lastTime = 0;
    let hovered = region.matches(":hover") && matchMedia("(hover: hover)").matches;
    let focused = region.contains(document.activeElement);
    let touching = false;
    let resumeTimeout = 0;
    let visible = true;
    let distance = group.getBoundingClientRect().width;
    let position = viewport.scrollLeft;
    const canAnimate = () => visible && !document.hidden && !hovered && !focused && !touching;
    const tick = (time: number) => {
      frame = 0;
      if (!canAnimate()) return;
      // Native horizontal scrolling also lets touch and keyboard users browse.
      // The second, AT-hidden copy makes the end-to-start transition seamless.
      const elapsed = lastTime ? Math.min(time - lastTime, 50) : 0;
      if (distance > 0) {
        position = (position + elapsed * 0.04) % distance;
        viewport.scrollLeft = position;
      }
      lastTime = time;
      frame = requestAnimationFrame(tick);
    };
    const sync = () => {
      if (canAnimate()) {
        if (!frame) { lastTime = 0; position = viewport.scrollLeft; frame = requestAnimationFrame(tick); }
      } else {
        cancelAnimationFrame(frame);
        frame = 0;
      }
    };
    const enter = (event: PointerEvent) => { if (event.pointerType === "mouse") { hovered = true; sync(); } };
    const leave = () => { hovered = false; sync(); };
    const focusIn = () => { focused = true; sync(); };
    const focusOut = (event: FocusEvent) => { focused = event.relatedTarget instanceof Node && region.contains(event.relatedTarget); sync(); };
    const touchStart = (event: PointerEvent) => {
      if (event.pointerType !== "touch" && event.pointerType !== "pen") return;
      clearTimeout(resumeTimeout);
      touching = true;
      sync();
    };
    const touchEnd = () => {
      if (!touching) return;
      clearTimeout(resumeTimeout);
      resumeTimeout = window.setTimeout(() => { touching = false; sync(); }, 700);
    };
    const observer = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; sync(); });
    const resizeObserver = new ResizeObserver(() => { distance = group.getBoundingClientRect().width; });
    observer.observe(region);
    resizeObserver.observe(group);
    region.addEventListener("pointerenter", enter);
    region.addEventListener("pointerleave", leave);
    region.addEventListener("focusin", focusIn);
    region.addEventListener("focusout", focusOut);
    region.addEventListener("pointerdown", touchStart);
    window.addEventListener("pointerup", touchEnd);
    window.addEventListener("pointercancel", touchEnd);
    document.addEventListener("visibilitychange", sync);
    sync();
    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(resumeTimeout);
      observer.disconnect();
      resizeObserver.disconnect();
      region.removeEventListener("pointerenter", enter);
      region.removeEventListener("pointerleave", leave);
      region.removeEventListener("focusin", focusIn);
      region.removeEventListener("focusout", focusOut);
      region.removeEventListener("pointerdown", touchStart);
      window.removeEventListener("pointerup", touchEnd);
      window.removeEventListener("pointercancel", touchEnd);
      document.removeEventListener("visibilitychange", sync);
    };
  }, [reducedMotion, disabled]);

  return <div ref={regionRef} className="chat-recommendations">
    <p id={hintId} className="sr-only">Chọn một gợi ý để điền vào ô nhập trên trang chat. Có thể kéo ngang hoặc dùng phím mũi tên để xem thêm. Gợi ý tạm dừng khi rê chuột hoặc dùng bàn phím.</p>
    <div ref={viewportRef} className="recommendation-viewport" role="group" aria-label="Gợi ý trò chuyện về sản phẩm" aria-describedby={hintId} tabIndex={0}>
      <div className="recommendation-track">
        {[false, true].map(duplicate => <div key={String(duplicate)} ref={duplicate ? undefined : groupRef} className="recommendation-group" aria-hidden={duplicate ? true : undefined}>
          {chatRecommendations.map((item, index) => <button type="button" key={item.label} className="suggestion" disabled={disabled} tabIndex={duplicate ? -1 : undefined} onMouseDown={event => { if (duplicate) event.preventDefault(); }} onFocus={() => {
            if (duplicate) groupRef.current?.querySelectorAll<HTMLButtonElement>("button")[index]?.focus();
          }} onClick={() => { if (!disabled) onSelect(item.text); }}>{item.label}</button>)}
        </div>)}
      </div>
    </div>
  </div>;
}
