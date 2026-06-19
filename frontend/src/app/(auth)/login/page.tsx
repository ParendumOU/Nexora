"use client";
import { useState, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Zap, Loader2 } from "lucide-react";
import { authApi } from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import toast from "react-hot-toast";

// Simple inline SVG icons to avoid extra deps
function GoogleIcon() {
  return (
    <svg viewBox="0 0 24 24" className="w-4 h-4" aria-hidden="true">
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
      <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"/>
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
    </svg>
  );
}

function GitHubIcon() {
  return (
    <svg viewBox="0 0 24 24" className="w-4 h-4" aria-hidden="true" fill="currentColor">
      <path d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"/>
    </svg>
  );
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextUrl = searchParams.get("next") || "/chat";
  const { login, isAuthenticated, _hasHydrated } = useAuthStore();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  // TOTP challenge state
  const [totpToken, setTotpToken] = useState<string | null>(null);
  const [totpCode, setTotpCode] = useState("");

  // OAuth provider availability
  const [oauthProviders, setOauthProviders] = useState<{ google: boolean; github: boolean } | null>(null);

  useEffect(() => {
    if (_hasHydrated && isAuthenticated) {
      router.replace(nextUrl);
      return;
    }
    authApi.firstRun().then((res) => {
      if (res.data?.first_run) router.replace("/setup");
    }).catch(() => {});
    authApi.oauthProviders().then((res) => setOauthProviders(res.data)).catch(() => {});
  }, [_hasHydrated, isAuthenticated, router, nextUrl]);

  const handleOAuthLogin = (provider: "google" | "github") => {
    window.location.href = `/api/auth/oauth/${provider}`;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await authApi.login({ email, password });
      if (res.data.requires_totp) {
        // 2FA required — show TOTP input
        setTotpToken(res.data.totp_token);
        setLoading(false);
        return;
      }
      localStorage.setItem("access_token", res.data.access_token);
      localStorage.setItem("refresh_token", res.data.refresh_token);
      const meRes = await authApi.me();
      login(res.data, meRes.data);
      router.replace(nextUrl);
    } catch (err: any) {
      toast.error(err.response?.data?.detail || "Invalid credentials");
    } finally {
      setLoading(false);
    }
  };

  const handleTotpSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!totpToken) return;
    setLoading(true);
    try {
      const res = await authApi.totpLogin({ totp_token: totpToken, code: totpCode });
      localStorage.setItem("access_token", res.data.access_token);
      localStorage.setItem("refresh_token", res.data.refresh_token);
      const meRes = await authApi.me();
      login(res.data, meRes.data);
      router.replace(nextUrl);
    } catch (err: any) {
      toast.error(err.response?.data?.detail || "Invalid code");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm space-y-6 animate-fade-in">
        <div className="flex items-center justify-center gap-2">
          <div className="w-9 h-9 rounded-xl bg-primary flex items-center justify-center">
            <Zap className="w-5 h-5 text-primary-foreground" />
          </div>
          <span className="text-xl font-semibold tracking-tight">Nexora</span>
        </div>

        <div className="bg-card border border-border rounded-2xl p-8 space-y-6 shadow-lg">
          {totpToken ? (
            <>
              <div>
                <h2 className="text-xl font-semibold">Two-factor authentication</h2>
                <p className="text-sm text-muted-foreground mt-1">Enter the 6-digit code from your authenticator app.</p>
              </div>
              <form onSubmit={handleTotpSubmit} className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-muted-foreground">Authentication code</label>
                  <Input
                    type="text"
                    inputMode="numeric"
                    pattern="[0-9A-Z]{6,8}"
                    placeholder="000000"
                    value={totpCode}
                    onChange={(e) => setTotpCode(e.target.value)}
                    maxLength={8}
                    required
                    autoFocus
                    className="tracking-widest text-center text-lg"
                  />
                </div>
                <Button type="submit" className="w-full" disabled={loading}>
                  {loading ? <><Loader2 className="w-4 h-4 animate-spin" />Verifying…</> : "Verify"}
                </Button>
              </form>
              <button onClick={() => setTotpToken(null)} className="w-full text-center text-xs text-muted-foreground hover:text-foreground transition-colors">
                ← Back to login
              </button>
            </>
          ) : (
            <>
              <div>
                <h2 className="text-xl font-semibold">Welcome back</h2>
                <p className="text-sm text-muted-foreground mt-1">Sign in to your account</p>
              </div>
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-muted-foreground">Email</label>
                  <Input type="email" placeholder="you@example.com" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-muted-foreground">Password</label>
                  <Input type="password" placeholder="••••••••" value={password} onChange={(e) => setPassword(e.target.value)} required />
                </div>
                <Button type="submit" className="w-full" disabled={loading}>
                  {loading ? <><Loader2 className="w-4 h-4 animate-spin" />Signing in…</> : "Sign in"}
                </Button>
              </form>
              <div className="flex items-center justify-between text-sm text-muted-foreground">
                <span>Don&apos;t have an account?{" "}
                  <Link href="/register" className="text-primary hover:underline">Sign up</Link>
                </span>
                <Link href="/forgot-password" className="text-primary hover:underline text-xs">Forgot password?</Link>
              </div>

              {oauthProviders && (oauthProviders.google || oauthProviders.github) && (
                <>
                  <div className="relative">
                    <div className="absolute inset-0 flex items-center">
                      <span className="w-full border-t border-border" />
                    </div>
                    <div className="relative flex justify-center text-xs">
                      <span className="bg-card px-2 text-muted-foreground">or continue with</span>
                    </div>
                  </div>
                  <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${[oauthProviders.google, oauthProviders.github].filter(Boolean).length}, 1fr)` }}>
                    {oauthProviders.google && (
                      <Button
                        type="button"
                        variant="outline"
                        className="w-full gap-2"
                        onClick={() => handleOAuthLogin("google")}
                      >
                        <GoogleIcon />
                        Google
                      </Button>
                    )}
                    {oauthProviders.github && (
                      <Button
                        type="button"
                        variant="outline"
                        className="w-full gap-2"
                        onClick={() => handleOAuthLogin("github")}
                      >
                        <GitHubIcon />
                        GitHub
                      </Button>
                    )}
                  </div>
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return <Suspense><LoginForm /></Suspense>;
}
