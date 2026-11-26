LiveKit Agents UI audio visualizers
==================================

Source: https://github.com/livekit/components-js/tree/main/packages/shadcn
Retrieved 2026-10-31. The Wave component and its animation hook are distributed
under the repository's Apache-2.0 license, included in LICENSE.livekit.
The Aura component and animation hook were retrieved from the same source on
2026-11-10 and are covered by the same license.

react-shader-toy.tsx carries its own MIT license notice, retained in the file:
Copyright (c) 2018 Morgan Villedieu
Copyright (c) 2023 Rysana, Inc.
Copyright (c) 2026 LiveKit, Inc.

Local changes adapt animation cleanup, a single 30 FPS rendering loop, reduced motion, rendering fallback and
the existing Gemini PCM/WebSocket client's state and playback volume. No LiveKit
room or token server is required for the volume-controlled Wave and Aura components.
