"use client";
import { useState, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Loader2, ShieldAlert, Eye, EyeOff } from "lucide-react";
import { authApi, orgsApi } from "@/lib/api";
import { BrandMark } from "@/components/BrandMark";
import { useAuthStore } from "@/store/auth";
import { useOnboardingStore } from "@/store/onboarding";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import toast from "react-hot-toast";

interface InviteDetails {
  org_id: string;
  org_name: string;
  org_icon: string | null;
  org_color: string | null;
  invited_by: string;
  role: string;
  expires_at: string;
}

function RegisterForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { login, isAuthenticated, _hasHydrated } = useAuthStore();
  const startOnboarding = useOnboardingStore((s) => s.start);

  const inviteToken = searchParams.get("invite") ?? "";
  // Org invite → invite-first registration (managed account inside the inviting org).
  // Accept ?org_invite=, the legacy ?join=, or a next=/join?token=... redirect param.
  const orgInviteToken =
    searchParams.get("org_invite") ||
    searchParams.get("join") ||
    (() => {
      const n = searchParams.get("next") ?? "";
      const m = n.match(/[?&]token=([^&]+)/);
      return m ? decodeURIComponent(m[1]) : "";
    })();

  const [form, setForm] = useState({ full_name: "", email: "", password: "", org_name: "", invite_token: inviteToken, org_invite_token: orgInviteToken });
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [inviteBlocked, setInviteBlocked] = useState(false);

  const { data: orgInvite, isError: orgInviteError } = useQuery<InviteDetails>({
    queryKey: ["org-invite", orgInviteToken],
    queryFn: () => orgsApi.getInviteDetails(orgInviteToken).then((r) => r.data),
    enabled: !!orgInviteToken,
    retry: false,
  });

  useEffect(() => {
    if (_hasHydrated && isAuthenticated) router.replace("/chat");
  }, [_hasHydrated, isAuthenticated, router]);

  // Keep tokens in sync if the URL params change
  useEffect(() => {
    setForm((f) => ({ ...f, invite_token: inviteToken, org_invite_token: orgInviteToken }));
  }, [inviteToken, orgInviteToken]);

  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (form.password.length < 8) { toast.error("Password must be at least 8 characters"); return; }
    if (!/[A-Z]/.test(form.password)) { toast.error("Password must contain at least one uppercase letter"); return; }
    if (!/[a-z]/.test(form.password)) { toast.error("Password must contain at least one lowercase letter"); return; }
    if (!/\d/.test(form.password)) { toast.error("Password must contain at least one number"); return; }
    setLoading(true);
    try {
      const res = await authApi.register(form);
      localStorage.setItem("access_token", res.data.access_token);
      localStorage.setItem("refresh_token", res.data.refresh_token);
      const meRes = await authApi.me();
      login(res.data, meRes.data);
      startOnboarding();
      // Invite-first accounts are already inside their org → go straight to chat.
      router.replace(orgInviteToken ? "/chat" : "/profile?tab=profile");
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      const message = Array.isArray(detail)
        ? detail.map((d: any) => d.msg).join(", ")
        : detail || "Registration failed";

      if (err.response?.status === 403 && message.toLowerCase().includes("invitation")) {
        setInviteBlocked(true);
      } else {
        toast.error(message);
      }
    } finally {
      setLoading(false);
    }
  };

  if (inviteBlocked) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background px-4">
        <div className="w-full max-w-sm space-y-6 animate-fade-in">
          <div className="flex items-center justify-center gap-2">
            <BrandMark className="w-9 h-9" />
            <span className="text-xl font-semibold tracking-tight">Nexora</span>
          </div>
          <div className="bg-card border border-border rounded-2xl p-8 space-y-4 shadow-lg text-center">
            <ShieldAlert className="w-10 h-10 mx-auto text-muted-foreground" />
            <h2 className="text-xl font-semibold">Invitation required</h2>
            <p className="text-sm text-muted-foreground">
              This Nexora instance is invite-only. Ask an existing member to send you an invite link.
            </p>
            <Link href="/login" className="block text-sm text-primary hover:underline">
              Already have an account? Sign in
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm space-y-6 animate-fade-in">
        <div className="flex items-center justify-center gap-2">
          <BrandMark className="w-9 h-9" />
          <span className="text-xl font-semibold tracking-tight">Nexora</span>
        </div>

        <div className="bg-card border border-border rounded-2xl p-8 space-y-6 shadow-lg">
          <div>
            <h2 className="text-xl font-semibold">Create account</h2>
            <p className="text-sm text-muted-foreground mt-1">
              {orgInvite
                ? `You've been invited to join ${orgInvite.org_name}.`
                : inviteToken
                  ? "You've been invited to join Nexora."
                  : "Get started for free"}
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Full name</label>
              <Input placeholder="Alex Johnson" value={form.full_name} onChange={set("full_name")} required autoFocus />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Email</label>
              <Input type="email" placeholder="you@example.com" value={form.email} onChange={set("email")} required />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Password</label>
              <div className="relative">
                <Input type={showPassword ? "text" : "password"} placeholder="••••••••" value={form.password} onChange={set("password")} required minLength={8} className="pr-10" />
                <button type="button" onClick={() => setShowPassword((v) => !v)} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors">
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>
            {orgInviteToken ? (
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">Organization</label>
                {orgInvite ? (
                  <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/30 px-3 py-2">
                    <div
                      className="w-8 h-8 rounded-lg flex items-center justify-center text-sm font-bold text-white shrink-0"
                      style={{ backgroundColor: orgInvite.org_color || "#6366f1" }}
                    >
                      {orgInvite.org_icon || orgInvite.org_name.charAt(0).toUpperCase()}
                    </div>
                    <div className="min-w-0">
                      <div className="text-sm font-medium truncate">{orgInvite.org_name}</div>
                      <div className="text-[11px] text-muted-foreground">You&apos;ll join as {orgInvite.role}</div>
                    </div>
                  </div>
                ) : orgInviteError ? (
                  <p className="text-xs text-destructive">This invite is invalid or has expired.</p>
                ) : (
                  <div className="h-12 rounded-lg bg-muted/30 animate-pulse" />
                )}
                <p className="text-[11px] text-muted-foreground">Your account will be created inside this organization.</p>
              </div>
            ) : (
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">Organization name <span className="text-muted-foreground/50">(optional)</span></label>
                <Input placeholder="Acme Corp" value={form.org_name} onChange={set("org_name")} />
              </div>
            )}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? <><Loader2 className="w-4 h-4 animate-spin" />Creating account…</> : "Create account"}
            </Button>
            <p className="text-xs text-muted-foreground text-center">
              Email verification is only required if configured by the administrator.
            </p>
          </form>

          <p className="text-center text-sm text-muted-foreground">
            Already have an account?{" "}
            <Link href="/login" className="text-primary hover:underline">Sign in</Link>
          </p>
        </div>
      </div>
    </div>
  );
}

export default function RegisterPage() {
  return (
    <Suspense>
      <RegisterForm />
    </Suspense>
  );
}
