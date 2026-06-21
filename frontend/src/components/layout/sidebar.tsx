"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, useMemo, useEffect, useRef } from "react";
import {
  MessageSquare, FolderKanban, Bot, Settings, ChevronLeft, ChevronDown,
  LogOut, User, Trash2, Zap, ListTodo, Sparkles, Server, Network, Wrench, Fingerprint, LayoutGrid, Plus, Search,
  GitBranch, Users, CircleDot, UserCircle, Clock, Lightbulb, X, CreditCard, ShoppingBag, BookOpen, Radio, BrainCircuit,
} from "lucide-react";
import { cn, truncate } from "@/lib/utils";
import { useSidebarStore } from "@/store/sidebar";
import { useAuthStore } from "@/store/auth";
import { useUIModeStore } from "@/store/ui-mode";
import { useOnboardingStore } from "@/store/onboarding";
import { ActiveAgentsPanel, AgentFilterPayload } from "@/components/sidebar/ActiveAgentsPanel";
import { chatsApi, projectsApi } from "@/lib/api";
import { BrandMark } from "@/components/BrandMark";
import { OrgSwitcher } from "@/components/layout/org-switcher";
import { NotificationBell } from "@/components/layout/NotificationBell";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import toast from "react-hot-toast";
import * as Tooltip from "@radix-ui/react-tooltip";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";

interface ChatStats {
  subchat_count: number;
  tool_calls: number;
  input_tokens: number;
  output_tokens: number;
}

interface Chat {
  id: string;
  title: string;
  project_id?: string | null;
  parent_chat_id?: string | null;
  agent_id?: string | null;
  updated_at?: string;
  created_at?: string;
  is_shared?: boolean;
  created_by_name?: string | null;
  stats?: ChatStats | null;
}

