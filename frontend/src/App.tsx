import { FormEvent, useEffect, useState } from "react";
import { Compass } from "lucide-react";
import {
  authorize,
  getAuthStatus,
  getHealth,
  logout,
  type AuthStatus,
  type Health,
} from "./api";
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
  const [submitting, setSubmitting] = useState(false);

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
          <p className="lead">在运行服务的本地主机读取本次启动生成的授权码，再手动输入。授权成功后，除非主动登出，否则无需重复授权。</p>
        </div>
        <div className="auth-stack">
          <section className="auth-code-card" aria-label="获取授权码">
            <div className="auth-code-card__heading">
              <div><p className="eyebrow">LOCAL ACCESS</p><h2>在服务主机获取授权码</h2></div>
            </div>
            <p>在运行 Nautilus 的 WSL2 终端，读取启动脚本显示的授权码文件路径；默认路径为 <code>tmp/access-token</code>。授权码仅保存在服务主机，请在下方手动输入。</p>
          </section>

          <form className="auth-form" onSubmit={handleSubmit}>
            <div className="form-heading"><p className="eyebrow">DEVICE ACCESS</p><h2>输入授权码</h2></div>
            <label htmlFor="access-token">授权码</label>
            <input
              id="access-token"
              type="password"
              value={accessToken}
              onChange={(event) => setAccessToken(event.target.value)}
              placeholder="粘贴或手动输入本地主机读取的授权码"
              autoComplete="off"
              required
            />
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
