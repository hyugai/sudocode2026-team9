export type VoiceActivity = { type: "speech_end" } | {
  type: "playback"; volume: number; playing: boolean; generation: number;
};

/** Browser audio resources are owned by one connection and always released together. */
export class VoiceAudio {
  private context: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private capture: AudioWorkletNode | null = null;
  private playback: AudioWorkletNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private silent: GainNode | null = null;
  private closed = false;
  private failed = false;
  private onError: ((message: string) => void) | null = null;
  private resumePending: Promise<void> | null = null;

  private fail(message: string) {
    if (this.closed || this.failed) return;
    this.failed = true;
    this.onError?.(message);
  }

  private async ensureRunning() {
    const context = this.context;
    if (!context || this.closed || this.failed || context.state === "running") return;
    if (!this.resumePending) {
      let timer: ReturnType<typeof setTimeout> | undefined;
      this.resumePending = Promise.race([
        context.resume(),
        new Promise<void>((_resolve, reject) => {
          timer = setTimeout(() => reject(new Error("audio_resume_timeout")), 3000);
        }),
      ]).then(() => {
        if (context.state !== "running") throw new Error("audio_not_running");
      }).catch(() => {
        this.fail("Trình duyệt đang tạm dừng âm thanh. Hãy quay lại tab và bắt đầu trò chuyện lại.");
      }).finally(() => {
        clearTimeout(timer);
        this.resumePending = null;
      });
    }
    await this.resumePending;
  }

  async start(onAudio: (buffer: ArrayBuffer) => void, onSpeech: () => void,
    onProgress: (data: Record<string, unknown>) => void, onError: (message: string) => void,
    onActivity?: (activity: VoiceActivity) => void) {
    if (!navigator.mediaDevices?.getUserMedia || !window.AudioContext) {
      throw new Error("Trình duyệt cần HTTPS hoặc localhost để sử dụng microphone.");
    }
    this.onError = onError;
    this.context = new AudioContext({ latencyHint: "interactive" });
    await this.ensureRunning();
    if (this.closed || this.failed) return;
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    if (this.closed) { stream.getTracks().forEach((track) => track.stop()); return; }
    this.stream = stream;
    await Promise.all([
      this.context.audioWorklet.addModule("/audio/voice-capture-worklet.js"),
      this.context.audioWorklet.addModule("/audio/voice-playback-worklet.js"),
    ]);
    if (this.closed) return;
    this.source = this.context.createMediaStreamSource(stream);
    this.capture = new AudioWorkletNode(this.context, "telesale-capture", {
      numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
    });
    this.playback = new AudioWorkletNode(this.context, "telesale-playback", {
      numberOfInputs: 0, numberOfOutputs: 1, outputChannelCount: [1],
    });
    this.silent = this.context.createGain();
    this.silent.gain.value = 0;
    this.capture.port.onmessage = ({ data }) => {
      if (this.closed || this.failed) return;
      if (data.type === "pcm") onAudio(data.buffer);
      if (data.type === "speech_start") onSpeech();
      if (data.type === "speech_end") onActivity?.({ type: "speech_end" });
    };
    this.playback.port.onmessage = ({ data }) => {
      if (this.closed || this.failed) return;
      if (data.type === "progress") onProgress(data);
      if (data.type === "visualizer") onActivity?.({ ...data, type: "playback" });
      if (data.type === "overflow") {
        console.warn("Voice playback capacity exceeded", { contextState: this.context?.state,
          deviceSampleRate: this.context?.sampleRate, queuedSeconds: data.queued_seconds,
          incomingSeconds: data.incoming_seconds });
        this.fail("Phản hồi âm thanh vượt giới hạn phát liên tục. Hãy bắt đầu trò chuyện lại.");
      }
    };
    this.capture.onprocessorerror = () => this.fail("Bộ thu âm đã dừng. Hãy bắt đầu trò chuyện lại.");
    this.playback.onprocessorerror = () => this.fail("Bộ phát âm thanh đã dừng. Hãy bắt đầu trò chuyện lại.");
    this.source.connect(this.capture).connect(this.silent).connect(this.context.destination);
    this.playback.connect(this.context.destination);
    this.context.onstatechange = () => { void this.ensureRunning(); };
    // A permission dialog or audio-device change can suspend the context again.
    await this.ensureRunning();
  }

  play(buffer: ArrayBuffer, generation: number, turnId: string) {
    if (this.closed || this.failed) return;
    void this.ensureRunning();
    this.playback?.port.postMessage({ type: "audio", buffer, generation, turnId }, [buffer]);
  }

  flush(generation?: number) { this.playback?.port.postMessage({ type: "flush", generation }); }

  async close() {
    if (this.closed) return;
    this.closed = true;
    if (this.context) this.context.onstatechange = null;
    this.onError = null;
    this.stream?.getTracks().forEach((track) => track.stop());
    this.capture?.disconnect();
    this.source?.disconnect();
    this.silent?.disconnect();
    this.playback?.disconnect();
    if (this.context && this.context.state !== "closed") await this.context.close();
  }
}