function fmtTok(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${Math.round(n / 1_000)}K`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

interface Project {
  id: string;
  name: string;
  description?: string;
  pm_agent_id?: string | null;
}

const _baseManageItems = [
  { href: "/tasks", label: "Tasks", icon: ListTodo },
  { href: "/issues", label: "Issues", icon: CircleDot },
  { href: "/proposals", label: "Proposals", icon: Lightbulb },
  { href: "/projects", label: "Projects", icon: FolderKanban },
  { href: "/channels", label: "Channels", icon: Radio },
  { href: "/schedules", label: "Schedules", icon: Clock },
  { href: "/agents", label: "Agents", icon: Bot },
  { href: "/personas", label: "Personas", icon: Fingerprint },
  { href: "/skills", label: "Skills", icon: Sparkles },
  { href: "/tools", label: "Tools", icon: Wrench },
  { href: "/mcps", label: "MCP Servers", icon: Server },
  { href: "/knowledge-bases", label: "Knowledge Bases", icon: BookOpen },
  { href: "/memory", label: "Memory", icon: BrainCircuit },
  { href: "/org", label: "Organization", icon: Network },
];

const billingEnabled = process.env.NEXT_PUBLIC_BILLING_ENABLED === "true";
const manageItems = billingEnabled
  ? [
      ..._baseManageItems,
      { href: "/marketplace", label: "Marketplace", icon: ShoppingBag },
      { href: "/billing", label: "Billing", icon: CreditCard },
      { href: "/audit", label: "Audit Logs", icon: LayoutGrid },
    ]
  : _baseManageItems;


function NavItem({ href, label, Icon, collapsed }: { href: string; label: string; Icon: React.ElementType; collapsed: boolean }) {
  const pathname = usePathname();
  const isActive = pathname.startsWith(href);
  return (
    <Tooltip.Provider delayDuration={0}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <Link
            href={href}
            className={cn(
              "flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors",
              isActive
                ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                : "text-sidebar-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground"
            )}
          >
            <Icon className="w-4 h-4 shrink-0" />
            {!collapsed && <span>{label}</span>}
          </Link>
        </Tooltip.Trigger>
        {collapsed && (
          <Tooltip.Content side="right" className="bg-card border border-border px-2 py-1 rounded text-xs text-foreground z-50">
            {label}
          </Tooltip.Content>
        )}
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}

function ProjectGroup({
  project,
  chats,
  childChats,
  pathname,
  router,
  deleteChat,
  collapsed,
  isExpanded,
  onToggle,
  expandedChats,
  toggleChat,
  isPersonalGroup,
}: {
  project: Project | null;
  chats: Chat[];
  childChats: Map<string, Chat[]>;
  pathname: string;
  router: (path: string) => void;
  deleteChat: { mutate: (id: string) => void };
  collapsed: boolean;
  isExpanded: boolean;
  onToggle: () => void;
  expandedChats: Record<string, boolean>;
  toggleChat: (chatId: string) => void;
  isPersonalGroup?: boolean;
}) {
  if (collapsed) return null;

  const projectName = isPersonalGroup ? "Personal" : (project?.name ?? "No Project");

  return (
    <div className="mb-3">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-1.5 px-2 py-1.5 rounded-lg hover:bg-sidebar-accent/60 transition-colors group"
      >
        <ChevronDown className={cn("w-3.5 h-3.5 text-muted-foreground transition-transform", isExpanded ? "rotate-0" : "-rotate-90")} />
        {isPersonalGroup ? (
          <MessageSquare className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
        ) : (
          <FolderKanban className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
        )}
        <span className="flex-1 min-w-0 text-xs font-medium text-sidebar-foreground text-left truncate">
          {projectName}
        </span>
      </button>

      {isExpanded && (
        <div className="ml-4 mt-1 space-y-0.5 border-l border-sidebar-border">
          {chats.map((chat) => {
            const isActive = pathname === `/chat/${chat.id}`;
            const chatChildren = childChats.get(chat.id) ?? [];
            const isChatExpanded = expandedChats[chat.id] === true;
            const hasChildren = chatChildren.length > 0;

            return (
              <div key={chat.id} className="mb-1 w-full">
                <div
                  className={cn(
                    "group relative flex items-center gap-2 px-2 py-1.5 rounded-lg cursor-pointer transition-colors",
                    isActive ? "bg-sidebar-accent" : "hover:bg-sidebar-accent/60"
                  )}
                  onClick={() => router(`/chat/${chat.id}`)}
                >
                  {hasChildren ? (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleChat(chat.id);
                      }}
                      className="p-0.5 rounded hover:bg-sidebar-accent/60 transition-colors"
                    >
                      <ChevronDown className={cn("w-3 h-3 text-muted-foreground transition-transform", isChatExpanded ? "rotate-0" : "-rotate-90")} />
                    </button>
                  ) : (
                    <div className="w-4 h-4" />
                  )}
                  {chat.is_shared
                    ? <Users className="w-3.5 h-3.5 shrink-0 text-primary/70" />
                    : <MessageSquare className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />
                  }
                  <span className="flex-1 min-w-0 text-xs truncate text-sidebar-foreground">
                    {truncate(chat.title || "New Chat", 18)}
                  </span>
                  {chat.is_shared && chat.created_by_name && (
                    <span className="text-[9px] text-primary/60 shrink-0 truncate max-w-[48px]" title={`Created by ${chat.created_by_name}`}>
                      {chat.created_by_name.split(" ")[0]}
                    </span>
                  )}
                  {!chat.is_shared && (
                    <div className="opacity-0 group-hover:opacity-100 flex items-center gap-1 transition-opacity shrink-0">
                      {chat.stats && (
                        <>
                          {chat.stats.subchat_count > 0 && (
                            <span className="flex items-center gap-0.5 text-[9px] text-muted-foreground/70" title="Subchats">
                              <GitBranch className="w-2.5 h-2.5" />
                              {chat.stats.subchat_count}
                            </span>
                          )}
                          {chat.stats.tool_calls > 0 && (
                            <span className="flex items-center gap-0.5 text-[9px] text-muted-foreground/70" title="Tool calls">
                              <Wrench className="w-2.5 h-2.5" />
                              {chat.stats.tool_calls}
                            </span>
                          )}
                          {(chat.stats.input_tokens + chat.stats.output_tokens) > 0 && (
                            <span
                              className="flex items-center gap-0.5 text-[9px] text-muted-foreground/70"
                              title={`${chat.stats.input_tokens} in / ${chat.stats.output_tokens} out`}
                            >
                              <Zap className="w-2.5 h-2.5" />
                              {fmtTok(chat.stats.input_tokens + chat.stats.output_tokens)}
                            </span>
                          )}
                        </>
                      )}
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          deleteChat.mutate(chat.id);
                        }}
                        className="p-0.5 rounded hover:text-destructive transition-colors"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                  )}
                </div>

                {isChatExpanded && hasChildren && (
                  <div className="ml-4 mt-0.5 space-y-0.5 border-l border-sidebar-border pl-[10px]">
                    {chatChildren.map((childChat) => {
                      const isChildActive = pathname === `/chat/${childChat.id}`;
                      const agentName = childChat.agent_id ? "Sub-agent" : "Unknown";
                      return (
                        <div
                          key={childChat.id}
                          className={cn(
                            "flex items-center gap-2 px-2 py-1.5 rounded-lg cursor-pointer transition-colors",
                            isChildActive ? "bg-sidebar-accent/80" : "hover:bg-sidebar-accent/40"
                          )}
                          onClick={() => router(`/chat/${childChat.id}`)}
                        >
                          <GitBranch className="w-3 h-3 shrink-0 text-muted-foreground" />
                          <span className="flex-1 min-w-0 text-xs truncate text-sidebar-foreground">
                            {truncate(childChat.title || `${agentName} Chat`, 22)}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function Sidebar() {
  const { collapsed, toggle, chatGroups, toggleChatGroup, expandedChats, toggleChat } = useSidebarStore();
  const { user, logout } = useAuthStore();
  const uiMode = useUIModeStore((s) => s.mode);
  const router = useRouter();
  const pathname = usePathname();
  const qc = useQueryClient();
  // Initialise the panel from the current route so a refresh on an Advanced
  // section (e.g. /billing) keeps the Advanced ("manage") panel open instead of
  // snapping back to Chats. uiMode is read from a persisted Zustand store, so it
  // is hydrated synchronously on the client before this initialiser runs.
  const [mode, setMode] = useState<"chats" | "manage">(() =>
    uiMode === "advanced" && manageItems.some((m) => pathname.startsWith(m.href))
      ? "manage"
      : "chats"
  );
  const { hasSeenAdvancedTour, startAdvancedTour } = useOnboardingStore();
  const [searchQuery, setSearchQuery] = useState("");
  const [agentFilter, setAgentFilter] = useState<AgentFilterPayload | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);

  // Global message search state
  interface SearchResult {
    chat_id: string;
    chat_title: string;
    message_id: string;
    excerpt: string;
    role: string;
    created_at: string;
  }
  const [globalResults, setGlobalResults] = useState<SearchResult[]>([]);
  const [globalSearching, setGlobalSearching] = useState(false);
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function handleSelectAgent(payload: AgentFilterPayload) {
    setAgentFilter(payload);
    setMode("chats");
  }

  function clearAgentFilter() {
    setAgentFilter(null);
  }

  // Reset to chats view whenever user switches back to simple mode
  useEffect(() => {
    if (uiMode === "simple") {
      setMode("chats");
      setAgentFilter(null);
    }
  }, [uiMode]);

  // Cmd/Ctrl+K → focus search input
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        if (mode !== "chats") setMode("chats");
        searchInputRef.current?.focus();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [mode]);

  // Debounced global message search
  useEffect(() => {
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    if (!searchQuery || searchQuery.trim().length < 2) {
      setGlobalResults([]);
      setGlobalSearching(false);
      return;
    }
    searchDebounceRef.current = setTimeout(async () => {
      setGlobalSearching(true);
      try {
        const r = await chatsApi.search(searchQuery.trim());
        setGlobalResults(r.data.results ?? []);
      } catch {
        setGlobalResults([]);
      } finally {
        setGlobalSearching(false);
      }
    }, 300);
    return () => {
      if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    };
  }, [searchQuery]);

  const { data: chats = [] } = useQuery<Chat[]>({
    queryKey: ["chats"],
    queryFn: () => chatsApi.list().then((r) => r.data),
    // Live updates arrive via the user WebSocket (useUserSocket); this long
    // interval is only a safety-net fallback for when the socket is down.
    refetchInterval: 60_000,
    staleTime: 2000,
  });

  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: () => projectsApi.list().then((r) => r.data),
  });

  const deleteChat = useMutation({
    mutationFn: (id: string) => chatsApi.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["chats"] });
      toast.success("Chat deleted");
      if (pathname.startsWith("/chat/")) router.push("/chat");
    },
  });

  const handleLogout = () => {
    logout();
    router.push("/login");
  };

  const filteredChats = useMemo(() => {
    let base = chats;
    // Agent filter (simple mode): restrict to chats where the selected agent is active
    if (agentFilter) {
      const chatIdSet = new Set(agentFilter.chatIds);
      base = base.filter((c) => chatIdSet.has(c.id) || (c.parent_chat_id && chatIdSet.has(c.parent_chat_id)));
    }
    if (!searchQuery.trim()) return base;
    const words = searchQuery.trim().toLowerCase().split(/\s+/);
    const matchingIds = new Set<string>();
    const parentIdsToInclude = new Set<string>();
    base.forEach((chat) => {
      const title = (chat.title || "").toLowerCase();
      if (words.every((w) => title.includes(w))) {
        matchingIds.add(chat.id);
        if (chat.parent_chat_id) parentIdsToInclude.add(chat.parent_chat_id);
      }
    });
    return base.filter((c) => matchingIds.has(c.id) || parentIdsToInclude.has(c.id));
  }, [chats, searchQuery, agentFilter]);

  // Chats agrupados por proyecto (solo chats padre - sin parent_chat_id)
  const chatsByProject = useMemo(() => {
    const grouped = new Map<string, Chat[]>();
    const childChatsMap = new Map<string, Chat[]>();
    const personalChats: Chat[] = [];

    // Separar chats padre de hijos
    filteredChats
      .filter((chat) => !chat.parent_chat_id)
      .forEach((chat) => {
        if (chat.project_id) {
          const key = `project-${chat.project_id}`;
          if (!grouped.has(key)) grouped.set(key, []);
          grouped.get(key)!.push(chat);
        } else {
          // Chats personales (sin proyecto)
          personalChats.push(chat);
        }
      });

    // Agrupar chats hijos por su padre
    filteredChats
      .filter((chat) => !!chat.parent_chat_id)
      .forEach((chat) => {
        if (!childChatsMap.has(chat.parent_chat_id!)) childChatsMap.set(chat.parent_chat_id!, []);
        childChatsMap.get(chat.parent_chat_id!)!.push(chat);
      });

    // Ordenar chats padre (por proyecto)
    grouped.forEach((chatsList) => {
      chatsList.sort((a, b) =>
        new Date(b.updated_at || b.created_at || 0).getTime() -
        new Date(a.updated_at || a.created_at || 0).getTime()
      );
    });

    // Ordenar chats personales
    personalChats.sort((a, b) =>
      new Date(b.updated_at || b.created_at || 0).getTime() -
      new Date(a.updated_at || a.created_at || 0).getTime()
    );

    // Ordenar chats hijos
    childChatsMap.forEach((chatsList) => {
      chatsList.sort((a, b) =>
        new Date(b.updated_at || b.created_at || 0).getTime() -
        new Date(a.updated_at || a.created_at || 0).getTime()
      );
    });

    return { parentChats: grouped, childChats: childChatsMap, personalChats };
  }, [filteredChats]);

  const projectMap = useMemo(() => {
    return new Map(projects.map((p) => [p.id, p]));
  }, [projects]);

  return (
    <aside
      className={cn(
        "flex flex-col h-full bg-sidebar border-r border-sidebar-border transition-all duration-200 ease-in-out shrink-0 overflow-hidden",
        collapsed ? "w-14" : "w-72"
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-4 border-b border-sidebar-border">
        {!collapsed && (
          <div className="flex items-center gap-2">
            <BrandMark className="w-7 h-7" />
            <span className="font-semibold text-sm tracking-tight">Nexora</span>
          </div>
        )}
        {collapsed && (
          <BrandMark className="w-7 h-7 mx-auto" />
        )}
        {!collapsed && (
          <Button variant="ghost" size="icon" onClick={toggle} className="h-7 w-7 shrink-0">
            <ChevronLeft className="w-4 h-4" />
          </Button>
        )}
      </div>

      {/* Collapse button (when collapsed) */}
      {collapsed && (
        <Button variant="ghost" size="icon" onClick={toggle} className="h-8 w-8 mx-auto mt-1 shrink-0">
          <ChevronLeft className="w-4 h-4 rotate-180" />
        </Button>
      )}

      {/* Org switcher */}
      <div className={cn("border-b border-sidebar-border", collapsed ? "py-1 flex flex-col items-center gap-1" : "px-2 py-2 flex items-center gap-1")}>
        <div className={collapsed ? "w-full" : "flex-1 min-w-0"}>
          <OrgSwitcher collapsed={collapsed} />
        </div>
        <NotificationBell />
      </div>

      {/* New Session + Search — chats mode only */}
      {mode === "chats" && (
        collapsed ? (
          <Tooltip.Provider delayDuration={0}>
            <Tooltip.Root>
              <Tooltip.Trigger asChild>
                <button
                  onClick={() => router.push("/chat")}
                  className="w-8 h-8 flex items-center justify-center rounded-lg mx-auto mt-2 mb-1 transition-colors text-sidebar-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground border border-sidebar-border"
                >
                  <Plus className="w-4 h-4" />
                </button>
              </Tooltip.Trigger>
              <Tooltip.Content side="right" className="bg-card border border-border px-2 py-1 rounded text-xs text-foreground z-50">
                New Session
              </Tooltip.Content>
            </Tooltip.Root>
          </Tooltip.Provider>
        ) : (
          <>
          <div className="px-2 pt-2 pb-1 flex items-center gap-1.5">
            <Tooltip.Provider delayDuration={0}>
              <Tooltip.Root>
                <Tooltip.Trigger asChild>
                  <button
                    onClick={() => router.push("/chat")}
                    className="flex items-center justify-center shrink-0 w-8 h-8 rounded-lg transition-colors text-sidebar-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground border border-sidebar-border"
                  >
                    <Plus className="w-4 h-4" />
                  </button>
                </Tooltip.Trigger>
                <Tooltip.Content side="right" className="bg-card border border-border px-2 py-1 rounded text-xs text-foreground z-50">
                  New Session
                </Tooltip.Content>
              </Tooltip.Root>
            </Tooltip.Provider>
            <div className="relative flex-1">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" />
              <input
                ref={searchInputRef}
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search chats... (⌘K)"
                className="w-full pl-7 pr-2 py-1.5 text-xs rounded-lg border border-sidebar-border bg-transparent text-sidebar-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-sidebar-accent"
                onKeyDown={(e) => {
                  if (e.key === "Escape") {
                    setSearchQuery("");
                    searchInputRef.current?.blur();
                  } else if (e.key === "Enter" && searchQuery.trim()) {
                    e.preventDefault();
                    window.location.href = `/search?q=${encodeURIComponent(searchQuery.trim())}`;
                  }
                }}
              />
            </div>
          </div>
          {/* Global message search results dropdown */}
          {searchQuery.trim().length >= 2 && (
            <div className="mx-2 mb-1 rounded-lg border border-sidebar-border bg-card overflow-hidden max-h-56 overflow-y-auto">
              {globalSearching && (
                <p className="text-[10px] text-muted-foreground px-3 py-2">Searching messages...</p>
              )}
              {!globalSearching && globalResults.length === 0 && (
                <p className="text-[10px] text-muted-foreground px-3 py-2">No message results</p>
              )}
              {!globalSearching && globalResults.length > 0 && (
                <>
                  <p className="text-[9px] font-medium text-muted-foreground px-3 pt-2 pb-1 uppercase tracking-wide">Message results</p>
                  {globalResults.map((r) => (
                    <Link
                      key={r.message_id}
                      href={`/chat/${r.chat_id}`}
                      onClick={() => setSearchQuery("")}
                      className="block px-3 py-2 hover:bg-sidebar-accent/60 transition-colors border-t border-sidebar-border/50 first:border-t-0"
                    >
                      <p className="text-[10px] font-medium text-sidebar-foreground truncate">{r.chat_title}</p>
                      <p className="text-[10px] text-muted-foreground truncate mt-0.5">{r.excerpt}</p>
                    </Link>
                  ))}
                </>
              )}
            </div>
          )}
          </>
        )
      )}

      {/* Chats section */}
      {mode === "chats" && (
        <>
          {/* Agent filter banner */}
          {agentFilter && !collapsed && (
            <div className="mx-2 mb-1 flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-cyan-950/20 border border-cyan-500/20 text-[10px]">
              <Bot className="w-3 h-3 text-cyan-400 shrink-0" />
              <span className="text-cyan-300/80 truncate flex-1 min-w-0">
                Filtered by <span className="font-semibold">{agentFilter.agentName}</span>
              </span>
              <button
                onClick={clearAgentFilter}
                title="Clear agent filter"
                className="shrink-0 text-muted-foreground hover:text-destructive transition-colors"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          )}
          {!collapsed && (
            <ScrollArea className="flex-1 px-2">
              <div className="py-2 pr-2 overflow-x-hidden">
                {chatsByProject.parentChats.size === 0 && chatsByProject.personalChats.length === 0 ? (
                  <p className="text-xs text-muted-foreground px-2 py-4 text-center">
                    {agentFilter ? `No chats found for ${agentFilter.agentName}.` : searchQuery.trim() ? "No chats match your search." : "No chats yet."}
                  </p>
                ) : (
                  <>
                    {/* Personal chats group */}
                    {chatsByProject.personalChats.length > 0 && (
                      <ProjectGroup
                        project={null}
                        chats={chatsByProject.personalChats}
                        childChats={chatsByProject.childChats}
                        pathname={pathname}
                        router={router.push.bind(router)}
                        deleteChat={deleteChat}
                        collapsed={collapsed}
                        isExpanded={chatGroups["personal"] === true}
                        onToggle={() => toggleChatGroup("personal")}
                        expandedChats={expandedChats}
                        toggleChat={toggleChat}
                        isPersonalGroup={true}
                      />
                    )}
                    
                    {/* Project-based chats */}
                    {Array.from(chatsByProject.parentChats.entries()).map(([groupKey, projectChats]) => {
                      const projectId = groupKey.replace('project-', '');
                      const project = projectMap.get(projectId) ?? null;
                      const isExpanded = chatGroups[groupKey] === true;

                      return (
                        <ProjectGroup
                          key={groupKey}
                          project={project}
                          chats={projectChats}
                          childChats={chatsByProject.childChats}
                          pathname={pathname}
                          router={router.push.bind(router)}
                          deleteChat={deleteChat}
                          collapsed={collapsed}
                          isExpanded={isExpanded}
                          onToggle={() => toggleChatGroup(groupKey)}
                          expandedChats={expandedChats}
                          toggleChat={toggleChat}
                          isPersonalGroup={false}
                        />
                      );
                    })}
                  </>
                )}
              </div>
            </ScrollArea>
          )}
        </>
      )}

      {/* Active agents panel — simple mode, below chat list */}
      {uiMode === "simple" && mode === "chats" && !collapsed && (
        <ActiveAgentsPanel onSelectAgent={handleSelectAgent} />
      )}

      {/* Manage section — advanced mode only */}
      {uiMode === "advanced" && mode === "manage" && (
        <div className="flex-1 overflow-y-auto">
          <nav className="px-2 pt-2 pb-1 space-y-0.5">
            {manageItems.map(({ href, label, icon: Icon }) => (
              <NavItem key={href} href={href} label={label} Icon={Icon} collapsed={collapsed} />
            ))}
          </nav>
        </div>
      )}

      {/* User menu */}
      <div className="p-2 border-t border-sidebar-border mt-auto">
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <button
              className={cn(
                "flex items-center gap-2 w-full px-2 py-2 rounded-lg hover:bg-sidebar-accent transition-colors text-sidebar-foreground",
                collapsed && "justify-center"
              )}
            >
              <div className="w-7 h-7 rounded-full bg-accent flex items-center justify-center shrink-0 text-sm">
                {user?.avatar_emoji ? user.avatar_emoji : <User className="w-4 h-4" />}
              </div>
              {!collapsed && (
                <div className="text-left min-w-0">
                  <div className="text-xs font-medium truncate">{user?.full_name}</div>
                  <div className="text-[10px] text-muted-foreground truncate">{user?.email}</div>
                </div>
              )}
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content
              side="top"
              align="start"
              className="z-50 min-w-[180px] rounded-lg border border-border bg-card p-1 shadow-lg"
            >
              <DropdownMenu.Item
                className="flex items-center gap-2 px-2 py-1.5 text-sm rounded-md cursor-pointer hover:bg-accent outline-none"
                onClick={() => router.push("/profile")}
              >
                <UserCircle className="w-4 h-4" />
                Profile
              </DropdownMenu.Item>
              <DropdownMenu.Item
                className="flex items-center gap-2 px-2 py-1.5 text-sm rounded-md cursor-pointer hover:bg-accent outline-none"
                onClick={() => router.push("/settings")}
              >
                <Settings className="w-4 h-4" />
                Settings
              </DropdownMenu.Item>
              {/* Billing link moved to main sidebar nav when billing is enabled */}
              {uiMode === "advanced" && (
                <>
                  <DropdownMenu.Separator className="my-1 h-px bg-border" />
                  <DropdownMenu.Item
                    className="flex items-center gap-2 px-2 py-1.5 text-sm rounded-md cursor-pointer hover:bg-accent outline-none"
                    onClick={() => {
                      const next = mode === "manage" ? "chats" : "manage";
                      setMode(next);
                      if (next === "manage" && !hasSeenAdvancedTour) startAdvancedTour();
                    }}
                  >
                    <LayoutGrid className="w-4 h-4" />
                    {mode === "manage" ? "Back to Chats" : "Advanced"}
                  </DropdownMenu.Item>
                </>
              )}
              <DropdownMenu.Separator className="my-1 h-px bg-border" />
              <DropdownMenu.Item
                className="flex items-center gap-2 px-2 py-1.5 text-sm rounded-md cursor-pointer hover:bg-accent outline-none text-destructive"
                onClick={handleLogout}
              >
                <LogOut className="w-4 h-4" />
                Sign out
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>
    </aside>
  );
}
