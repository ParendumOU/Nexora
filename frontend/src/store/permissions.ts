import { create } from "zustand";
import { permissionsApi } from "@/lib/api";

export interface PermissionLimits {
  token_budget?: number;
  token_window_hours?: number;
  max_concurrent_agents?: number;
  max_provider_accounts?: number;
}

export interface PermissionCapabilities {
  agent_ids?: string[];
  skill_keys?: string[];
  tool_keys?: string[];
  persona_ids?: string[];
  provider_ids?: string[];
  chain_ids?: string[];
  default_chain_id?: string | null;
}

export interface PermissionBudget {
  budget: number;
  used: number;
  remaining: number;
  window_hours: number;
}

type CapListDim =
  | "agent_ids"
  | "skill_keys"
  | "tool_keys"
  | "persona_ids"
  | "provider_ids"
  | "chain_ids";

interface PermissionsState {
  // null = not loaded yet → the UI fails open (the backend still enforces).
  permissions: string[] | null;
  restricted: boolean;
  orgId: string | null;
  limits: PermissionLimits;
  capabilities: PermissionCapabilities;
  budget: PermissionBudget | null;
  loading: boolean;
  fetch: () => Promise<void>;
  reset: () => void;
}

export const usePermissionsStore = create<PermissionsState>((set, get) => ({
  permissions: null,
  restricted: false,
  orgId: null,
  limits: {},
  capabilities: {},
  budget: null,
  loading: false,
  fetch: async () => {
    if (get().loading) return;
    set({ loading: true });
    try {
      const r = await permissionsApi.me();
      set({
        permissions: r.data.permissions ?? [],
        restricted: !!r.data.restricted,
        orgId: r.data.org_id ?? null,
        limits: r.data.limits ?? {},
        capabilities: r.data.capabilities ?? {},
        budget: r.data.budget ?? null,
      });
    } catch {
      set({ permissions: null, restricted: false, limits: {}, capabilities: {}, budget: null });
    } finally {
      set({ loading: false });
    }
  },
  reset: () =>
    set({
      permissions: null,
      restricted: false,
      orgId: null,
      limits: {},
      capabilities: {},
      budget: null,
    }),
}));

/** True when the key is granted (or permissions haven't loaded yet). */
export function hasPermission(permissions: string[] | null, key?: string | null): boolean {
  if (!key) return true;
  if (permissions === null) return true;
  return permissions.includes(key);
}

/**
 * Mirrors the backend capability check: an empty or missing allowlist for a
 * dimension permits everything, otherwise the value must be a member.
 */
export function capAllows(
  caps: PermissionCapabilities | null | undefined,
  dim: CapListDim,
  value: string,
): boolean {
  if (!caps) return true;
  const list = caps[dim];
  if (!Array.isArray(list) || list.length === 0) return true;
  return list.includes(value);
}
