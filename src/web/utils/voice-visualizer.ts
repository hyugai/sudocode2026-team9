import type { VoiceEvent } from "./voice-api.ts";

export type VoiceVisualizer = {
  state: "disconnected" | "connecting" | "listening" | "thinking" | "speaking";
  volume: number;
};

export const idleVisualizer: VoiceVisualizer = { state: "disconnected", volume: 0 };

/** Playback can outlast the provider response; only rendered audio drives speaking. */
export function updateVoiceVisualizer(previous: VoiceVisualizer, event: VoiceEvent): VoiceVisualizer {
  if (event.type === "error" || event.type === "disconnected") return idleVisualizer;
  if (event.type === "connection" && event.status === "reconnecting") return { state: "connecting", volume: 0 };
  if (event.type === "session_ready" || (event.type === "connection" && event.status === "connected") || event.type === "interrupted") {
    return { state: "listening", volume: 0 };
  }
  if (event.type === "playback") return {
    state: event.playing ? "speaking" : "listening",
    volume: event.playing && Number.isFinite(event.volume) ? Math.max(0, Math.min(1, event.volume!)) : 0,
  };
  if (event.type === "agent_state" && event.state) {
    if (event.state === "thinking" && previous.state === "speaking") return previous;
    return { state: event.state, volume: 0 };
  }
  if (event.type === "transcript_interim" && previous.state !== "speaking") return { state: "listening", volume: 0 };
  if (event.type === "transcript_update" && event.role === "user" && event.finished && previous.state !== "speaking") {
    return { state: "thinking", volume: 0 };
  }
  return previous;
}
