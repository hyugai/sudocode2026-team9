"use client";

import { useEffect, useRef } from "react";

export function HeroBackdrop() {
  const backdropRef = useRef<HTMLDivElement>(null);
  const glowRef = useRef<HTMLDivElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const backdrop = backdropRef.current;
    const hero = backdrop?.parentElement;
    const glow = glowRef.current;
    const grid = gridRef.current;
    if (!hero || !backdrop || !glow || !grid) return;

    const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
    const finePointer = matchMedia("(hover: hover) and (pointer: fine)");
    let frame = 0;
    let active = false;
    let x = 0;
    let y = 0;
    let targetX = 0;
    let targetY = 0;

    const reset = () => {
      active = false;
      backdrop.dataset.pointerActive = "false";
      cancelAnimationFrame(frame);
      frame = 0;
      grid.style.removeProperty("transform");
    };
    const paint = () => {
      x += (targetX - x) * .16;
      y += (targetY - y) * .16;
      glow.style.transform = `translate3d(${x}px, ${y}px, 0) translate(-50%, -50%)`;
      grid.style.transform = `translate3d(${(x - hero.clientWidth / 2) * -.015}px, ${(y - hero.clientHeight / 2) * -.015}px, 0) scale(1.04)`;
      frame = active && Math.abs(targetX - x) + Math.abs(targetY - y) > .2 ? requestAnimationFrame(paint) : 0;
    };
    const move = (event: PointerEvent) => {
      if (reducedMotion.matches || !finePointer.matches || event.pointerType === "touch") return;
      const rect = hero.getBoundingClientRect();
      targetX = event.clientX - rect.left;
      targetY = event.clientY - rect.top;
      if (!active) {
        x = targetX;
        y = targetY;
        active = true;
        backdrop.dataset.pointerActive = "true";
      }
      if (!frame) frame = requestAnimationFrame(paint);
    };

    hero.addEventListener("pointermove", move, { passive: true });
    hero.addEventListener("pointerleave", reset);
    reducedMotion.addEventListener("change", reset);
    finePointer.addEventListener("change", reset);
    window.addEventListener("blur", reset);
    return () => {
      reset();
      hero.removeEventListener("pointermove", move);
      hero.removeEventListener("pointerleave", reset);
      reducedMotion.removeEventListener("change", reset);
      finePointer.removeEventListener("change", reset);
      window.removeEventListener("blur", reset);
    };
  }, []);

  return <div ref={backdropRef} className="hero-backdrop" aria-hidden="true">
    <div ref={gridRef} className="hero-grid" />
    <div ref={glowRef} className="hero-cursor-glow" />
  </div>;
}
