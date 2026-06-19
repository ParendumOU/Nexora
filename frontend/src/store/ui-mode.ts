import { create } from "zustand";
import { persist } from "zustand/middleware";

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
