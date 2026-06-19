import { create } from "zustand";
import { persist } from "zustand/middleware";

interface SidebarState {
  collapsed: boolean;
  toggle: () => void;
  setCollapsed: (v: boolean) => void;
  chatGroups: Record<string, boolean>;
  toggleChatGroup: (projectId: string) => void;
  expandedChats: Record<string, boolean>;
  toggleChat: (chatId: string) => void;
}

export const useSidebarStore = create<SidebarState>()(
  persist(
    (set) => ({
      collapsed: false,
      toggle: () => set((s) => ({ collapsed: !s.collapsed })),
      setCollapsed: (v) => set({ collapsed: v }),
      chatGroups: {},
      toggleChatGroup: (projectId) =>
        set((s) => ({
          chatGroups: { ...s.chatGroups, [projectId]: !s.chatGroups[projectId] },
        })),
      expandedChats: {},
      toggleChat: (chatId) =>
        set((s) => ({
          expandedChats: { ...s.expandedChats, [chatId]: !s.expandedChats[chatId] },
        })),
    }),
    { name: "sidebar-state" }
  )
);
