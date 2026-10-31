import { VoiceAudio } from "./voice-audio.ts";

export interface VoiceEvent {
  type: string;
  text?: string;
  role?: "user" | "agent";
  turn_id?: string;
  generation?: number;
  detail?: string;
  status?: string;
}

export interface VoiceSession {
  session_id: string;
  conversation_id: string;
  owner_token: string;
  connect_ticket: string;
}

export function voiceSocketUrl(apiBase: string, sessionId: string) {
  const url = new URL(apiBase);
  if (url.protocol !== "http:" && url.protocol !== "https:") throw new Error("Địa chỉ backend không hợp lệ.");
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = url.pathname.replace(/\/$/, "") + "/api/voice/sessions/" + encodeURIComponent(sessionId) + "/stream";
  url.search = "";
  url.hash = "";
  return url.toString();
}

export class VoiceClient {
  private socket: WebSocket | null = null;
  private audio = new VoiceAudio();
  private session: VoiceSession | null = null;
  private disposed = false;
  private ready = false;
  private muted = false;
  private generation = -1;
  private nextAudio: { generation: number; turnId: string } | null = null;
  private abort = new AbortController();
  private apiBase: string;
  private onEvent: (event: VoiceEvent) => void;

  constructor(apiBase: string, onEvent: (event: VoiceEvent) => void) {
    this.apiBase = apiBase;
    this.onEvent = onEvent;
  }

  private control(value: Record<string, unknown>) {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify(value));
  }

  async connect(phone: string, accessCode = "") {
    try {
      await this.audio.start((buffer) => {
        if (this.ready && !this.muted && this.socket?.readyState === WebSocket.OPEN) {
          if (this.socket.bufferedAmount > 16000 * 2) {
            this.onEvent({ type: "error", detail: "Mạng đang chậm; hãy kết nối lại." });
            void this.close();
            return;
          }
          this.socket.send(buffer);
        }
      }, () => {
        if (this.ready && !this.muted) {
          this.audio.flush();
          this.control({ type: "input_started" });
        }
      }, (data) => this.control({ ...data, type: "playback_progress" }),
      (detail) => { this.onEvent({ type: "error", detail }); void this.close(); });
      if (this.disposed) return;
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (accessCode) headers["X-API-Key"] = accessCode;
      const response = await fetch(this.apiBase + "/api/voice/sessions", {
        method: "POST", headers,
        body: JSON.stringify({ customer_phone: phone || null }), signal: this.abort.signal,
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "Không mở được phiên voice.");
      this.session = payload;
      if (this.disposed) { await this.close(); return; }
      const socket = new WebSocket(voiceSocketUrl(this.apiBase, payload.session_id));
      socket.binaryType = "arraybuffer";
      this.socket = socket;
      socket.onopen = () => this.control({ type: "authenticate",
        owner_token: payload.owner_token, connect_ticket: payload.connect_ticket });
      socket.onmessage = ({ data }) => {
        if (this.disposed) return;
        if (data instanceof ArrayBuffer) {
          const meta = this.nextAudio;
          this.nextAudio = null;
          if (meta && meta.generation >= this.generation) {
            this.generation = meta.generation;
            this.audio.play(data, meta.generation, meta.turnId);
          }
          return;
        }
        try {
          const event = JSON.parse(data);
          if (event.type === "audio") {
            this.nextAudio = { generation: event.generation, turnId: event.turn_id };
            return;
          }
          if (event.type === "interrupted") {
            this.generation = Math.max(this.generation, event.generation ?? -1);
            this.nextAudio = null;
            this.audio.flush(this.generation);
          }
          if (event.type === "session_ready") this.ready = true;
          if (event.type === "connection") this.ready = event.status === "connected";
          this.onEvent(event);
          if (event.type === "error") void this.close();
        } catch {
          this.onEvent({ type: "error", detail: "Phản hồi voice không hợp lệ." });
          void this.close();
        }
      };
      socket.onerror = () => {
        if (!this.disposed) this.onEvent({ type: "error", detail: "Không kết nối được realtime voice." });
        void this.close();
      };
      socket.onclose = () => {
        if (!this.disposed) this.onEvent({ type: "disconnected" });
        void this.close();
      };
    } catch (error) {
      if (!this.disposed) {
        this.onEvent({ type: "error", detail: error instanceof Error ? error.message : "Không mở được microphone." });
      }
      await this.close();
    }
  }

  setMuted(value: boolean) {
    this.muted = value;
    if (value) this.control({ type: "input_audio_end" });
  }

  async close() {
    this.disposed = true;
    this.ready = false;
    this.abort.abort();
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "close" }));
      socket.close();
    }
    await this.audio.close();
    const session = this.session;
    this.session = null;
    if (session) {
      await fetch(this.apiBase + "/api/voice/sessions/" + session.session_id, {
        method: "DELETE", headers: { Authorization: "Bearer " + session.owner_token },
        keepalive: true,
      }).catch(() => {});
    }
  }
}
