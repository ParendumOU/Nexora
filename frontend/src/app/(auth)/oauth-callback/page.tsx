"use client";
import { useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2, Zap } from "lucide-react";
import { authApi } from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import toast from "react-hot-toast";

function OAuthCallbackInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { login } = useAuthStore();

  useEffect(() => {
    const token = searchParams.get("token");
    const refresh = searchParams.get("refresh");
    const error = searchParams.get("error");

    if (error) {
      const messages: Record<string, string> = {
        oauth_denied: "Sign-in was cancelled.",
        no_code: "No authorization code received.",
        token_exchange_failed: "Failed to exchange OAuth code.",
        provider_error: "Provider returned an error.",
        no_email: "No email address returned by provider.",
      };
      toast.error(messages[error] ?? "OAuth sign-in failed.");
      router.replace("/login");
      return;
    }

    if (!token || !refresh) {
      toast.error("OAuth sign-in failed — missing tokens.");
      router.replace("/login");
      return;
    }

    localStorage.setItem("access_token", token);
    localStorage.setItem("refresh_token", refresh);

    authApi.me()
      .then((res) => {
        login({ access_token: token, refresh_token: refresh }, res.data);
        router.replace("/chat");
      })
      .catch(() => {
        toast.error("Failed to load user profile after sign-in.");
        router.replace("/login");
      });
  }, [searchParams, router, login]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="flex flex-col items-center gap-4 animate-fade-in">
        <div className="w-9 h-9 rounded-xl bg-primary flex items-center justify-center">
          <Zap className="w-5 h-5 text-primary-foreground" />
        </div>
        <div className="flex items-center gap-2 text-muted-foreground text-sm">
          <Loader2 className="w-4 h-4 animate-spin" />
          Completing sign-in…
        </div>
      </div>
    </div>
  );
}

export default function OAuthCallbackPage() {
  return (
    <Suspense>
      <OAuthCallbackInner />
    </Suspense>
  );
}
