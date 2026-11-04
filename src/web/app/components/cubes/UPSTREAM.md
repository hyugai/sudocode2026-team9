# Cubes / React Bits

Source: https://reactbits.dev/r/Cubes-TS-CSS.json

Documentation: https://reactbits.dev/animations/cubes

Retrieved 2026-11-04 from the official registry. Copyright (c) 2026 David Haz.
The full upstream license is retained in `LICENSE.md`.

Application adaptations:

- Scope pointer events to the dashboard hero and ignore chat controls when triggering ripples.
- React to reduced-motion preference changes, including disabling pointer tilt and ripple.
- Display a static CSS grid when WebGL2 is unavailable or its context is lost.
- Keep the backing buffer within 2048px per edge and release GPU resources on unmount.
- Update settings refs after render to follow the application's React lint rules.

The shader, cube geometry, spring simulation, intro, automatic motion and ripple behavior come from the upstream component. No animation dependency was added.

Upstream TypeScript SHA-256: `fbc38c6307446ed2159a7ad4847199735b1f46bbe6ad1a609ff6899b659c8d01`.
