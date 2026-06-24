"use client";
import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Eye, EyeOff, Shuffle, Copy, Check } from "lucide-react";
import { authApi } from "@/lib/api";
import { copyToClipboard } from "@/lib/utils";
import { BrandMark } from "@/components/BrandMark";
import { useAuthStore } from "@/store/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import toast from "react-hot-toast";

const CHARSET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*-_+=?";

function generateSecurePassword(length = 20): string {
  const array = new Uint32Array(length);
  crypto.getRandomValues(array);
  // Ensure at least one of each required class
  const lower  = "abcdefghijklmnopqrstuvwxyz";
  const upper  = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  const digits = "0123456789";
  const specials = "!@#$%^&*-_+=?";
  const pick = (s: string) => s[crypto.getRandomValues(new Uint32Array(1))[0] % s.length];
  const base = Array.from(array).map((n) => CHARSET[n % CHARSET.length]);
  base[0] = pick(lower);
  base[1] = pick(upper);
  base[2] = pick(digits);
  base[3] = pick(specials);
  // Fisher-Yates shuffle
  for (let i = base.length - 1; i > 0; i--) {
    const j = crypto.getRandomValues(new Uint32Array(1))[0] % (i + 1);
    [base[i], base[j]] = [base[j], base[i]];
  }
  return base.join("");
}

export default function SetupPage() {
  const router = useRouter();
  const { login } = useAuthStore();
  const [form, setForm] = useState({ full_name: "", email: "", password: "", org_name: "" });
  const [loading, setLoading] = useState(false);
  const [showPwd, setShowPwd] = useState(false);
  const [copied, setCopied] = useState(false);

  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const handleGenerate = useCallback(async () => {
    const pwd = generateSecurePassword();
    setForm((f) => ({ ...f, password: pwd }));
    setShowPwd(true);
    try {
      await copyToClipboard(pwd);
      setCopied(true);
      toast.success("Password copied to clipboard!", { icon: "🔐", duration: 3000 });
      setTimeout(() => setCopied(false), 2500);
    } catch {
      toast("Password generated — copy it manually", { icon: "⚠️" });
    }
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.full_name.trim()) { toast.error("Enter your name"); return; }
    if (!form.email.trim()) { toast.error("Enter your email"); return; }
    if (form.password.length < 8) { toast.error("Password must be at least 8 characters"); return; }
    setLoading(true);
    try {
      const res = await authApi.register({
        ...form,
        org_name: form.org_name || `${form.full_name}'s Workspace`,
      });
      localStorage.setItem("access_token", res.data.access_token);
      localStorage.setItem("refresh_token", res.data.refresh_token);
      const meRes = await authApi.me();
      login(res.data, meRes.data);
      toast.success("Welcome to Nexora!");
      router.replace("/chat");
    } catch (err: any) {
      toast.error(err.response?.data?.detail || "Setup failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm space-y-6 animate-fade-in">
        {/* Logo */}
        <div className="flex items-center justify-center gap-2">
          <BrandMark className="w-9 h-9" />
          <span className="text-xl font-semibold tracking-tight">Nexora</span>
        </div>

        {/* Card */}
        <div className="bg-card border border-border rounded-2xl p-8 space-y-6 shadow-lg">
          <div>
            <div className="inline-flex items-center gap-1.5 text-xs font-medium text-primary bg-primary/10 px-2.5 py-1 rounded-full mb-3">
              <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
              First-time setup
            </div>
            <h2 className="text-xl font-semibold">Create your admin account</h2>
            <p className="text-sm text-muted-foreground mt-1">
              This will be the owner account for this Nexora instance.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Full name</label>
              <Input
                placeholder="Your name"
                value={form.full_name}
                onChange={set("full_name")}
                required
                autoFocus
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Email</label>
              <Input
                type="email"
                placeholder="admin@example.com"
                value={form.email}
                onChange={set("email")}
                required
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Password</label>
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <Input
                    type={showPwd ? "text" : "password"}
                    placeholder="••••••••"
                    value={form.password}
                    onChange={set("password")}
                    required
                    className="pr-9 font-mono text-sm"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPwd((v) => !v)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                    tabIndex={-1}
                  >
                    {showPwd ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  onClick={handleGenerate}
                  title="Generate secure password"
                  className="shrink-0"
                >
                  {copied ? <Check className="w-4 h-4 text-green-500" /> : <Shuffle className="w-4 h-4" />}
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Click <Shuffle className="w-3 h-3 inline" /> to generate a secure password — it will be copied to your clipboard automatically.
              </p>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">
                Workspace name <span className="text-muted-foreground/50">(optional)</span>
              </label>
              <Input
                placeholder="My Team"
                value={form.org_name}
                onChange={set("org_name")}
              />
            </div>

            <Button type="submit" className="w-full" disabled={loading}>
              {loading
                ? <><Loader2 className="w-4 h-4 animate-spin" />Setting up…</>
                : "Create admin account"}
            </Button>
          </form>
        </div>

        <p className="text-center text-xs text-muted-foreground">
          Already set up?{" "}
          <a href="/login" className="text-primary hover:underline">Sign in</a>
        </p>
      </div>
    </div>
  );
}
