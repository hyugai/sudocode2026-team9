export type AuthUser = { id: string; name: string; email: string };

export class AuthApiError extends Error {
  constructor(message: string, readonly status = 0) { super(message); }
}

export function createAuthClient(fetcher: typeof fetch = fetch) {
  let saving = false;
  const request = async (path: string, body?: Record<string, string>) => {
    let response: Response;
    try {
      response = await fetcher(`/api/auth/${path}`, {
        method: body ? "POST" : "GET", credentials: "same-origin", cache: "no-store",
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(15000),
      });
    } catch { throw new AuthApiError("Không kết nối được dịch vụ tài khoản. Hãy thử lại."); }
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new AuthApiError(typeof data?.detail === "string" ? data.detail : "Chưa xử lý được yêu cầu tài khoản.", response.status);
    return data;
  };
  const userFrom = (data: { user?: AuthUser } | null): AuthUser => {
    const user = data?.user;
    if (!user || typeof user.id !== "string" || typeof user.name !== "string" || typeof user.email !== "string") {
      throw new AuthApiError("Dịch vụ chưa xác nhận thông tin tài khoản hợp lệ.");
    }
    return { id: user.id, name: user.name, email: user.email };
  };
  const mutate = async <T,>(operation: () => Promise<T>): Promise<T> => {
    if (saving) throw new AuthApiError("Đang xử lý tài khoản. Vui lòng chờ.");
    saving = true;
    try { return await operation(); } finally { saving = false; }
  };
  return {
    register: (name: string, email: string, password: string) => mutate(async () => userFrom(await request("register", { name, email, password }))),
    login: (email: string, password: string) => mutate(async () => userFrom(await request("login", { email, password }))),
    async me(): Promise<AuthUser | null> {
      try { return userFrom(await request("me")); }
      catch (error) { if (error instanceof AuthApiError && error.status === 401) return null; throw error; }
    },
    logout: () => mutate(async () => {
      if ((await request("logout", {}))?.status !== "logged_out") throw new AuthApiError("Dịch vụ chưa xác nhận đăng xuất.");
    }),
  };
}
