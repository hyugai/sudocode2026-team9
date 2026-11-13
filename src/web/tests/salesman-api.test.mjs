import test from "node:test";
import assert from "node:assert/strict";
import { createSalesmanClient, SalesmanApiError } from "../utils/salesman-api.ts";
import { createAuthClient } from "../utils/auth-api.ts";

test("Salesman encodes search and ID, uses the account proxy, and keeps pagination", async () => {
  const calls = [];
  const client = createSalesmanClient(async (url, options) => {
    calls.push({ url, options });
    return Response.json({ items: [], total: 0, has_more: false });
  });
  await client.list("Đặng % &", "voice", 20);
  const url = new URL(calls[0].url, "https://web.example");
  assert.equal(url.searchParams.get("q"), "Đặng % &");
  assert.equal(url.searchParams.get("offset"), "20");
  assert.equal(calls[0].options.credentials, "same-origin");
  assert.equal(calls[0].options.cache, "no-store");
  await client.get("voice", "live-a/b", 50);
  assert.ok(calls[1].url.includes("live-a%2Fb?limit=50&offset=50"));
});

test("Salesman preserves access errors and never substitutes demo data", async () => {
  for (const status of [401, 403, 404, 503]) {
    const client = createSalesmanClient(async () => Response.json({ detail: "Lỗi thử nghiệm" }, { status }));
    await assert.rejects(client.list("", "all"), error => error instanceof SalesmanApiError && error.status === status);
  }
  const client = createSalesmanClient(async () => { throw new TypeError("offline"); });
  await assert.rejects(client.list("", "all"), /Kiểm tra kết nối/);
});

test("Salesman cancels a stale request instead of showing a network error", async () => {
  const abort = new AbortController();
  const client = createSalesmanClient(async (_url, options) => {
    abort.abort();
    options.signal.throwIfAborted();
  });
  await assert.rejects(client.list("", "all", 0, abort.signal), error => error.name === "AbortError");
});

test("Auth accepts only explicit roles and registration sends the selected role", async () => {
  let body;
  const user = { id: "sales", name: "Salesman", email: "sales@example.invalid", role: "salesman" };
  const client = createAuthClient(async (_url, options) => { body = JSON.parse(options.body); return Response.json({ user }); });
  assert.equal((await client.register(user.name, user.email, "Demo2026", "salesman")).role, "salesman");
  assert.equal(body.role, "salesman");
  const invalid = createAuthClient(async () => Response.json({ user: { ...user, role: "admin" } }));
  await assert.rejects(invalid.me(), /hợp lệ/);
});
