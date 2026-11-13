"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useAuth } from "../components/auth-provider";

type AuthMode = "login" | "register";
type Field = "name" | "email" | "password" | "confirm" | "terms";
type Errors = Partial<Record<Field, string>>;

function AuthIcon({ name }: { name: "spark" | "chat" | "search" | "shield" | "eye" | "eyeOff" | "arrow" | "check" }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {name === "spark" ? <><path d="m12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4ZM20 2v4M18 4h4" /></>
      : name === "chat" ? <><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z" /><path d="M8 9h8M8 13h5" /></>
      : name === "search" ? <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></>
      : name === "shield" ? <><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z" /><path d="m8 12 3 3 5-6" /></>
      : name === "arrow" ? <path d="M4 12h16m-6-6 6 6-6 6" />
      : name === "check" ? <path d="m5 12 4 4L19 6" />
      : <><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" />{name === "eyeOff" && <path d="m3 3 18 18" />}</>}
  </svg>;
}

export function AuthScreen({ mode }: { mode: AuthMode }) {
  const register = mode === "register";
  const auth = useAuth();
  const router = useRouter();
  const [interactive, setInteractive] = useState(false);
  const [errors, setErrors] = useState<Errors>({});
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [pending, setPending] = useState(false);
  const [serverError, setServerError] = useState("");
  const [role, setRole] = useState<"user" | "salesman">("user");
  const submitLock = useRef(false);
  const resultRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Keep credentials out of native form navigation before hydration.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setInteractive(true);
  }, []);

  const clearFeedback = (field: Field) => {
    setErrors(previous => ({ ...previous, [field]: undefined }));
    setSubmitted(false);
    setServerError("");
  };
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitLock.current || auth.busy || !auth.ready) return;
    const form = event.currentTarget;
    const field = (name: Field) => form.querySelector<HTMLInputElement>(`#auth-${name}`)!;
    const next: Errors = {};
    if (register && field("name").value.trim().length < 2) next.name = "Nhập họ và tên có ít nhất 2 ký tự.";
    if (!field("email").value.trim() || !field("email").validity.valid) next.email = "Nhập địa chỉ email hợp lệ.";
    if (!field("password").value) next.password = "Nhập mật khẩu để tiếp tục.";
    else if (register && [...field("password").value].length < 8) next.password = "Dùng mật khẩu có ít nhất 8 ký tự.";
    if (register && (!field("confirm").value || field("confirm").value !== field("password").value)) next.confirm = "Mật khẩu nhập lại chưa khớp.";
    if (register && !field("terms").checked) next.terms = "Vui lòng xác nhận điều khoản để tiếp tục.";
    setErrors(next);
    setSubmitted(false);
    const firstError = Object.keys(next)[0] as Field | undefined;
    if (firstError) { field(firstError).focus(); return; }

    submitLock.current = true; setPending(true); setServerError("");
    try {
      const email = field("email").value.trim();
      const password = field("password").value;
      const user = register ? await auth.register(field("name").value.trim(), email, password, role) : await auth.login(email, password);
      form.querySelectorAll<HTMLInputElement>("[data-password]").forEach(input => { input.value = ""; });
      setShowPassword(false); setShowConfirm(false);
      if (register) {
        setSubmitted(true);
        requestAnimationFrame(() => resultRef.current?.focus({ preventScroll: true }));
      } else router.replace(user?.role === "salesman" ? "/salesman" : "/account");
    } catch (error) {
      setServerError(error instanceof Error ? error.message : "Chưa xử lý được tài khoản. Hãy thử lại.");
    } finally { submitLock.current = false; setPending(false); }
  };
  const describedBy = (field: Field, hint?: string) => [hint, errors[field] ? `auth-${field}-error` : undefined].filter(Boolean).join(" ") || undefined;

  return <div className={`auth-layout ${register ? "auth-register" : "auth-login"}`}>
    <section className="auth-story" aria-labelledby="auth-story-heading">
      <div className="auth-synee"><span><AuthIcon name="spark" /></span><div><strong>Synee AI</strong><p>Trợ lý mua sắm của bạn</p></div></div>
      <h2 id="auth-story-heading">Tìm điều bạn cần.<br /><span>Theo cách của bạn.</span></h2>
      <p>Từ câu hỏi đầu tiên đến lựa chọn phù hợp, luôn có Synee đồng hành.</p>
      <ul className="auth-benefits">{[
        { icon: "search" as const, title: "Khám phá dễ dàng", text: "Tìm sản phẩm phù hợp với nhu cầu và ngân sách." },
        { icon: "chat" as const, title: "Trò chuyện theo cách bạn thích", text: "Nhắn tin, gửi ghi âm hoặc trò chuyện bằng Voice." },
        { icon: "shield" as const, title: "Thông tin rõ ràng", text: "So sánh lựa chọn, an tâm hơn khi tìm hiểu sản phẩm." },
      ].map(item => <li key={item.title}><span><AuthIcon name={item.icon} /></span><div><h3>{item.title}</h3><p>{item.text}</p></div></li>)}</ul>
      <Link className="auth-story-link" href="/ai-chat?mode=text">Khám phá Synee AI <AuthIcon name="arrow" /></Link>
    </section>
    <section className="auth-card" aria-labelledby="auth-heading">
      <nav className="auth-mode-nav" aria-label="Đăng nhập và đăng ký"><Link href="/login" aria-current={!register ? "page" : undefined}>Đăng nhập</Link><Link href="/register" aria-current={register ? "page" : undefined}>Đăng ký</Link></nav>
      <div className="auth-card-heading"><h1 id="auth-heading">{register ? "Tạo tài khoản Synee" : "Chào mừng bạn trở lại"}</h1><p>{register ? "Một bước nhỏ để bắt đầu hành trình cùng Synee." : "Tiếp tục hành trình mua sắm cùng Synee."}</p></div>
      <p className="auth-demo-note" id="auth-demo-note">{auth.ready ? "Sử dụng email và mật khẩu của bạn. Không chia sẻ mật khẩu với người khác." : "Đang kiểm tra phiên đăng nhập…"}</p>
      <form className="auth-form" noValidate onSubmit={submit} aria-describedby="auth-demo-note" aria-busy={pending}>
        <fieldset disabled={!interactive || !auth.ready || pending || auth.busy}>
          {register && <div className="auth-field"><label htmlFor="auth-name">Họ và tên</label><input id="auth-name" autoComplete="name" placeholder="Nguyễn Minh Anh" required maxLength={100} aria-invalid={!!errors.name} aria-describedby={describedBy("name")} onChange={() => clearFeedback("name")} />{errors.name && <p className="auth-field-error" id="auth-name-error">{errors.name}</p>}</div>}
          {register && <div className="auth-field"><label htmlFor="auth-role">Vai trò demo</label><select id="auth-role" value={role} onChange={event => setRole(event.target.value as "user" | "salesman")}><option value="user">User — tư vấn sản phẩm</option><option value="salesman">Salesman — xem lịch sử hội thoại</option></select></div>}
          <div className="auth-field"><label htmlFor="auth-email">Email</label><input id="auth-email" type="email" autoComplete={register ? "email" : "username"} inputMode="email" autoCapitalize="none" spellCheck={false} placeholder="ban@example.com" required maxLength={254} aria-invalid={!!errors.email} aria-describedby={describedBy("email")} onChange={() => clearFeedback("email")} />{errors.email && <p className="auth-field-error" id="auth-email-error">{errors.email}</p>}</div>
          <div className="auth-field"><label htmlFor="auth-password">Mật khẩu</label><div className="auth-password-field"><input id="auth-password" data-password type={showPassword ? "text" : "password"} autoComplete={register ? "new-password" : "current-password"} placeholder={register ? "Tạo mật khẩu" : "Nhập mật khẩu"} required maxLength={128} aria-invalid={!!errors.password} aria-describedby={describedBy("password", register ? "auth-password-hint" : undefined)} onChange={() => clearFeedback("password")} /><button type="button" aria-label={showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"} aria-pressed={showPassword} aria-controls="auth-password" onClick={() => setShowPassword(value => !value)}><AuthIcon name={showPassword ? "eyeOff" : "eye"} /></button></div>{register && <p className="auth-field-hint" id="auth-password-hint">Ít nhất 8 ký tự. Có thể dùng một cụm từ dễ nhớ.</p>}{errors.password && <p className="auth-field-error" id="auth-password-error">{errors.password}</p>}</div>
          {register && <>
            <div className="auth-field"><label htmlFor="auth-confirm">Nhập lại mật khẩu</label><div className="auth-password-field"><input id="auth-confirm" data-password type={showConfirm ? "text" : "password"} autoComplete="new-password" placeholder="Nhập lại mật khẩu" required maxLength={128} aria-invalid={!!errors.confirm} aria-describedby={describedBy("confirm")} onChange={() => clearFeedback("confirm")} /><button type="button" aria-label={showConfirm ? "Ẩn mật khẩu nhập lại" : "Hiện mật khẩu nhập lại"} aria-pressed={showConfirm} aria-controls="auth-confirm" onClick={() => setShowConfirm(value => !value)}><AuthIcon name={showConfirm ? "eyeOff" : "eye"} /></button></div>{errors.confirm && <p className="auth-field-error" id="auth-confirm-error">{errors.confirm}</p>}</div>
            <div className="auth-consent"><div><input id="auth-terms" type="checkbox" required aria-invalid={!!errors.terms} aria-describedby={describedBy("terms")} onChange={() => clearFeedback("terms")} /><label htmlFor="auth-terms">Tôi đồng ý với <Link href="/terms" target="_blank" rel="noopener noreferrer">Điều khoản</Link> và <Link href="/privacy" target="_blank" rel="noopener noreferrer">Chính sách bảo mật</Link>.</label></div>{errors.terms && <p className="auth-field-error" id="auth-terms-error">{errors.terms}</p>}</div>
          </>}
          {Object.values(errors).some(Boolean) && <p className="auth-error-summary" role="alert">Vui lòng kiểm tra các mục được đánh dấu.</p>}
          <button type="submit" className="auth-submit">{pending ? "Đang xử lý…" : register ? "Đăng ký" : "Đăng nhập"}<AuthIcon name="arrow" /></button>
        </fieldset>
      </form>
      {pending && <p role="status">Đang xử lý tài khoản…</p>}
      {serverError && <p className="auth-field-error" role="alert">{serverError}</p>}
      {submitted && <div className="auth-result" ref={resultRef} tabIndex={-1} role="status"><span><AuthIcon name="check" /></span><div><strong>Đã tạo tài khoản</strong><p>Đăng nhập bằng email vừa đăng ký để tiếp tục.</p><Link href="/login">Đăng nhập <span aria-hidden="true">→</span></Link></div></div>}
      <div className="auth-card-bottom"><p>{register ? "Bạn đã có tài khoản?" : "Bạn chưa có tài khoản?"} <Link href={register ? "/login" : "/register"}>{register ? "Đăng nhập" : "Đăng ký ngay"}</Link></p><Link href="/" className="auth-guest-link">{auth.user ? "Về trang chủ" : "Tiếp tục với phiên khách"} <span aria-hidden="true">→</span></Link></div>
      <p className="auth-demo-note">Đăng ký vai trò Salesman để xem lịch sử Chat và Voice đã lưu.</p>
      <noscript><p className="auth-field-error">Bật JavaScript để sử dụng biểu mẫu tài khoản. Bạn vẫn có thể quay về trang chủ.</p></noscript>
    </section>
  </div>;
}
