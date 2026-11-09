"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { VoiceClient, type VoiceEvent } from "@/utils/voice-api";
import { AgentAudioVisualizerAura } from "@/components/agents-ui/agent-audio-visualizer-aura";
import { idleVisualizer, updateVoiceVisualizer } from "@/utils/voice-visualizer";

type Line = { key: string; role: "user" | "agent"; text: string };
type Status = "idle" | "connecting" | "connected" | "reconnecting";

export default function VoicePanel({ apiBase, customerPhone, onActiveChange }: {
  apiBase: string; customerPhone: string; onActiveChange: (active: boolean) => void;
}) {
  const client = useRef<VoiceClient | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [visualizer, setVisualizer] = useState(idleVisualizer);
  const [muted, setMuted] = useState(false);
  const [lines, setLines] = useState<Line[]>([]);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState("");
  const [memoryNote, setMemoryNote] = useState("");
  const [available, setAvailable] = useState<boolean | null>(null);
  const [requiresCode, setRequiresCode] = useState(false);
  const [accessCode, setAccessCode] = useState("");
  const mounted = useRef(true);
  const historyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    mounted.current = true;
    const abort = new AbortController();
    fetch(apiBase + "/api/voice/capabilities", {
      signal: AbortSignal.any([abort.signal, AbortSignal.timeout(5000)]), cache: "no-store",
    })
      .then(async (response) => response.ok ? response.json() : { enabled: false })
      .then((data) => {
        if (!abort.signal.aborted) {
          setAvailable(data.enabled === true);
          setRequiresCode(data.requires_access_code === true);
        }
      })
      .catch(() => { if (!abort.signal.aborted) setAvailable(false); });
    return () => {
      mounted.current = false;
      abort.abort();
      void client.current?.close();
      client.current = null;
      onActiveChange(false);
    };
  }, [apiBase, onActiveChange]);

  useEffect(() => {
    const history = historyRef.current;
    if (history) history.scrollTop = history.scrollHeight;
  }, [lines, interim]);

  const handle = useCallback((event: VoiceEvent) => {
    if (!mounted.current) return;
    setVisualizer(previous => updateVoiceVisualizer(previous, event));
    if (event.type === "session_ready") setStatus("connected");
    if (event.type === "connection") setStatus(event.status === "reconnecting" ? "reconnecting" : "connected");
    if (event.type === "transcript_interim") setInterim(event.text || "");
    if (event.type === "interrupted") setMemoryNote("Đã dừng lời đang phát để nghe bạn.");
    if (event.type === "memory_committed") setMemoryNote("Đã lưu thông tin của lượt trao đổi.");
    if (event.type === "memory_pending") setMemoryNote("Thông tin đang chờ lưu lại; bạn có thể tiếp tục trao đổi.");
    if (event.type === "transcript_update" && event.turn_id && event.role && event.text) {
      const key = event.turn_id + ":" + event.role;
      const line: Line = { key, role: event.role, text: event.text };
      setLines((previous) => {
        const index = previous.findIndex((item) => item.key === key);
        if (index < 0) return [...previous, line].slice(-100);
        return previous.map((item) => item.key === key ? line : item);
      });
      if (event.role === "user") setInterim("");
    }
    if (event.type === "error" || event.type === "disconnected") {
      setStatus("idle");
      onActiveChange(false);
      if (event.type === "error") setError(event.detail || "Kết nối bị gián đoạn.");
      else setMemoryNote("Cuộc trò chuyện đã kết thúc. Bạn có thể bắt đầu phiên mới.");
    }
  }, [onActiveChange]);

  const start = async () => {
    if (status !== "idle") return;
    setError("");
    setMemoryNote("");
    setInterim("");
    setMuted(false);
    setStatus("connecting");
    setVisualizer({ state: "connecting", volume: 0 });
    onActiveChange(true);
    const next = new VoiceClient(apiBase, handle);
    client.current = next;
    await next.connect(customerPhone, accessCode);
  };

  const stop = async () => {
    const current = client.current;
    client.current = null;
    setStatus("idle");
    setVisualizer(idleVisualizer);
    setInterim("");
    onActiveChange(false);
    await current?.close();
    if (mounted.current) setMemoryNote("Đã kết thúc cuộc trò chuyện.");
  };

  const labels: Record<Status, string> = {
    idle: "Sẵn sàng trò chuyện", connecting: "Đang mở kết nối…",
    connected: visualizer.state === "speaking" ? "Synee đang trả lời" : visualizer.state === "thinking" ? "Synee đang suy nghĩ…" : muted ? "Microphone đang tắt" : "Đang lắng nghe",
    reconnecting: "Đang kết nối lại…",
  };
  const auraState = status === "connecting" || status === "reconnecting" ? "connecting"
    : status === "idle" ? "disconnected" : visualizer.state;

  return (
    <section aria-label="Voice" className="realtime-voice">
      <div className="voice-stage">
        <div className="voice-stage-heading"><span>SYNEE / VOICE</span></div>
        <AgentAudioVisualizerAura
          size="xl"
          color="#2f00ff"
          colorShift={2}
          state={auraState}
          themeMode="dark"
          volume={visualizer.volume}
          className="voice-aura mx-auto aspect-square size-auto w-full"
          aria-hidden="true"
        />
        <div className="voice-stage-caption">
          <p role="status" className="voice-status">{available === null ? "Đang kiểm tra kết nối voice…" : available === false ? "Voice chưa sẵn sàng" : labels[status]}</p>
          <p className="voice-state-hint">{status === "idle" ? "Bấm bắt đầu khi bạn sẵn sàng." : status !== "connected" ? "Synee sẽ sẵn sàng trong giây lát." : visualizer.state === "speaking" ? "Bạn có thể nói chen, Synee sẽ lắng nghe." : muted ? "Bật microphone khi bạn muốn nói tiếp." : "Cứ nói điều bạn đang tìm kiếm."}</p>
        </div>
      </div>
      {available === false && <p className="muted-note">
        Voice chưa sẵn sàng trên backend. Chat và tải ghi âm vẫn sử dụng được.
      </p>}
      {(lines.length > 0 || interim) && <details className="voice-transcript">
        <summary>Bản chép hội thoại <span>{lines.length} tin nhắn</span></summary>
        <div ref={historyRef} className="voice-history" role="log" aria-label="Nội dung voice" aria-live="polite" tabIndex={0}>
          {lines.map((line) => (
            <div key={line.key} className={`voice-line ${line.role}`}>
              <span>{line.role === "user" ? "Bạn" : "Synee AI"}</span>
              {line.text}
            </div>
          ))}
          {interim && <p className="muted-note">{interim}</p>}
        </div>
      </details>}
      <div className="voice-controls">
        {error && <p role="alert" className="error">{error}</p>}
        {memoryNote && <p role="status" className="muted-note">{memoryNote}</p>}
        <div className="voice-actions">
          {requiresCode && status === "idle" && <label className="voice-access-code">
            Mã truy cập
            <input type="password" autoComplete="off" value={accessCode}
              disabled={status !== "idle"} onChange={(event) => setAccessCode(event.target.value)}
              className="voice-code-input" />
          </label>}
          {status === "idle" ? (
            <button onClick={() => void start()} disabled={available !== true || (requiresCode && !accessCode)}
              className="commerce-secondary voice-start">
              <VoiceIcon name="mic" />
              Bắt đầu trò chuyện
            </button>
          ) : (
            <>
              <button onClick={() => {
                client.current?.setMuted(!muted);
                setMuted(!muted);
              }} disabled={status !== "connected"}
                className="commerce-secondary voice-mute"
                aria-label={muted ? "Bật microphone" : "Tắt microphone"}
                aria-pressed={muted}>
                <VoiceIcon name={muted ? "muted" : "mic"} />
                <span className="voice-mute-label">{muted ? "Bật microphone" : "Tắt microphone"}</span>
              </button>
              <button onClick={() => void stop()}
                className="commerce-secondary voice-stop">
                <VoiceIcon name="end" />
                Kết thúc
              </button>
            </>
          )}
        </div>
      </div>
    </section>
  );
}

function VoiceIcon({ name }: { name: "mic" | "muted" | "end" }) {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {name === "end" ? <path d="M4 14c4-4 12-4 16 0l1-3c-5-5-13-5-18 0l1 3Z M7 12v4 M17 12v4" /> : <>
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10v2a7 7 0 0 0 14 0v-2 M12 19v3 M8 22h8" />
      {name === "muted" && <path d="m3 3 18 18" />}
    </>}
  </svg>;
}
