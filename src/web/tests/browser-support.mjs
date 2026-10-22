import { writeFile } from 'node:fs/promises';
export async function connect() {
  const endpoint = process.env.CDP_URL || 'http://127.0.0.1:9222';
  // Each suite gets its own page: injected mocks must not leak into another run.
  const page = await (await fetch(`${endpoint}/json/new?about:blank`, { method: 'PUT' })).json();
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  let id = 0;
  const pending = new Map();
  const events = new Map();
  ws.onmessage = ({ data }) => {
    const m = JSON.parse(data);
    if (m.id) { const p = pending.get(m.id); if (p) { pending.delete(m.id); if (m.error) p.reject(new Error(JSON.stringify(m.error))); else p.resolve(m.result); } }
    else for (const cb of events.get(m.method) || []) cb(m.params);
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => { pending.set(++id, { resolve, reject }); ws.send(JSON.stringify({ id, method, params })); });
  const evaluate = async expression => { const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }); if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails)); return r.result.value; };
  const wait = async expression => { for (let i = 0; i < 120; i++) { if (await evaluate(`Boolean(${expression})`)) return; await new Promise(r => setTimeout(r, 250)); } throw new Error('Timed out: ' + expression); };
  const screenshot = async path => { const r = await send('Page.captureScreenshot', { format: 'png' }); await writeFile(path, Buffer.from(r.data, 'base64')); };
  return { send, evaluate, wait, screenshot, on(method, cb) { events.set(method, [...(events.get(method) || []), cb]); }, close() { ws.close(); return fetch(`${endpoint}/json/close/${encodeURIComponent(page.id)}`).catch(() => {}); } };
}
