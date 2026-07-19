"use client";
import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useMutation } from "@tanstack/react-query";
import { orgsApi } from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import { Loader2, CheckCircle, XCircle } from "lucide-react";
import { useState } from "react";

interface InviteDetails {
  org_id: string;
  org_name: string;
  org_icon: string | null;
  org_color: string | null;
  invited_by: string;
  role: string;
  expires_at: string;
}

function JoinContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const router = useRouter();
  const { isAuthenticated } = useAuthStore();
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data: invite, isLoading, isError } = useQuery<InviteDetails>({
    queryKey: ["invite", token],
    queryFn: () => orgsApi.getInviteDetails(token).then((r) => r.data),
    enabled: !!token,
    retry: false,
  });

  const acceptMutation = useMutation({
    mutationFn: () => orgsApi.acceptInvite(token).then((r) => r.data),
    onSuccess: () => {
      setAccepted(true);
      setTimeout(() => router.push("/chat"), 2000);
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Failed to join";
      setError(msg);
    },
  });

  if (!token) {
    return (
      <div className="text-center space-y-2">
        <XCircle className="w-10 h-10 text-destructive mx-auto" />
        <p className="text-sm text-muted-foreground">Invalid invite link.</p>
      </div>
    );
  }

  if (isLoading) {
    return <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />;
  }

  if (isError || !invite) {
    return (
      <div className="text-center space-y-3 max-w-xs">
        <XCircle className="w-10 h-10 text-destructive mx-auto" />
        <p className="text-sm font-medium">Invite not found or expired</p>
        <p className="text-xs text-muted-foreground">This invite link may have already been used or has expired.</p>
        <button
          onClick={() => router.push("/login")}
          className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
        >
          Go to login
        </button>
      </div>
    );
  }

  if (accepted) {
    return (
      <div className="text-center space-y-3">
        <CheckCircle className="w-10 h-10 text-green-400 mx-auto" />
        <p className="text-sm font-medium">You joined <strong>{invite.org_name}</strong>!</p>
        <p className="text-xs text-muted-foreground">Redirecting…</p>
      </div>
    );
  }

  const bg = invite.org_color || "#6366f1";

  return (
    <div className="w-full max-w-sm rounded-2xl border border-border bg-card p-6 space-y-5 shadow-xl">
      <div className="flex flex-col items-center gap-3 text-center">
        <div
          className="w-14 h-14 rounded-2xl flex items-center justify-center text-2xl font-bold text-white"
          style={{ backgroundColor: bg }}
        >
          {invite.org_icon || invite.org_name.charAt(0).toUpperCase()}
        </div>
        <div>
          <p className="text-xs text-muted-foreground">{invite.invited_by} invited you to join</p>
          <h2 className="text-lg font-semibold mt-0.5">{invite.org_name}</h2>
          <p className="text-xs text-muted-foreground mt-0.5">You&apos;ll join as <strong>{invite.role}</strong></p>
        </div>
      </div>

      {error && (
        <p className="text-xs text-destructive text-center bg-destructive/10 rounded-lg px-3 py-2">{error}</p>
      )}

      {isAuthenticated ? (
        <button
          onClick={() => acceptMutation.mutate()}
          disabled={acceptMutation.isPending}
          className="w-full py-2.5 rounded-xl bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
        >
          {acceptMutation.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
          Accept invitation
        </button>
      ) : (
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground text-center">You need an account to accept this invite.</p>
          <button
            onClick={() => router.push(`/login?next=/join?token=${token}`)}
            className="w-full py-2.5 rounded-xl bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
          >
            Log in to accept
          </button>
          <button
            onClick={() => router.push(`/register?org_invite=${token}`)}
            className="w-full py-2.5 rounded-xl border border-border text-sm font-medium hover:bg-accent transition-colors"
          >
            Create account
          </button>
        </div>
      )}

      <p className="text-[10px] text-muted-foreground text-center">
        Expires {new Date(invite.expires_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
      </p>
    </div>
  );
}

export default function JoinPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Suspense fallback={<Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />}>
        <JoinContent />
      </Suspense>
    </div>
  );
}
