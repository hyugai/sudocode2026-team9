"use client";

import Cubes from "./cubes/Cubes";
import { useSyncExternalStore } from "react";

const compactViewport = "(max-width: 760px)";
const subscribeToViewport = (onChange: () => void) => {
  const media = matchMedia(compactViewport);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
};
const isCompactViewport = () => matchMedia(compactViewport).matches;
const serverViewport = () => false;

export function HeroBackdrop() {
  const compact = useSyncExternalStore(subscribeToViewport, isCompactViewport, serverViewport);
  return <div className="hero-backdrop" aria-hidden="true">
    <Cubes className="hero-cubes" gridSize={compact ? 12 : 18} faceColor="#0c172b" edgeColor="#4b6282"
      maxAngle={45} radius={3} rippleColor="#56c0ee" gap={0.18} edgeStyle="solid"
      edgeWidth={1} faceOpacity={1} shading={0.6} perspective={0} speed={1}
      bounce={0.4} brush={1} rippleSpeed={1} dpr={1.5} autoAnimate rippleOnClick intro
      interactionSelector=".hero" ignorePointerSelector=".chat-panel, .hero-copy, .browse-action" />
  </div>;
}
