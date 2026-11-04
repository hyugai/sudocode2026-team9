"use client";

import Cubes from "./cubes/Cubes";

export function HeroBackdrop() {
  return <div className="hero-backdrop" aria-hidden="true">
    <Cubes className="hero-cubes" gridSize={10} faceColor="#080f22" edgeColor="#34445f"
      maxAngle={45} radius={3} rippleColor="#56c0ee" gap={0.18} edgeStyle="solid"
      edgeWidth={1} faceOpacity={1} shading={0.6} perspective={0} speed={1}
      bounce={0.4} brush={1} rippleSpeed={1} dpr={1.5} autoAnimate rippleOnClick intro
      interactionSelector=".hero" ignorePointerSelector=".chat-panel, .hero-copy, .browse-action" />
  </div>;
}
