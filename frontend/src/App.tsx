import { FormEvent, useEffect, useState } from "react";
import { Check, Compass, Copy } from "lucide-react";
import {
  authorize,
  getAuthChallenge,
  getAuthStatus,
  getHealth,
  logout,
  type AuthChallenge,
  type AuthStatus,
  type Health,
} from "./api";
import { QRCodeCanvas } from "qrcode.react";
import Workspace from "./Workspace";

type LoadState = "loading" | "ready" | "error";

function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([getHealth(), getAuthStatus()])
      .then(([healthResult, authResult]) => {
        setHealth(healthResult);
        setAuth(authResult);
        setLoadState("ready");
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "无法连接本地服务");
        setLoadState("error");
      });
  }, []);

  if (loadState === "loading") return <LoadingScreen />;
  if (loadState === "error") return <ErrorScreen message={error} />;

  if (!auth?.authenticated) {
    return (
      <AuthorizationScreen
        health={health}
        error={error}
        onAuthorized={(nextAuth) => {
          setAuth(nextAuth);
          setError("");
        }}
        onError={setError}
      />
    );
  }

  return (
    <Workspace
      health={health}
      identity={auth.identity}
      onLogout={async () => {
        await logout();
        setAuth({ authenticated: false, identity: null });
      }}
    />
  );
}

function LoadingScreen() {
  return (
    <main className="shell shell--center">
      <div className="signal-loader" aria-label="正在连接本地服务" />
      <p className="eyebrow">NAUTILUS / LOCAL SERVICE</p>
      <h1>正在连接学海无涯</h1>
    </main>
  );
}

function ErrorScreen({ message }: { message: string }) {
  return (
    <main className="shell shell--center">
      <p className="eyebrow">NAUTILUS / CONNECTION</p>
      <h1>本地服务未响应</h1>
      <p className="lead">{message}</p>
      <button className="button button--dark" onClick={() => window.location.reload()}>
        重新连接
      </button>
    </main>
  );
}

function AuthorizationScreen({
  health,
  error,
  onAuthorized,
  onError,
}: {
  health: Health | null;
  error: string;
  onAuthorized: (auth: AuthStatus) => void;
  onError: (message: string) => void;
}) {
  const [accessToken, setAccessToken] = useState("");
  const [challenge, setChallenge] = useState<AuthChallenge | null>(null);
  const [copied, setCopied] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    getAuthChallenge()
      .then(setChallenge)
      .catch((reason: unknown) => {
        onError(reason instanceof Error ? reason.message : "无法获取实时授权码");
      });
  }, [onError]);

  async function copyChallenge() {
    if (!challenge?.code) return;
    try {
      await navigator.clipboard.writeText(challenge.code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      onError("浏览器拒绝访问剪贴板，请手动复制下方授权码");
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    onError("");
    try {
      onAuthorized(await authorize(accessToken));
      setAccessToken("");
    } catch (reason: unknown) {
      onError(reason instanceof Error ? reason.message : "授权失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="shell shell--auth">
      <header className="masthead">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true"><Compass size={22} strokeWidth={1.7} /></span>
          <div><p className="eyebrow">NAUTILUS</p><p className="brand-name">学海无涯</p></div>
        </div>
        <ServiceBadge health={health} />
      </header>
      <section className="auth-layout">
        <div className="auth-intro">
          <p className="eyebrow">LOCAL WORKSPACE</p>
          <h1>授权此设备，继续学习。</h1>
          <p className="lead">扫码或输入本次服务启动时生成的实时授权码。授权成功后，除非主动登出，否则无需重复授权。</p>
        </div>
        <div className="auth-stack">
          <section className="auth-code-card" aria-label="实时授权码">
            <div className="auth-code-card__heading">
              <div><p className="eyebrow">LIVE ACCESS</p><h2>扫码授权</h2></div>
              <span className="live-badge"><span className="status-dot" />实时</span>
            </div>
            <div className="auth-qr" aria-label="授权二维码">
              {challenge ? <QRCodeCanvas value={challenge.code} size={188} includeMargin bgColor="#ffffff" fgColor="#18211f" /> : <div className="auth-qr__loading" />}
            </div>
            <div className="auth-code-card__label">二维码内容与下方授权码完全一致</div>
            <div className="auth-code-value">
              <code>{challenge?.code ?? "正在生成授权码"}</code>
              <button className="icon-button" type="button" onClick={copyChallenge} disabled={!challenge} aria-label="复制授权码" title="复制授权码">
                {copied ? <Check size={17} /> : <Copy size={17} />}
              </button>
            </div>
          </section>

          <form className="auth-form" onSubmit={handleSubmit}>
            <div className="form-heading"><p className="eyebrow">DEVICE ACCESS</p><h2>输入授权码</h2></div>
            <label htmlFor="access-token">授权码</label>
            <input
              id="access-token"
              type="password"
              value={accessToken}
              onChange={(event) => setAccessToken(event.target.value)}
              placeholder="粘贴或手动输入下方授权码"
              autoComplete="off"
              required
            />
            {challenge && <button className="button button--quiet" type="button" onClick={() => setAccessToken(challenge.code)}>填入当前授权码</button>}
            {error && <p className="form-error" role="alert">{error}</p>}
            <button className="button button--accent" disabled={submitting}>{submitting ? "正在授权" : "进入工作区"}</button>
            <p className="form-hint">服务每次启动都会轮换授权码；主动登出后需要重新授权。</p>
          </form>
        </div>
      </section>
    </main>
  );
}

function ServiceBadge({ health }: { health: Health | null }) {
  const isOnline = health?.status === "ok";
  return <span className={`service-badge${isOnline ? "" : " service-badge--offline"}`}><span className="status-dot" />{isOnline ? "服务在线" : "等待服务"}</span>;
}

export default App;
