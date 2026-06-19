"use client";
import { useState } from "react";
import Link from "next/link";
import { Zap, Loader2, ArrowLeft } from "lucide-react";
import { authApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import toast from "react-hot-toast";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await authApi.forgotPassword(email);
      setSent(true);
    } catch {
      toast.error("Something went wrong. Try again.");
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
          {sent ? (
            <div className="text-center space-y-3">
              <p className="text-xl font-semibold">Check your inbox</p>
              <p className="text-sm text-muted-foreground">
                If that email is registered you&apos;ll receive a reset link within a minute.
              </p>
              <Link href="/login" className="inline-flex items-center gap-1 text-sm text-primary hover:underline mt-2">
                <ArrowLeft className="w-3.5 h-3.5" /> Back to login
              </Link>
            </div>
          ) : (
            <>
              <div>
                <h2 className="text-xl font-semibold">Forgot your password?</h2>
                <p className="text-sm text-muted-foreground mt-1">Enter your email and we&apos;ll send a reset link.</p>
              </div>
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-muted-foreground">Email</label>
                  <Input type="email" placeholder="you@example.com" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
                </div>
                <Button type="submit" className="w-full" disabled={loading}>
                  {loading ? <><Loader2 className="w-4 h-4 animate-spin" />Sending…</> : "Send reset link"}
                </Button>
              </form>
              <p className="text-center text-sm text-muted-foreground">
                <Link href="/login" className="inline-flex items-center gap-1 text-primary hover:underline">
                  <ArrowLeft className="w-3.5 h-3.5" /> Back to login
                </Link>
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
