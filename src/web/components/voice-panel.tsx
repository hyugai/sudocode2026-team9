"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { VoiceClient, type VoiceEvent } from "@/utils/voice-api";

type Line = { key: string; role: "user" | "agent"; text: string };
type Status = "idle" | "connecting" | "connected" | "reconnecting";

export default function VoicePanel({ apiBase, customerPhone, onActiveChange }: {
  apiBase: string; customerPhone: string; onActiveChange: (active: boolean) => void;
}) {
  const client = useRef<VoiceClient | null>(null);
  const [status, setStatus] = useState<Status>("idle");
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
    onActiveChange(true);
    const next = new VoiceClient(apiBase, handle);
    client.current = next;
    await next.connect(customerPhone, accessCode);
  };

  const stop = async () => {
    const current = client.current;
    client.current = null;
    setStatus("idle");
    setInterim("");
    onActiveChange(false);
    await current?.close();
    if (mounted.current) setMemoryNote("Đã kết thúc cuộc trò chuyện.");
  };

  const labels: Record<Status, string> = {
    idle: "Sẵn sàng trò chuyện", connecting: "Đang mở kết nối…",
    connected: muted ? "Microphone đang tắt" : "Đang lắng nghe",
    reconnecting: "Đang kết nối lại…",
  };

  return (
    <section aria-label="Realtime voice" className="realtime-voice">
      <div className="voice-intro">
        <p>
          Bắt đầu để nói chuyện bằng microphone. Bạn có thể nói chen để đổi ý.
          Chế độ này hỗ trợ tư vấn và tra cứu; đặt hoặc sửa đơn ở chế độ chat.
        </p>
        <p role="status" className="voice-status">{available === null ? "Đang kiểm tra kết nối voice…" : available === false ? "Voice chưa sẵn sàng" : labels[status]}</p>
        {available === false && <p className="muted-note">
          Realtime voice chưa sẵn sàng trên backend. Chat và tải ghi âm vẫn sử dụng được.
        </p>}
      </div>
      <div ref={historyRef} className="voice-history" role="log" aria-label="Nội dung voice" aria-live="polite" tabIndex={0}>
        {lines.map((line) => (
          <div key={line.key} className={`voice-line ${line.role}`}>
            <span>{line.role === "user" ? "Bạn" : "Synee AI"}</span>
            {line.text}
          </div>
        ))}
        {interim && <p className="muted-note">{interim}</p>}
      </div>
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
              Bắt đầu trò chuyện
            </button>
          ) : (
            <>
              <button onClick={() => {
                client.current?.setMuted(!muted);
                setMuted(!muted);
              }} disabled={status !== "connected"}
                className="commerce-secondary"
                aria-pressed={muted}>
                {muted ? "Bật microphone" : "Tắt microphone"}
              </button>
              <button onClick={() => void stop()}
                className="commerce-secondary voice-stop">
                Kết thúc
              </button>
            </>
          )}
          <span className="muted-note">Microphone chỉ hoạt động trong phiên đang kết nối. Đóng cửa sổ sẽ kết thúc phiên voice.</span>
        </div>
      </div>
    </section>
  );
}
