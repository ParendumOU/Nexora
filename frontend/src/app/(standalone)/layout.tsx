"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/auth";
import { authApi } from "@/lib/api";
import { Sidebar } from "@/components/layout/sidebar";
import { Loader2 } from "lucide-react";

export default function StandaloneLayout({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, _hasHydrated, user, setUser, logout } = useAuthStore();
  const router = useRouter();

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

  if (!_hasHydrated || !isAuthenticated) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <Sidebar />
      <main className="flex-1 overflow-hidden">
        {children}
      </main>
    </div>
  );
}
