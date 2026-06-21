"use client";
import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { Loader2, CheckCircle2, XCircle } from "lucide-react";
import api from "@/lib/api";
import { BrandMark } from "@/components/BrandMark";

function VerifyEmailForm() {
  const params = useSearchParams();
  const [status, setStatus] = useState<"loading" | "ok" | "error">("loading");

  useEffect(() => {
    const token = params.get("token");
    if (!token) {
      setStatus("error");
      return;
    }
    api
      .get(`/auth/verify-email?token=${encodeURIComponent(token)}`)
      .then(() => setStatus("ok"))
      .catch(() => setStatus("error"));
  }, [params]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm space-y-6 animate-fade-in">
        <div className="flex items-center justify-center gap-2">
          <BrandMark className="w-9 h-9" />
          <span className="text-xl font-semibold tracking-tight">Nexora</span>
        </div>

        <div className="bg-card border border-border rounded-2xl p-8 space-y-4 shadow-lg text-center">
          {status === "loading" && (
            <>
              <Loader2 className="w-10 h-10 mx-auto animate-spin text-muted-foreground" />
              <p className="text-sm text-muted-foreground">Verifying your email…</p>
            </>
          )}
          {status === "ok" && (
            <>
              <CheckCircle2 className="w-10 h-10 mx-auto text-green-500" />
              <h2 className="text-xl font-semibold">Email verified</h2>
              <p className="text-sm text-muted-foreground">Your account is ready to use.</p>
              <Link href="/login" className="inline-block text-sm text-primary hover:underline">
                Continue to login
              </Link>
            </>
          )}
          {status === "error" && (
            <>
              <XCircle className="w-10 h-10 mx-auto text-destructive" />
              <h2 className="text-xl font-semibold">Verification failed</h2>
              <p className="text-sm text-muted-foreground">
                This link is invalid or has already been used. Links expire after 24 hours.
              </p>
              <Link href="/login" className="inline-block text-sm text-primary hover:underline">
                Back to login
              </Link>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense>
      <VerifyEmailForm />
    </Suspense>
  );
}
