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
  const endRef = useRef<HTMLDivElement>(null);

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

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [lines, interim]);

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
    <section aria-label="Realtime voice" className="flex flex-1 min-h-0 flex-col">
      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        <div className="max-w-3xl mx-auto">
          <div className="rounded-2xl border border-black/10 bg-white p-6 mb-6">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-xl font-semibold text-black">Trò chuyện trực tiếp</h2>
              <span className="text-xs rounded-full bg-black/5 px-3 py-1 text-black/60">Gemini 3.8 Live</span>
            </div>
            <p className="mt-3 text-sm text-black/60 leading-relaxed">
              Bắt đầu để nói chuyện bằng microphone. Bạn có thể nói chen để đổi ý.
              Chế độ này hỗ trợ tư vấn và tra cứu; đặt hoặc sửa đơn ở chế độ chat.
            </p>
            <p role="status" className="mt-4 text-sm font-medium text-black/80">{labels[status]}</p>
            {available === false && <p className="mt-3 text-sm text-amber-800">
              Realtime voice chưa sẵn sàng trên backend. Chat và tải ghi âm vẫn sử dụng được.
            </p>}
          </div>
          <div className="space-y-4" aria-live="polite">
            {lines.map((line) => (
              <div key={line.key} className={"rounded-2xl px-5 py-3 whitespace-pre-wrap text-sm leading-relaxed " +
                (line.role === "user" ? "ml-10 bg-black text-white" : "mr-10 bg-white border border-black/10 text-black/80")}>
                <span className="block text-xs opacity-60 mb-1">{line.role === "user" ? "Bạn" : "Tư vấn viên"}</span>
                {line.text}
              </div>
            ))}
            {interim && <p className="text-sm text-black/45 italic px-3">{interim}</p>}
          </div>
          <div ref={endRef} />
        </div>
      </div>
      <div className="border-t border-black/10 p-4 sm:p-6">
        <div className="max-w-3xl mx-auto">
          {error && <p role="alert" className="text-sm text-red-700 mb-3">{error}</p>}
          {memoryNote && <p className="text-xs text-black/55 mb-3">{memoryNote}</p>}
          <div className="flex flex-wrap items-center gap-3">
            {requiresCode && <label className="text-sm text-black/70">
              Mã truy cập
              <input type="password" autoComplete="off" value={accessCode}
                disabled={status !== "idle"} onChange={(event) => setAccessCode(event.target.value)}
                className="ml-2 rounded-full border border-black/20 bg-white px-3 py-2 text-black" />
            </label>}
            {status === "idle" ? (
              <button onClick={() => void start()} disabled={available !== true || (requiresCode && !accessCode)}
                className="rounded-full bg-black text-white px-6 py-3 text-sm font-semibold disabled:opacity-40">
                Bắt đầu trò chuyện
              </button>
            ) : (
              <>
                <button onClick={() => {
                  client.current?.setMuted(!muted);
                  setMuted(!muted);
                }} disabled={status !== "connected"}
                  className="rounded-full border border-black/20 bg-white px-5 py-3 text-sm disabled:opacity-40"
                  aria-pressed={muted}>
                  {muted ? "Bật microphone" : "Tắt microphone"}
                </button>
                <button onClick={() => void stop()}
                  className="rounded-full bg-red-700 text-white px-5 py-3 text-sm font-semibold">
                  Kết thúc
                </button>
              </>
            )}
            <span className="text-xs text-black/50">Microphone chỉ hoạt động trong phiên đang kết nối.</span>
          </div>
        </div>
      </div>
    </section>
  );
}
