"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/auth";
import { Sidebar } from "@/components/layout/sidebar";
import { OnboardingBanner } from "@/components/onboarding/OnboardingBanner";
import { AdvancedTourBanner } from "@/components/onboarding/AdvancedTourBanner";
import { UpdateBanner } from "@/components/layout/UpdateBanner";
import { authApi } from "@/lib/api";
import { useUserSocket } from "@/lib/useUserSocket";
import { Loader2 } from "lucide-react";

function LoadingScreen() {
  return (
    <div className="flex h-screen items-center justify-center bg-background">
      <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
    </div>
  );
}

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, _hasHydrated, user, setUser, logout } = useAuthStore();
  const router = useRouter();

  // Single user-level WebSocket → pushes notifications + chat-list changes,
  // replacing the old REST polling. Connects once authenticated.
  useUserSocket(_hasHydrated && isAuthenticated);

  useEffect(() => {
    if (!_hasHydrated) return;

    if (!isAuthenticated) {
      router.replace("/login");
      return;
    }

    if (!user) {
      authApi.me()
        .then((r) => setUser(r.data))
        .catch(() => {
          logout();
          router.replace("/login");
        });
    }
  }, [isAuthenticated, _hasHydrated, user, setUser, logout, router]);

  // Show loader while hydrating OR while redirecting unauthenticated users
  if (!_hasHydrated || !isAuthenticated) return <LoadingScreen />;

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-background">
      <UpdateBanner />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-hidden">
          {children}
        </main>
      </div>
      <OnboardingBanner />
      <AdvancedTourBanner />
    </div>
  );
}
