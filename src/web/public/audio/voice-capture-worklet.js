/* Average-resample the device rate to mono PCM16/16 kHz; send 20 ms frames. */
class TelesaleCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.frame = new Int16Array(320);
    this.index = 0;
    this.weight = 0;
    this.sum = 0;
    this.ratio = sampleRate / 16000;
    this.speechSamples = 0;
    this.quietSamples = 0;
    this.speaking = false;
  }
  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel) return true;
    let energy = 0;
    for (const value of channel) {
      energy += value * value;
      let remaining = 1;
      while (remaining > 0) {
        const amount = Math.min(remaining, this.ratio - this.weight);
        this.sum += value * amount;
        this.weight += amount;
        remaining -= amount;
        if (this.weight >= this.ratio - 1e-8) {
          const sample = Math.max(-1, Math.min(1, this.sum / this.ratio));
          this.frame[this.index++] = Math.round(sample * (sample < 0 ? 32768 : 32767));
          this.sum = 0;
          this.weight = 0;
          if (this.index === this.frame.length) {
            const buffer = this.frame.buffer;
            this.port.postMessage({ type: "pcm", buffer }, [buffer]);
            this.frame = new Int16Array(320);
            this.index = 0;
          }
        }
      }
    }
    if (Math.sqrt(energy / channel.length) > .035) {
      this.speechSamples += channel.length;
      this.quietSamples = 0;
      if (!this.speaking && this.speechSamples > sampleRate * .08) {
        this.speaking = true;
        this.port.postMessage({ type: "speech_start" });
      }
    } else {
      this.quietSamples += channel.length;
      this.speechSamples = 0;
      if (this.speaking && this.quietSamples > sampleRate * .4) {
        this.speaking = false;
        this.port.postMessage({ type: "speech_end" });
      }
    }
    return true;
  }
}
registerProcessor("telesale-capture", TelesaleCapture);
