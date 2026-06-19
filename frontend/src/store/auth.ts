import { create } from "zustand";
import { persist } from "zustand/middleware";

interface User {
  id: string;
  email: string;
  full_name: string;
  avatar_url?: string;
  avatar_emoji?: string;
  telegram_user_id?: string;
  notes?: string;
  contact_info?: string;
  is_active?: boolean;
  is_superuser?: boolean;
}

export interface ActiveOrg {
  id: string;
  name: string;
  icon: string | null;
  color: string | null;
  role: string;
  is_personal?: boolean;
}

interface AuthState {
  user: User | null;
  accessToken: string | null;
  refreshToken: string | null;
  isAuthenticated: boolean;
  _hasHydrated: boolean;
  activeOrg: ActiveOrg | null;
  login: (tokens: { access_token: string; refresh_token: string }, user: User) => void;
  logout: () => void;
  setUser: (user: User) => void;
  setHasHydrated: (has: boolean) => void;
  setActiveOrg: (org: ActiveOrg | null) => void;
  switchOrg: (tokens: { access_token: string; refresh_token: string }, org: ActiveOrg) => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,
      _hasHydrated: false,
      activeOrg: null,

      login: (tokens, user) => {
        localStorage.setItem("access_token", tokens.access_token);
        localStorage.setItem("refresh_token", tokens.refresh_token);
        set({ user, accessToken: tokens.access_token, refreshToken: tokens.refresh_token, isAuthenticated: true });
      },

      logout: () => {
        localStorage.removeItem("access_token");
        localStorage.removeItem("refresh_token");
        set({ user: null, accessToken: null, refreshToken: null, isAuthenticated: false, activeOrg: null });
      },

      setUser: (user) => set({ user }),
      setHasHydrated: (has) => set({ _hasHydrated: has }),
      setActiveOrg: (org) => set({ activeOrg: org }),

      switchOrg: (tokens, org) => {
        localStorage.setItem("access_token", tokens.access_token);
        localStorage.setItem("refresh_token", tokens.refresh_token);
        set({ accessToken: tokens.access_token, refreshToken: tokens.refresh_token, activeOrg: org });
      },
    }),
    {
      name: "auth-storage",
      partialize: (s) => ({
        user: s.user,
        accessToken: s.accessToken,
        refreshToken: s.refreshToken,
        isAuthenticated: s.isAuthenticated,
        activeOrg: s.activeOrg,
      }),
      onRehydrateStorage: () => (state) => {
        if (state?.accessToken) localStorage.setItem("access_token", state.accessToken);
        if (state?.refreshToken) localStorage.setItem("refresh_token", state.refreshToken);
        state?.setHasHydrated(true);
      },
    }
  )
);
