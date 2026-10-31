/* Gemini can generate faster than playback. Grow for bursts, with a hard 60s cap. */
class TelesalePlayback extends AudioWorkletProcessor {
  constructor() {
    super();
    this.limit = 24000 * 60;
    this.ring = new Float32Array(24000 * 2);
    this.read = 0;
    this.write = 0;
    this.generation = -1;
    this.turnId = "";
    this.samples = 0;
    this.reported = 0;
    this.overflowed = false;
    this.port.onmessage = ({ data }) => {
      if (data.type === "flush") {
        this.read = this.write;
        this.overflowed = false;
        if (Number.isFinite(data.generation)) {
          this.generation = Math.max(this.generation, data.generation);
        }
        return;
      }
      if (data.type !== "audio" || data.generation < this.generation) return;
      if (data.generation !== this.generation) {
        this.read = this.write = this.samples = this.reported = 0;
        this.generation = data.generation;
        this.turnId = data.turnId;
        this.overflowed = false;
      }
      if (this.overflowed) return;
      const input = new Int16Array(data.buffer);
      const start = Math.floor(this.read);
      const remaining = this.write - start;
      const required = remaining + input.length;
      if (required > this.limit) {
        this.overflowed = true;
        this.port.postMessage({ type: "overflow", queued_seconds: (this.write - this.read) / 24000,
          incoming_seconds: input.length / 24000 });
        return;
      }
      if (required > this.ring.length) {
        const grown = new Float32Array(Math.min(this.limit, Math.max(required, this.ring.length * 2)));
        for (let index = 0; index < remaining; index++) {
          grown[index] = this.ring[(start + index) % this.ring.length];
        }
        this.ring = grown;
        this.read -= start;
        this.write = remaining;
      }
      for (const sample of input) this.ring[this.write++ % this.ring.length] = sample / 32768;
    };
  }
  process(_inputs, outputs) {
    const output = outputs[0][0];
    const step = 24000 / sampleRate;
    for (let i = 0; i < output.length; i++) {
      if (this.read >= this.write) { output[i] = 0; continue; }
      const index = Math.floor(this.read);
      const fraction = this.read - index;
      const a = this.ring[index % this.ring.length];
      const b = index + 1 < this.write ? this.ring[(index + 1) % this.ring.length] : a;
      output[i] = a + (b - a) * fraction;
      const consumed = Math.min(step, this.write - this.read);
      this.read += consumed;
      this.samples += consumed;
    }
    if (this.samples - this.reported >= 6000) {
      this.reported = this.samples;
      this.port.postMessage({ type: "progress", generation: this.generation,
        turn_id: this.turnId, samples: Math.floor(this.samples) });
    }
    return true;
  }
}
registerProcessor("telesale-playback", TelesalePlayback);
