import { create } from "zustand";
import { persist } from "zustand/middleware";
import { usePermissionsStore, hasPermission } from "@/store/permissions";

export type UIMode = "simple" | "advanced";

interface UIModeState {
  mode: UIMode;
  setMode: (mode: UIMode) => void;
}

export const useUIModeStore = create<UIModeState>()(
  persist(
    (set) => ({
      mode: "simple",
      setMode: (mode) => set({ mode }),
    }),
    { name: "nx_ui_mode" }
  )
);

/** The user's UI mode, forced to "simple" when the org admin has revoked the
 *  `ui.advanced_mode` permission via a permission group. */
export function useEffectiveUIMode(): UIMode {
  const mode = useUIModeStore((s) => s.mode);
  const permissions = usePermissionsStore((s) => s.permissions);
  return hasPermission(permissions, "ui.advanced_mode") ? mode : "simple";
}

/** Imperative (non-hook) variant of useEffectiveUIMode for event handlers. */
export function getEffectiveUIMode(): UIMode {
  const mode = useUIModeStore.getState().mode;
  const permissions = usePermissionsStore.getState().permissions;
  return hasPermission(permissions, "ui.advanced_mode") ? mode : "simple";
}
