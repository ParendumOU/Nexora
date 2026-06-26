"use client";
import { use, useEffect, useRef, useState, useCallback, Fragment } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { chatsApi, tasksApi, projectsApi, plansApi, chatFilesApi, approvalsApi } from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import { useUIModeStore } from "@/store/ui-mode";
import { ChatMessage } from "@/components/chat/message";
import { ChatInput, SendOptions } from "@/components/chat/input";
import { TaskData } from "@/components/chat/task-panel";
import { FlowTaskTree } from "@/components/flow/flow-task-tree";
import { TaskDetailPanel } from "@/components/flow/task-detail-panel";
import { LogPanel, LogEntry } from "@/components/chat/log-panel";
import { FileExplorerPanel } from "@/components/chat/file-explorer-panel";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { NotesPanel } from "@/components/chat/notes-panel";
import { ConversationUsagePanel } from "@/components/chat/conversation-usage-panel";
import { PlanPanel, Plan as PlanType, PlanStep } from "@/components/chat/plan-panel";
import { ChatFilesPanel, ChatFile } from "@/components/chat/chat-files-panel";
import { WebhookSettingsPanel } from "@/components/chat/webhook-settings-panel";
import { ExecutionGraphPanel } from "@/components/chat/execution-graph-panel";
import { getWsUrl } from "@/lib/utils";
import { Loader2, ListTodo, Network, Terminal, FolderKanban, FolderCode, Zap, ChevronRight, ChevronDown, ChevronLeft, MessageSquare, CheckCircle, XCircle, Clock, X, Info, NotebookPen, Layers, ClipboardList, Paperclip, Download, Webhook, GitBranch, ShieldCheck, CheckCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import toast from "react-hot-toast";

interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  provider_used?: string;
  metadata_?: Record<string, unknown>;
  agent_id?: string | null;
  agent_name?: string | null;
  user_id?: string | null;
  user_name?: string | null;
  excluded?: boolean;
  created_at?: string | null;
}

interface Participant {
  id: string;
  full_name: string;
  email: string;
  avatar_url?: string | null;
  avatar_emoji?: string | null;
}

export default function ChatPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: chatId } = use(params);
  const router = useRouter();
  const qc = useQueryClient();
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const didInitialScroll = useRef(false);
  const atBottomRef = useRef(true);
  const wsRef = useRef<WebSocket | null>(null);
  const messagesRef = useRef<Message[]>([]);
  const streamingContentRef = useRef<string | null>(null);
  const stopRef = useRef(false);
  const initialTasksLoadedRef = useRef(false);
  const hasHydrated = useAuthStore((s) => s._hasHydrated);
  const currentUser = useAuthStore((s) => s.user);
  const uiMode = useUIModeStore((s) => s.mode);

  const [messages, setMessages] = useState<Message[]>([]);
  const [streamingContent, setStreamingContent] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [wsRetryKey, setWsRetryKey] = useState(0);
  const wsGaveUpRef = useRef(false);
  const wasConnectedRef = useRef(false);
  const wsRetryAttemptRef = useRef(0);
  const activeSubAgentsRef = useRef(0);
  // Stale-activity guard: timestamp of the last WS event + a mirror of isStreaming,
  // so a turn that ends without a clean stream_end (e.g. a weak model that never
  // emits <final/>, or a dropped completion event) can't hang "Agent is writing…"
  // forever — see the watchdog effect below.
  const lastWsActivityRef = useRef<number>(Date.now());
  const isStreamingRef = useRef(false);
  // Deep-descendant activity: a sub-agent several levels below this chat broadcasts a
  // heartbeat. We keep a TTL deadline (refreshed per heartbeat) and show "Sub-agents
  // working…" while it's fresh — so the root + intermediate chats reflect deep work. No
  // decrement to track; it auto-clears when heartbeats stop (see the watchdog effect).
  const descendantBusyUntilRef = useRef<number>(0);
  const userClosedActivitiesRef = useRef(false);
  const uiStateLoadedRef = useRef(false);
  type RightPanel = "tasks" | "logs" | "files" | "attachments" | "usage" | "notes" | "plan" | "webhook" | "graph" | null;
  const [rightPanel, setRightPanel] = useState<RightPanel>(null);
  const [availableFiles, setAvailableFiles] = useState<ChatFile[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [showScrollBtn, setShowScrollBtn] = useState(false);
  const [tasks, setTasks] = useState<TaskData[]>([]);
  const [liveLogs, setLiveLogs] = useState<LogEntry[]>([]);
  const [agentStatus, setAgentStatus] = useState<{ label: string; tool?: string } | null>(null);

  type SubAgentActivity = { 
    taskId: string; 
    agentName: string; 
    taskTitle: string; 
    content: string; 
    done: boolean; 
    failed?: boolean;
    subChatId?: string;
    steps: SubAgentStep[];
    createdAfterMessageId?: string | null;
  };
  
  type AgentActionStep = {
    tool: string;
    label: string;
    status: "running" | "success" | "failed";
    error?: string;
  };
  type AgentActionGroup = {
    groupId: string;
    messageId: string;
    agentName: string;
    steps: AgentActionStep[];
  };
  const [agentActionGroups, setAgentActionGroups] = useState<AgentActionGroup[]>([]);
  const [collapsedActionGroups, setCollapsedActionGroups] = useState<Set<string>>(new Set());
  // Groups we've already auto-collapsed on completion, so a user re-expand sticks.
  const autoCollapsedActionsRef = useRef<Set<string>>(new Set());

  type SubAgentStep = {
    stepId: string;
    name: string;
    label: string;
    status: "pending" | "running" | "success" | "failed";
    error?: string;
  };
  
  const [subAgentActivities, setSubAgentActivities] = useState<SubAgentActivity[]>([]);
  const [collapsedActivities, setCollapsedActivities] = useState<Set<string>>(new Set());
  // Inline tool-approval requests for this chat (#235): show a card with Approve/Deny.
  type PendingApproval = { id: string; tool: string; tier: string; status: "pending" | "approved" | "denied"; messageId?: string | null; result?: unknown; args?: Record<string, unknown> };
  const [pendingApprovals, setPendingApprovals] = useState<PendingApproval[]>([]);
  const [expandedApprovals, setExpandedApprovals] = useState<Set<string>>(new Set());
  const [onlineUserIds, setOnlineUserIds] = useState<Set<string>>(new Set());
  const [chatTitleOverride, setChatTitleOverride] = useState<string | null>(null);
  const [activePlan, setActivePlan] = useState<PlanType | null>(null);
  const [showActivitiesPanel, setShowActivitiesPanel] = useState(false);
  const [activitiesPage, setActivitiesPage] = useState(0);
  const ACTIVITIES_PER_PAGE = 8;

  // Parse tool results from agent content to extract steps
  const parseAgentSteps = useCallback((content: string) => {
    const steps: { tool: string; status: "success" | "error" | "pending"; data?: unknown; error?: string }[] = [];
    const jsonBlockRegex = /\*\*(.+?)\*\*[:\s]*\n?```(?:json)?\s*([\s\S]*?)```/g;
    const errorRegex = /\*\*(.+?)\*\*\s+failed:\s*(.+)/g;
    
    let match;
    while ((match = jsonBlockRegex.exec(content)) !== null) {
      const [, toolName, jsonStr] = match;
      try {
        const data = JSON.parse(jsonStr.trim());
        steps.push({ tool: toolName.trim(), status: "success", data });
      } catch {
        steps.push({ tool: toolName.trim(), status: "pending" });
      }
    }
    
    let errorMatch;
    while ((errorMatch = errorRegex.exec(content)) !== null) {
      const [, toolName, error] = errorMatch;
      steps.push({ tool: toolName.trim(), status: "error", error: error.trim() });
    }
    
    return steps.length > 0 ? steps : null;
  }, []);

  const { data: chat, isLoading: chatLoading } = useQuery({
    queryKey: ["chat", chatId],
    queryFn: () => chatsApi.get(chatId).then((r) => r.data),
    enabled: !!chatId,
  });

  const { data: history, isLoading: historyLoading } = useQuery({
    queryKey: ["messages", chatId],
    queryFn: () => chatsApi.messages(chatId).then((r) => r.data),
    enabled: !!chatId,
  });

  const { data: initialTasks } = useQuery({
    queryKey: ["tasks", chatId],
    queryFn: () => tasksApi.list(chatId).then((r) => r.data),
    enabled: !!chatId,
    refetchInterval: (query) => {
      const tasks = query.state.data as { status: string }[] | undefined;
      if (!tasks) return false;
      const hasActive = tasks.some(
        (t) => t.status === "pending" || t.status === "running" || t.status === "in_progress" || t.status === "queued"
      );
      return hasActive ? 1000 : false;
    },
  });

  // For sub-chats: load the parent task that spawned this chat; poll while still in progress
  const { data: parentTask } = useQuery({
    queryKey: ["task-by-sub-chat", chatId],
    queryFn: () => tasksApi.listBySubChat(chatId).then((r) => r.data),
    enabled: !!chat?.parent_chat_id,
    refetchInterval: (query) => {
      const tasks = query.state.data as { status: string }[] | undefined;
      if (!tasks || tasks.length === 0) return 2000;
      const done = tasks[0].status === "completed" || tasks[0].status === "failed";
      return done ? false : 2000;
    },
  });

  // Load active plan on mount
  const { data: planData } = useQuery({
    queryKey: ["plans", chatId],
    queryFn: () => plansApi.list(chatId).then((r) => r.data as PlanType[]),
    enabled: !!chatId,
  });

  useEffect(() => {
    if (!planData) return;
    const active = planData.find((p) => p.status === "active") ?? planData[0] ?? null;
    if (active) setActivePlan(active);
  }, [planData]);

  const { data: project } = useQuery({
    queryKey: ["project", chat?.project_id],
    queryFn: () => projectsApi.get(chat!.project_id!).then((r) => r.data),
    enabled: !!chat?.project_id,
  });

  const { data: allParticipants = [] } = useQuery<Participant[]>({
    queryKey: ["participants", chatId],
    queryFn: () => chatsApi.participants(chatId).then((r) => r.data),
    enabled: !!chatId,
    staleTime: 30_000,
  });

  const { data: chatFiles = [] } = useQuery<ChatFile[]>({
    queryKey: ["chat-files", chatId],
    queryFn: () => chatFilesApi.list(chatId).then((r) => r.data),
    enabled: !!chatId,
    refetchInterval: 15_000,
  });

  useEffect(() => { setAvailableFiles(chatFiles); }, [chatFiles]);

  useEffect(() => {
    if (!initialTasks || initialTasks.length === 0) return;
    setTasks(initialTasks);

    const dbActivities: SubAgentActivity[] = initialTasks
      // Direct children only — never the current chat itself (a sub-chat must not
      // list itself in its own Sub-agents panel).
      .filter((t: TaskData) => t.sub_chat_id && t.sub_chat_id !== chatId && t.steps)
      .map((t: TaskData) => ({
        taskId: t.id,
        agentName: t.assigned_agent_name || "Agent",
        taskTitle: t.title,
        content: "",
        done: t.status === "completed" || t.status === "failed",
        failed: t.status === "failed",
        subChatId: t.sub_chat_id || undefined,
        createdAfterMessageId: t.created_after_message_id,
        steps: (t.steps || []).map((s: { step_id: string; name: string; label: string; status: string; error?: string | null }) => ({
          stepId: s.step_id,
          name: s.name,
          label: s.label,
          status: s.status as "pending" | "running" | "success" | "failed",
          error: s.error || undefined,
        })),
      }));

    if (dbActivities.length === 0) return;

    const isFirstLoad = !initialTasksLoadedRef.current;
    initialTasksLoadedRef.current = true;

    setSubAgentActivities((prev) => {
      if (isFirstLoad) return dbActivities;
      // Subsequent polls: merge steps from DB into existing WS-built state
      const merged = [...prev];
      for (const dbAct of dbActivities) {
        const idx = merged.findIndex((a) => a.taskId === dbAct.taskId);
        if (idx === -1) {
          merged.push(dbAct);
        } else {
          merged[idx] = {
            ...merged[idx],
            done: dbAct.done || merged[idx].done,
            failed: dbAct.failed || merged[idx].failed,
            steps: dbAct.steps.length > 0 ? dbAct.steps : merged[idx].steps,
          };
        }
      }
      return merged;
    });

    // Auto-collapse completed activities only on first load
    if (isFirstLoad) {
      const completed = new Set(dbActivities.filter((a) => a.done).map((a) => a.taskId));
      setCollapsedActivities(completed);
    }
  }, [initialTasks]);

  // Populate / sync sub-chat activity panel from the parent task (polling while in-progress)
  useEffect(() => {
    if (!parentTask || parentTask.length === 0) return;
    const task = parentTask[0];
    const isDone = task.status === "completed" || task.status === "failed";
    const dbSteps = (task.steps || []).map((s: { step_id: string; name: string; label: string; status: string; error?: string }) => ({
      stepId: s.step_id,
      name: s.name,
      label: s.label,
      status: s.status as "pending" | "running" | "success" | "failed",
      error: s.error || undefined,
    }));

    setSubAgentActivities((prev) => {
      const idx = prev.findIndex((a) => a.taskId === task.id);
      if (idx === -1) {
        // New activity (no WS event arrived)
        return [...prev, {
          taskId: task.id,
          agentName: task.assigned_agent_name || "Agent",
          taskTitle: task.title,
          content: "",
          done: isDone,
          failed: task.status === "failed",
          subChatId: task.sub_chat_id || undefined,
          createdAfterMessageId: undefined,
          steps: dbSteps,
        }];
      }
      // Merge: keep WS-streamed content, sync steps and done status from DB
      const existing = prev[idx];
      const merged = {
        ...existing,
        done: isDone || existing.done,
        failed: task.status === "failed" || existing.failed,
        steps: dbSteps.length > 0 ? dbSteps : existing.steps,
      };
      const result = [...prev];
      result[idx] = merged;
      return result;
    });
  }, [parentTask]);

  useEffect(() => { messagesRef.current = messages; }, [messages]);
  useEffect(() => { streamingContentRef.current = streamingContent; }, [streamingContent]);
  useEffect(() => { isStreamingRef.current = isStreaming; }, [isStreaming]);

  // Stale-activity watchdog: if the UI shows "working" but no WS event has arrived
  // for 3 min, the turn almost certainly ended without a clean stream_end (weak model
  // that never emitted <final/>, or a missed sub_agent_done). Force-clear the indicator
  // so it can never hang for an hour. Real activity (chunks/status/sub-agent events)
  // refreshes lastWsActivityRef, so a genuinely-busy turn is never cut off.
  useEffect(() => {
    const iv = setInterval(() => {
      if (isStreamingRef.current && Date.now() - lastWsActivityRef.current > 180000) {
        setIsStreaming(false);
        setAgentStatus(null);
        activeSubAgentsRef.current = 0;
        descendantBusyUntilRef.current = 0;
        setStreamingContent((c) => (c && c.trim() ? c : null));
      }
      // Deep-descendant heartbeats stopped → clear the bubbled "Sub-agents working…"
      // status (only if it isn't this chat's own turn / direct sub-agents).
      if (
        descendantBusyUntilRef.current &&
        Date.now() > descendantBusyUntilRef.current &&
        !isStreamingRef.current &&
        activeSubAgentsRef.current === 0
      ) {
        descendantBusyUntilRef.current = 0;
        setAgentStatus((s) => (s && s.label === "Sub-agents working…" ? null : s));
      }
    }, 20000);
    return () => clearInterval(iv);
  }, []);

  // Restore per-user per-chat UI state from localStorage
  useEffect(() => {
    // Gate persistence until restore completes, so switching chats can't save the
    // previous chat's (or default) layout over the new chat's saved one.
    uiStateLoadedRef.current = false;
    if (!hasHydrated || !currentUser?.id || !chatId) return;
    const key = `nx_chat_ui_${currentUser.id}_${chatId}`;
    const raw = localStorage.getItem(key);
    // Restore this chat's per-user panel layout (or defaults when none saved, so a
    // panel left open in another chat doesn't bleed over). This effect — not the
    // content-reset effect — owns the panel state.
    let saved: { rightPanel?: RightPanel; showActivitiesPanel?: boolean; activitiesUserClosed?: boolean } = {};
    if (raw) {
      try { saved = JSON.parse(raw); } catch {}
    }
    setRightPanel(saved.rightPanel ?? null);
    setShowActivitiesPanel(saved.showActivitiesPanel ?? false);
    setActivitiesPage(0);
    userClosedActivitiesRef.current = !!saved.activitiesUserClosed;
    uiStateLoadedRef.current = true;
  }, [hasHydrated, currentUser?.id, chatId]);

  // Persist UI state on every change (only after restore gate opens)
  useEffect(() => {
    if (!uiStateLoadedRef.current || !currentUser?.id || !chatId) return;
    const key = `nx_chat_ui_${currentUser.id}_${chatId}`;
    localStorage.setItem(key, JSON.stringify({
      rightPanel,
      showActivitiesPanel,
      activitiesUserClosed: userClosedActivitiesRef.current,
    }));
  }, [rightPanel, showActivitiesPanel, currentUser?.id, chatId]);

  // Invalidate chats list; save message cache so navigating away+back shows full history
  useEffect(() => {
    qc.invalidateQueries({ queryKey: ["chats"] });
    return () => {
      if (messagesRef.current.length > 0) {
        qc.setQueryData(["messages", chatId], messagesRef.current);
      }
    };
  }, [chatId, qc]);

  // Reset chat CONTENT when the chat changes. Panel layout (left sub-agents panel +
  // right panels) is owned by the restore effect above so it persists per chat.
  useEffect(() => {
    setMessages([]);
    setStreamingContent(null);
    setIsStreaming(false);
    didInitialScroll.current = false;
    setShowScrollBtn(false);
    setActivePlan(null);
    setPendingApprovals([]);
    setExpandedApprovals(new Set());
    // Reset per-chat sub-agent + action state too — otherwise the parent chat's
    // sub-agents panel and action cards bleed into a sub-chat you navigate into
    // (so a sub-chat appeared to list ITSELF). Each chat repopulates from its own
    // tasks/history; a sub-chat shows only the sub-chats IT spawned.
    setTasks([]);
    setSubAgentActivities([]);
    setAgentActionGroups([]);
    activeSubAgentsRef.current = 0;
  }, [chatId]);

  // Seed inline approval cards for this chat (so they survive a refresh / late open,
  // not just the live WS event). Loads recent decided ones too — anchored ones stay
  // in their place in the thread and show their result.
  useEffect(() => {
    if (!chatId) return;
    approvalsApi.list("all").then((r) => {
      const mine = (r.data as { id: string; chat_id: string; message_id: string | null; tool_name: string; tool_args?: Record<string, unknown>; risk_tier: string; status: string; result?: unknown }[])
        .filter((a) => a.chat_id === chatId)
        .map((a) => ({ id: a.id, tool: a.tool_name, tier: a.risk_tier || "write", status: a.status as PendingApproval["status"], messageId: a.message_id, result: a.result, args: a.tool_args ?? {} }));
      if (mine.length) setPendingApprovals((prev) => {
        const have = new Set(prev.map((p) => p.id));
        return [...prev, ...mine.filter((m) => !have.has(m.id))];
      });
    }).catch(() => {});
  }, [chatId]);

  // Close advanced-only panels when switching to simple mode
  useEffect(() => {
    if (uiMode === "simple") {
      setShowActivitiesPanel(false);
      setRightPanel((p) => (p === "logs" || p === "notes" ? null : p));
    }
  }, [uiMode]);

  useEffect(() => {
    if (history) setMessages(history);
  }, [history]);

  // Rebuild PM-level action groups from message metadata so they survive page refresh.
  // Live agent_action_* events build groups during streaming; historical PM tool calls
  // are preserved in metadata_.tool_calls_detail and need to be re-projected here.
  useEffect(() => {
    if (!history) return;
    type ToolDetail = { name: string; args?: Record<string, unknown>; status?: string; error?: string };
    const rebuilt: AgentActionGroup[] = [];
    for (const msg of history as Message[]) {
      const detail = (msg.metadata_ as { tool_calls_detail?: ToolDetail[] } | undefined)?.tool_calls_detail;
      if (!detail || !Array.isArray(detail) || detail.length === 0) continue;
      const steps: AgentActionStep[] = detail.map((d) => {
        const formattedName = (d.name || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
        let label = formattedName;
        const args = d.args || {};
        if (d.name === "task_create" && args.title) label = `Create: ${String(args.title).slice(0, 60)}`;
        else if (d.name === "task_update") label = "Update task";
        else if (d.name === "log_entry" && args.message) label = `Log: ${String(args.message).slice(0, 60)}`;
        else if (d.name === "read_url" && args.url) label = `Fetch: ${String(args.url).slice(0, 60)}`;
        else if (d.name === "issue_manage" && args.action === "create" && args.title) label = `Issue: ${String(args.title).slice(0, 60)}`;
        // Honor the persisted per-tool status so a failed tool stays red on refresh
        // (old behavior hardcoded "success", flipping failed tools green on reload).
        const failed = d.status === "failed";
        return { tool: d.name, label, status: failed ? "failed" : "success", error: d.error };
      });
      rebuilt.push({
        groupId: `hist-${msg.id}`,
        messageId: msg.id,
        agentName: msg.agent_name || "Agent",
        steps,
      });
    }
    if (rebuilt.length === 0) return;
    setAgentActionGroups((prev) => {
      // Reconcile so the live view always converges to the PERSISTED truth: for any
      // message that now has a reconstructed group (a completed, saved turn), the
      // reconstruction is authoritative — replace any live group for that message
      // (which may be partial, or missing entirely if this page was unmounted while
      // the turn ran). Keep live groups only for messages NOT yet in history (genuine
      // in-flight turns whose message hasn't been persisted yet). This makes the
      // real-time view identical to what a refresh would show.
      const rebuiltIds = new Set(rebuilt.map((g) => g.messageId));
      const liveInFlight = prev.filter((g) => !rebuiltIds.has(g.messageId));
      return [...liveInFlight, ...rebuilt];
    });
    // Collapse historical groups by default — user can expand them on demand
    setCollapsedActionGroups((prev) => {
      const next = new Set(prev);
      rebuilt.forEach((g) => next.add(g.groupId));
      return next;
    });
  }, [history]);

  // Auto-collapse an action card once all its steps finish (mirrors the thinking
  // panel + sub-agent activity). Once per group, so a manual re-expand persists.
  useEffect(() => {
    const finished = agentActionGroups.filter(
      (g) => g.steps.length > 0
        && g.steps.every((s) => s.status !== "running")
        && !autoCollapsedActionsRef.current.has(g.groupId)
    );
    if (finished.length === 0) return;
    setCollapsedActionGroups((prev) => {
      const next = new Set(prev);
      finished.forEach((g) => { next.add(g.groupId); autoCollapsedActionsRef.current.add(g.groupId); });
      return next;
    });
  }, [agentActionGroups]);

  // Send fork-pending message once BOTH history is loaded AND WS is connected
  useEffect(() => {
    if (!isConnected || !history) return;
    const key = `fork_pending_${chatId}`;
    const stored = sessionStorage.getItem(key);
    if (!stored) return;
    sessionStorage.removeItem(key);
    const { content, options } = JSON.parse(stored) as { content: string; options: Record<string, unknown> };
    setMessages((prev) => {
      if (prev.some((m) => m.role === "user" && m.content === content)) return prev;
      return [...prev, {
        id: `fork-${Date.now()}`,
        role: "user",
        content,
        user_id: currentUser?.id ?? null,
        user_name: currentUser?.full_name ?? null,
      }];
    });
    wsRef.current?.send(JSON.stringify({ type: "message", content, ...options }));
  }, [isConnected, history, chatId]);

  useEffect(() => {
    if (messages.length === 0 && streamingContent === null) return;
    const el = scrollContainerRef.current;
    if (!el) return;
    if (!didInitialScroll.current) {
      didInitialScroll.current = true;
      // Double RAF ensures the browser has fully measured the rendered message list
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          const c = scrollContainerRef.current;
          if (c) { c.scrollTop = c.scrollHeight; atBottomRef.current = true; }
        });
      });
    } else if (atBottomRef.current) {
      // Stay pinned to bottom as new content (streaming chunks, sub-agent panels) arrives
      el.scrollTop = el.scrollHeight;
    }
  }, [messages, streamingContent, subAgentActivities]);

  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const onScroll = () => {
      const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
      setShowScrollBtn(dist > 200);
      atBottomRef.current = dist < 10;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // WebSocket connection — wait for auth store to rehydrate before connecting
  useEffect(() => {
    wsGaveUpRef.current = false;
    wasConnectedRef.current = false;
    wsRetryAttemptRef.current = 0;
  }, [chatId]);

  useEffect(() => {
    if (!hasHydrated) return;

    let cleaned = false;
    const { url, protocols } = getWsUrl(chatId);
    const ws = new WebSocket(url, protocols);
    wsRef.current = ws;
    stopRef.current = false;

    const _backoffDelay = () => {
      const attempt = wsRetryAttemptRef.current;
      // Exponential backoff: 500ms * 2^attempt + up to 500ms jitter, capped at 30s
      return Math.min(500 * Math.pow(2, attempt) + Math.random() * 500, 30_000);
    };

    const _scheduleRetry = () => {
      if (wsGaveUpRef.current || cleaned) return;
      const delay = _backoffDelay();
      wsRetryAttemptRef.current += 1;
      console.warn(`WebSocket retry #${wsRetryAttemptRef.current} in ${Math.round(delay)}ms`);
      setTimeout(() => setWsRetryKey((k) => k + 1), delay);
    };

    // Timeout to detect connection failures
    const connectTimeout = setTimeout(() => {
      if (!cleaned && (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN)) {
        setIsConnected(false);
        _scheduleRetry();
      }
    }, 5000);

    ws.onopen = () => {
      clearTimeout(connectTimeout);
      wasConnectedRef.current = true;
      wsRetryAttemptRef.current = 0;
      setIsConnected(true);
    };

    ws.onclose = () => {
      clearTimeout(connectTimeout);
      setIsConnected(false);
      // Only retry on unexpected close — not when the effect is intentionally cleaning up
      if (!wsGaveUpRef.current && !cleaned) {
        _scheduleRetry();
      }
    };

    ws.onerror = () => {
      clearTimeout(connectTimeout);
      // Don't show toast on every error, let the timeout/retry handle it
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      lastWsActivityRef.current = Date.now();  // feed the stale-activity watchdog

      if (data.type === "error") {
        setIsStreaming(false);
        setStreamingContent(null);
        // Chat not found or access denied - close and don't retry
        if (data.message === "Chat not found") {
          wsGaveUpRef.current = true;
          toast.error("Chat not found");
          ws.close();
          return;
        }
        if (data.message === "Unauthorized") {
          const refresh = localStorage.getItem("refresh_token");
          if (refresh) {
            fetch("/api/auth/refresh", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ refresh_token: refresh }),
            })
              .then((r) => (r.ok ? r.json() : Promise.reject()))
              .then((tokens) => {
                localStorage.setItem("access_token", tokens.access_token);
                localStorage.setItem("refresh_token", tokens.refresh_token);
                setWsRetryKey((k) => k + 1);
              })
              .catch(() => { window.location.href = "/login"; });
          } else {
            window.location.href = "/login";
          }
          return;
        }
        // Turn-failure errors (no providers, chain exhausted, mid-stream crash) are
        // persisted server-side as an excluded assistant message and carry its id.
        // Append the SAME bubble live so the conversation looks identical whether you
        // watch in real time or reload the page (the reloaded view loads it from DB).
        if (data.message_id) {
          setMessages((msgs) => {
            if (msgs.some((m) => m.id === data.message_id)) return msgs;
            return [...msgs, {
              id: data.message_id as string,
              role: "assistant" as const,
              content: data.message as string,
              metadata_: { error: true },
              excluded: true,
              created_at: (data.created_at as string) ?? new Date().toISOString(),
            }];
          });
        } else {
          toast.error(data.message);
        }
      } else if (data.type === "busy") {
        toast.error(data.message || "Sub-agent is still working — please wait.");
      } else if (data.type === "tool_parse_error") {
        // The agent emitted a malformed tool-call. Recoverable (it will be nudged to
        // retry), but surface it so the user isn't left wondering why nothing happened.
        toast(data.message || "Agent produced a malformed tool call — retrying.", { icon: "⚠️" });
      } else if (data.type === "connected") {
        if (data.participants) setOnlineUserIds(new Set((data.participants as { id: string }[]).map((p) => p.id)));
      } else if (data.type === "user_joined") {
        if (data.participants) setOnlineUserIds(new Set((data.participants as { id: string }[]).map((p) => p.id)));
      } else if (data.type === "user_left") {
        if (data.participants) setOnlineUserIds(new Set((data.participants as { id: string }[]).map((p) => p.id)));
      } else if (data.type === "chat_created") {
        // Another user created a chat in the same org/project — refresh sidebar
        qc.invalidateQueries({ queryKey: ["chats"] });
      } else if (data.type === "chat_notes_updated") {
        qc.invalidateQueries({ queryKey: ["chat-notes", chatId] });
      } else if (data.type === "chat_title_updated") {
        setChatTitleOverride(data.title);
        qc.invalidateQueries({ queryKey: ["chats"] });
        qc.invalidateQueries({ queryKey: ["chat", chatId] });
      } else if (data.type === "user_message") {
        // Render any user message posted to this chat in real time — including the SAME
        // user from another client (a CLI, another tab, telegram). Dedup ONLY our own
        // optimistic echo by client_message_id (reconcile its temp id to the server id),
        // and never add a server id we already have.
        const isTelegram = !!data.user_name && data.user_id !== currentUser?.id;
        setMessages((msgs) => {
          if (data.client_message_id) {
            const idx = msgs.findIndex((m) => m.id === data.client_message_id);
            if (idx >= 0) {
              const copy = [...msgs];
              copy[idx] = { ...copy[idx], id: data.message_id || copy[idx].id };
              return copy; // our own optimistic message — reconcile, don't duplicate
            }
          }
          if (data.message_id && msgs.some((m) => m.id === data.message_id)) return msgs;
          return [...msgs, {
            id: data.message_id || Date.now().toString(),
            role: "user" as const,
            content: data.content,
            user_id: isTelegram ? (currentUser?.id ?? data.user_id) : data.user_id,
            user_name: data.user_name,
            metadata_: isTelegram ? { tg_user_display: data.user_name } : undefined,
            created_at: data.created_at ?? new Date().toISOString(),
          }];
        });
      } else if (data.type === "chunk") {
        if (!stopRef.current) {
          setStreamingContent((prev) => (prev ?? "") + data.content);
        }
      } else if (data.type === "stream_start") {
        setIsStreaming(true);
        setAgentStatus({ label: "Agent is writing…" });
        setStreamingContent("");
        stopRef.current = false;
        // Refresh the sidebar so this chat's running spinner appears immediately.
        qc.invalidateQueries({ queryKey: ["chats"] });
      } else if (data.type === "stream_end") {
        setIsStreaming(false);
        // Refresh the sidebar so the running spinner clears promptly.
        qc.invalidateQueries({ queryKey: ["chats"] });
        // Only clear status if no sub-agents are still running
        if (activeSubAgentsRef.current === 0) {
          setAgentStatus(null);
        }
        // Separate setStreamingContent and setMessages — nesting setState inside a
        // setState updater is a React anti-pattern that can silently drop updates in
        // concurrent mode. Backend always sends content in stream_end, and it is
        // AUTHORITATIVE: it equals the saved message (fences/file blobs stripped). Use
        // `??` (not `||`) so an intentionally-empty turn ("" — a pure tool-call / file
        // delivery whose raw stream was just JSON/CSS) does NOT fall back to the raw
        // streamed buffer. That fallback made the live view show fence/code garbage that
        // vanished on refresh (live ≠ saved). Now live snaps to exactly what's persisted.
        const finalContent = (data.content as string | undefined) ?? streamingContentRef.current ?? "";
        setStreamingContent(null);
        // A tool-only turn (e.g. knowledge_search) has its prose blanked, so finalContent
        // is empty — but it carries tool_calls_detail. Keep that message anyway so the
        // action card anchors to it (in chronological place, above the resume answer)
        // instead of orphaning to the bottom of the thread. The empty message renders no
        // bubble (ChatMessage returns null for empty content); only its card shows.
        const _endMeta = (data.metadata as Record<string, unknown>) || {};
        const _hasToolDetail = Array.isArray(_endMeta.tool_calls_detail) && (_endMeta.tool_calls_detail as unknown[]).length > 0;
        if (finalContent.trim() || _hasToolDetail) {
          setMessages((msgs) => {
            if (data.message_id && msgs.some((m) => m.id === data.message_id)) return msgs;
            return [...msgs, {
              id: (data.message_id as string) || Date.now().toString(),
              role: "assistant" as const,
              content: finalContent,
              metadata_: _endMeta,
              created_at: (data.created_at as string) ?? new Date().toISOString(),
            }];
          });
        }
        qc.invalidateQueries({ queryKey: ["chats"] });
        qc.invalidateQueries({ queryKey: ["chat-usage", chatId] });
        // Refetch persisted messages so the action-card rebuild re-runs against the
        // saved turn (with its real tool_calls_detail) and the live view converges to
        // exactly what a refresh would show — including cards for turns that ran while
        // this page wasn't the active view. Authoritative reconcile happens in the
        // rebuild effect; keyed message fragments keep this from causing a remount blink.
        qc.invalidateQueries({ queryKey: ["messages", chatId] });
      } else if (data.type === "task_created") {
        setTasks((prev) => [...prev, data.task as TaskData]);
      } else if (data.type === "task_updated") {
        setTasks((prev) =>
          prev.map((t) => (t.id === data.task.id ? (data.task as TaskData) : t))
        );
      } else if (data.type === "task_deleted") {
        setTasks((prev) => prev.filter((t) => t.id !== data.task_id));
      } else if (data.type === "log_entry") {
        setLiveLogs((prev) => [...prev.slice(-499), data.log as LogEntry]);
      } else if (data.type === "messages_updated") {
        // Autopilot (and other server-side message inserts) → refetch the thread.
        qc.invalidateQueries({ queryKey: ["messages", chatId] });
      } else if (data.type === "file_created" || data.type === "file_updated") {
        // Refresh the panel live. No per-file toast — an agent building a project
        // writes/rewrites many files and the toasts were spammy; the Files panel
        // (with its live count badge) is the surface for this now.
        qc.invalidateQueries({ queryKey: ["chat-files", chatId] });
      } else if (data.type === "approval_pending") {
        setPendingApprovals((prev) =>
          prev.some((a) => a.id === data.approval_id)
            ? prev
            : [...prev, { id: data.approval_id as string, tool: data.tool as string, tier: (data.tier as string) || "write", status: "pending", messageId: (data.message_id as string) ?? null, args: (data.args as Record<string, unknown>) ?? {} }]
        );
        qc.invalidateQueries({ queryKey: ["approvals"] });
      } else if (data.type === "approval_decided") {
        setPendingApprovals((prev) =>
          prev.map((a) => (a.id === data.approval_id ? { ...a, status: data.status as "approved" | "denied", result: data.result ?? a.result } : a))
        );
        qc.invalidateQueries({ queryKey: ["approvals"] });
      } else if (data.type === "activity_status") {
        if (data.status === "idle") {
          if (activeSubAgentsRef.current === 0) {
            setAgentStatus(null);
          }
        } else if (data.status === "executing_tool") {
          setAgentStatus({ label: data.label || data.tool, tool: data.tool });
        } else if (data.status === "running") {
          setAgentStatus({ label: data.label || "Agent is working…" });
        }
      } else if (data.type === "descendant_active") {
        // A sub-agent several levels below is working. Refresh the TTL deadline and, unless
        // this chat is itself streaming or already shows its own direct sub-agents, surface
        // a generic "Sub-agents working…" status so deep activity is visible up the tree.
        // We drive only the status line (not isStreaming) so the input/stop affordances of
        // this chat are unaffected; the watchdog clears it when heartbeats stop.
        descendantBusyUntilRef.current = Date.now() + 120000;
        if (!isStreamingRef.current && activeSubAgentsRef.current === 0) {
          setAgentStatus((s) => s ?? { label: "Sub-agents working…" });
        }
      } else if (data.type === "sub_agent_start") {
        // Ignore an event for THIS chat itself — a chat never lists itself as its
        // own sub-agent (only directly-spawned children belong in the panel).
        if (data.sub_chat_id && data.sub_chat_id === chatId) {
          return;
        }
        activeSubAgentsRef.current++;
        setIsStreaming(true);
        setAgentStatus({ label: "Sub-agents working…" });
        if (!userClosedActivitiesRef.current && useUIModeStore.getState().mode !== "simple") setShowActivitiesPanel(true);
        setSubAgentActivities((prev) => {
          const existing = prev.find((a) => a.taskId === data.task_id);
          if (existing) return prev;
          return [...prev, {
            taskId: data.task_id,
            agentName: data.agent_name || "Agent",
            taskTitle: data.task_title || "Task",
            content: "",
            done: false,
            subChatId: data.sub_chat_id,
            createdAfterMessageId: data.created_after_message_id,
            steps: [],
          }];
        });
        // Sub-chat is created in DB at this point — refresh sidebar immediately
        qc.invalidateQueries({ queryKey: ["chats"] });
      } else if (data.type === "sub_agent_chunk") {
        setSubAgentActivities((prev) =>
          prev.map((a) =>
            a.taskId === data.task_id
              ? { ...a, content: a.content + (data.content || "") }
              : a
          )
        );
      } else if (data.type === "sub_agent_done") {
        activeSubAgentsRef.current = Math.max(0, activeSubAgentsRef.current - 1);
        setSubAgentActivities((prev) =>
          prev.map((a) =>
            a.taskId === data.task_id
              ? { ...a, done: true, failed: !!data.failed, content: data.output || a.content }
              : a
          )
        );
        // Auto-collapse completed activity so it doesn't take up space
        setCollapsedActivities((prev) => {
          const next = new Set(prev);
          next.add(data.task_id as string);
          return next;
        });
        qc.invalidateQueries({ queryKey: ["tasks", chatId] });
        qc.invalidateQueries({ queryKey: ["task-by-sub-chat", chatId] });
      } else if (data.type === "sub_agent_step_start") {
        setSubAgentActivities((prev) =>
          prev.map((a) => {
            if (a.taskId !== data.task_id) return a;
            const stepExists = a.steps.some((s) => s.stepId === data.step_id);
            if (stepExists) return a;
            return {
              ...a,
              steps: [...a.steps, {
                stepId: data.step_id,
                name: data.step_name || data.step_id,
                label: data.step_label || data.step_name || "",
                status: "running",
              }],
            };
          })
        );
      } else if (data.type === "sub_agent_step_done") {
        setSubAgentActivities((prev) =>
          prev.map((a) =>
            a.taskId === data.task_id
              ? {
                  ...a,
                  steps: a.steps.map((s) =>
                    s.stepId === data.step_id
                      ? {
                          ...s,
                          status: data.status === "success" ? "success" : "failed",
                          error: data.error || s.error,
                        }
                      : s
                  ),
                }
              : a
          )
        );
      } else if (data.type === "agent_action_start") {
        setAgentActionGroups((prev) => {
          const existing = prev.find((g) => g.groupId === data.group_id);
          const newStep: AgentActionStep = { tool: data.tool, label: data.label, status: "running" };
          if (existing) {
            return prev.map((g) =>
              g.groupId === data.group_id ? { ...g, steps: [...g.steps, newStep] } : g
            );
          }
          return [...prev, {
            groupId: data.group_id,
            messageId: data.message_id,
            agentName: data.agent_name || "Agent",
            steps: [newStep],
          }];
        });
      } else if (data.type === "agent_action_done") {
        setAgentActionGroups((prev) =>
          prev.map((g) =>
            g.groupId === data.group_id
              ? {
                  ...g,
                  steps: g.steps.map((s, i) =>
                    // Update the last running step that matches this tool
                    i === g.steps.map((x) => x.tool).lastIndexOf(data.tool) && s.status === "running"
                      ? { ...s, status: data.status, error: data.error }
                      : s
                  ),
                }
              : g
          )
        );
      } else if (data.type === "plan_created") {
        setActivePlan(data.plan as PlanType);
        // Only auto-open if user has nothing open — don't steal focus from current panel
        setRightPanel((prev) => prev === null ? "plan" : prev);
      } else if (data.type === "plan_step_updated") {
        const updatedStep = data.step as PlanStep;
        setActivePlan((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            steps: prev.steps.map((s) =>
              s.id === updatedStep.id ? { ...s, ...updatedStep } : s
            ),
          };
        });
      } else if (data.type === "plan_completed") {
        setActivePlan((prev) => {
          if (!prev) return prev;
          return { ...prev, status: "completed" };
        });
      }
    };

    return () => {
      cleaned = true;
      ws.close();
      wsRef.current = null;
      setIsConnected(false);
      setStreamingContent(null);
      setIsStreaming(false);
    };
  }, [chatId, hasHydrated, wsRetryKey, qc]);

  const handleSend = useCallback((content: string, options: SendOptions) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      toast.error(wsRetryAttemptRef.current > 0 ? "Reconnecting… try again in a moment." : "Not connected. Please refresh.");
      return;
    }
    const clientMsgId = crypto.randomUUID?.() ?? 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => { const r = Math.random() * 16 | 0; return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16); });
    setMessages((msgs) => [...msgs, { id: clientMsgId, role: "user", content, user_id: currentUser?.id ?? null, user_name: currentUser?.full_name ?? null, created_at: new Date().toISOString() }]);
    wsRef.current.send(JSON.stringify({
      type: "message",
      content,
      agent_id: options.agent_id,
      provider_chain_id: options.provider_chain_id,
      mode: options.mode,
      model_name: options.model_name ?? null,
      enable_agent: options.enable_agent,
      file_ids: options.file_ids ?? [],
      yolo: options.yolo ?? false,
      autopilot: options.autopilot ?? false,
      client_message_id: clientMsgId,
    }));
  }, []);

  const handleStop = useCallback(async () => {
    stopRef.current = true;
    setIsStreaming(false);
    setAgentStatus(null);
    if (streamingContent) {
      setMessages((msgs) => [...msgs, { id: Date.now().toString(), role: "assistant", content: streamingContent }]);
    }
    setStreamingContent(null);
    try {
      await chatsApi.cancelAll(chatId);
    } catch {
      // best-effort
    }
  }, [streamingContent, chatId]);

  const handleEditSubmit = useCallback(async (messageId: string, newContent: string) => {
    try {
      const res = await chatsApi.fork(chatId, messageId);
      const newChatId: string = res.data.new_chat_id;
      const options = {
        agent_id: chat?.agent_id ?? null,
        provider_chain_id: chat?.provider_chain_id ?? null,
        mode: "flash",
        model_name: null,
        enable_agent: true,
      };
      sessionStorage.setItem(`fork_pending_${newChatId}`, JSON.stringify({ content: newContent, options }));
      qc.invalidateQueries({ queryKey: ["chats"] });
      router.push(`/chat/${newChatId}`);
    } catch {
      toast.error("Failed to fork conversation");
    }
  }, [chatId, chat, qc, router]);

  const handleExcludedToggle = useCallback(async (messageId: string, excluded: boolean) => {
    setMessages((msgs) => msgs.map((m) => m.id === messageId ? { ...m, excluded } : m));
    try {
      await chatsApi.setMessageExcluded(chatId, messageId, excluded);
    } catch {
      setMessages((msgs) => msgs.map((m) => m.id === messageId ? { ...m, excluded: !excluded } : m));
      toast.error("Failed to update message");
    }
  }, [chatId]);

  const decideApproval = useCallback(async (id: string, ok: boolean, rememberSimilar = false) => {
    // optimistic
    setPendingApprovals((prev) => prev.map((a) => (a.id === id ? { ...a, status: ok ? "approved" : "denied" } : a)));
    try {
      await (ok ? approvalsApi.approve(id, rememberSimilar) : approvalsApi.deny(id));
    } catch {
      toast.error("Approval action failed");
      setPendingApprovals((prev) => prev.map((a) => (a.id === id ? { ...a, status: "pending" } : a)));
    }
  }, []);

  // Render one inline approval card (anchored to its originating message). Collapsible:
  // expand to see the exact command + console-formatted output.
  const renderApprovalCard = (a: PendingApproval) => {
    // Pending cards start expanded (need the buttons); decided ones start collapsed.
    const expanded = expandedApprovals.has(a.id) || a.status === "pending";
    const cmd = (a.args && (a.args.command ?? a.args.cmd)) as string | undefined;
    const r = a.result as { data?: unknown; error?: string } | undefined;
    const out = r?.error
      ?? (r?.data && typeof r.data === "object" && typeof (r.data as { output?: unknown }).output === "string"
        ? (r.data as { output: string }).output
        : typeof r?.data === "string" ? r.data
        : r?.data != null ? JSON.stringify(r.data, null, 2) : undefined);
    return (
      <div key={a.id} className={cn(
        "mx-4 my-2 rounded-xl border text-xs overflow-hidden",
        a.status === "approved" ? "border-green-500/30 bg-green-500/5"
          : a.status === "denied" ? "border-destructive/40 bg-destructive/5"
          : "border-yellow-400/40 bg-yellow-400/5"
      )}>
        <button
          onClick={() => setExpandedApprovals((prev) => { const n = new Set(prev); n.has(a.id) ? n.delete(a.id) : n.add(a.id); return n; })}
          className="w-full flex items-center gap-2 px-3 py-2 text-left"
        >
          {expanded ? <ChevronDown className="w-3.5 h-3.5 shrink-0 text-muted-foreground" /> : <ChevronRight className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />}
          <ShieldCheck className={cn("w-3.5 h-3.5 shrink-0",
            a.status === "approved" ? "text-green-500" : a.status === "denied" ? "text-destructive" : "text-yellow-400")} />
          <span className="font-medium text-foreground">Approval required</span>
          <span className="text-muted-foreground">·</span>
          <span className="font-mono text-foreground">{a.tool}</span>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground uppercase">{a.tier}</span>
          <span className="ml-auto text-muted-foreground">
            {a.status === "pending" ? "" : a.status === "approved" ? "approved ✓" : "denied"}
          </span>
        </button>
        {expanded && (
          <div className="px-3 pb-2.5 space-y-2">
            {cmd && (
              <div>
                <p className="text-[10px] text-muted-foreground mb-1">Command</p>
                <pre className="text-[11px] font-mono bg-black/40 rounded p-2 overflow-x-auto whitespace-pre text-foreground/90">{cmd}</pre>
              </div>
            )}
            {a.status === "approved" && out != null && (
              <div>
                <p className="text-[10px] text-muted-foreground mb-1">Output</p>
                <pre className="text-[11px] font-mono leading-relaxed bg-black/40 rounded p-2 max-h-80 overflow-auto whitespace-pre text-foreground/90">{out}</pre>
              </div>
            )}
            {a.status === "pending" && (
              <div className="flex flex-wrap gap-2 pt-0.5">
                <button onClick={() => decideApproval(a.id, true)}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md bg-green-500/10 text-green-400 hover:bg-green-500/20 transition-colors">
                  <CheckCircle className="w-3.5 h-3.5" /> Approve & Run
                </button>
                <button onClick={() => decideApproval(a.id, true, true)}
                  title="Approve this and stop asking for similar commands for the rest of this conversation"
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 transition-colors">
                  <CheckCheck className="w-3.5 h-3.5" /> Always allow similar
                </button>
                <button onClick={() => decideApproval(a.id, false)}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors">
                  <XCircle className="w-3.5 h-3.5" /> Deny
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  // Render one "Agent · N actions" card (reused for message-anchored + orphan groups).
  const renderActionGroup = (g: AgentActionGroup) => {
    const isCollapsed = collapsedActionGroups.has(g.groupId);
    const allDone = g.steps.every((s) => s.status !== "running");
    const anyFailed = g.steps.some((s) => s.status === "failed");
    return (
      <div key={g.groupId} className={cn(
        "mx-4 my-2 rounded-xl border text-xs overflow-hidden",
        anyFailed ? "border-destructive/40 bg-destructive/5" : allDone ? "border-border bg-muted/30" : "border-primary/30 bg-primary/5"
      )}>
        <div className="flex items-center gap-2 px-3 py-2 border-b border-inherit">
          <button
            onClick={() => setCollapsedActionGroups((prev) => {
              const next = new Set(prev);
              next.has(g.groupId) ? next.delete(g.groupId) : next.add(g.groupId);
              return next;
            })}
            className="shrink-0 text-muted-foreground hover:text-foreground transition-colors"
          >
            {isCollapsed ? <ChevronRight className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>
          <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", anyFailed ? "bg-destructive" : allDone ? "bg-green-400" : "bg-primary animate-pulse")} />
          <span className="font-medium text-foreground">{g.agentName}</span>
          <span className="text-muted-foreground">·</span>
          <span className="text-muted-foreground truncate flex-1">
            {g.steps.length === 1 ? g.steps[0].label : `${g.steps.length} actions`}
          </span>
          <span className="text-muted-foreground text-xs ml-1">
            {!allDone ? "working…" : anyFailed ? "failed" : "done"}
          </span>
        </div>
        {!isCollapsed && (
          <div className="px-3 py-2 space-y-1.5 bg-muted/20">
            {g.steps.map((step, i) => (
              <div key={i} className="flex items-start gap-2 text-[11px] animate-fade-in">
                {step.status === "success" ? (
                  <CheckCircle className="w-3 h-3 text-green-500 shrink-0 mt-0.5" />
                ) : step.status === "failed" ? (
                  <XCircle className="w-3 h-3 text-destructive shrink-0 mt-0.5" />
                ) : (
                  <Clock className="w-3 h-3 text-primary shrink-0 mt-0.5 animate-pulse" />
                )}
                <span className="font-medium text-foreground">{step.label}</span>
                {step.error && <span className="text-destructive ml-1">{step.error}</span>}
              </div>
            ))}
            {g.steps.length === 0 && (
              <p className="text-[11px] text-muted-foreground italic animate-pulse py-0.5">Working…</p>
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-3 border-b border-border shrink-0">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          {chat?.parent_chat_id && (
            <button
              onClick={() => router.push(`/chat/${chat.parent_chat_id}`)}
              title="Back to parent conversation"
              className="p-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground shrink-0"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
          )}

          <div className="min-w-0">
            <h1 className="text-sm font-semibold">{chatTitleOverride || chat?.title || "Chat"}</h1>
            <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${isConnected ? "bg-green-400" : "bg-yellow-400 animate-pulse"}`} />
              {isConnected ? "Connected" : wasConnectedRef.current ? `Reconnecting…${wsRetryAttemptRef.current > 1 ? ` (${wsRetryAttemptRef.current})` : ""}` : "Connecting…"}
              {project && (
                <>
                  <span className="opacity-30">·</span>
                  <FolderKanban className="w-3 h-3 shrink-0" />
                  <span className="truncate max-w-[160px]">{project.name}</span>
                </>
              )}
            </div>
          </div>
        </div>

        {/* Participant presence indicators — always show all members */}
        {allParticipants.length > 1 && (
          <div className="flex items-center gap-1 shrink-0">
            {allParticipants.map((p) => {
              const isOnline = onlineUserIds.has(p.id);
              const isMe = p.id === currentUser?.id;
              return (
                <div
                  key={p.id}
                  title={`${p.full_name}${isOnline ? " · online" : " · offline"}`}
                  className={cn(
                    "w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 transition-all duration-300",
                    isMe ? "bg-primary text-primary-foreground" : "bg-accent text-foreground",
                    isOnline
                      ? "ring-2 ring-green-400 ring-offset-1 ring-offset-background shadow-[0_0_6px_rgba(74,222,128,0.5)]"
                      : "ring-1 ring-border opacity-50"
                  )}
                >
                  {p.full_name.charAt(0).toUpperCase()}
                </div>
              );
            })}
          </div>
        )}

        <div className="flex items-center gap-1 shrink-0">
          {uiMode !== "simple" && (
            <button
              onClick={() => setShowActivitiesPanel((p) => {
                const next = !p;
                userClosedActivitiesRef.current = !next;
                return next;
              })}
              title="Sub-agent activities"
              className={cn(
                "p-1.5 rounded hover:bg-accent transition-colors relative",
                showActivitiesPanel ? "text-foreground bg-accent" : "text-muted-foreground"
              )}
            >
              <Layers className="w-4 h-4" />
              {subAgentActivities.some((a) => !a.done) && (
                <span className="absolute top-0.5 right-0.5 w-1.5 h-1.5 rounded-full bg-primary" />
              )}
            </button>
          )}
          {(
            [
              { key: "tasks" as const, Icon: ListTodo, title: "Task tree", advancedOnly: false },
              { key: "logs"  as const, Icon: Terminal, title: "Agent logs", advancedOnly: true },
              { key: "notes" as const, Icon: NotebookPen, title: "Chat notes", advancedOnly: true },
            ]
          ).filter(({ advancedOnly }) => !advancedOnly || uiMode !== "simple").map(({ key, Icon, title }) => (
            <button
              key={key}
              onClick={() => { setRightPanel((p) => (p === key ? null : key)); if (key !== "tasks") setSelectedTaskId(null); }}
              title={title}
              className={`p-1.5 rounded hover:bg-accent transition-colors ${rightPanel === key ? "text-foreground bg-accent" : "text-muted-foreground"}`}
            >
              <Icon className="w-4 h-4" />
            </button>
          ))}
          <button
            onClick={() => setRightPanel((p) => (p === "plan" ? null : "plan"))}
            title="Execution plan"
            className={cn(
              "p-1.5 rounded hover:bg-accent transition-colors relative",
              rightPanel === "plan" ? "text-foreground bg-accent" : "text-muted-foreground"
            )}
          >
            <ClipboardList className="w-4 h-4" />
            {activePlan && activePlan.status === "active" && (
              <span className="absolute top-0.5 right-0.5 w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
            )}
          </button>
          <div className="relative group">
            <button
              title="Export conversation"
              className="p-1.5 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
            >
              <Download className="w-4 h-4" />
            </button>
            <div className="absolute right-0 top-full mt-1 bg-popover border border-border rounded-md shadow-lg hidden group-hover:block z-20 min-w-[140px]">
              <a
                href={chatsApi.exportUrl(chatId, "json")}
                download
                className="flex items-center gap-2 px-3 py-2 text-sm text-foreground hover:bg-accent rounded-t-md transition-colors"
              >
                Export JSON
              </a>
              <a
                href={chatsApi.exportUrl(chatId, "markdown")}
                download
                className="flex items-center gap-2 px-3 py-2 text-sm text-foreground hover:bg-accent rounded-b-md transition-colors"
              >
                Export Markdown
              </a>
            </div>
          </div>
          <button
            onClick={() => window.open(`/hierarchy/${chatId}`, "_blank")}
            title="Agent hierarchy (opens in new window)"
            className="p-1.5 rounded hover:bg-accent transition-colors text-muted-foreground"
          >
            <Network className="w-4 h-4" />
          </button>
          <button
            onClick={() => setRightPanel((p) => (p === "graph" ? null : "graph"))}
            title="Execution graph"
            className={cn(
              "p-1.5 rounded hover:bg-accent transition-colors",
              rightPanel === "graph" ? "text-foreground bg-accent" : "text-muted-foreground"
            )}
          >
            <GitBranch className="w-4 h-4" />
          </button>
          <button
            onClick={() => setRightPanel((p) => (p === "usage" ? null : "usage"))}
            title="Conversation stats"
            className={`p-1.5 rounded hover:bg-accent transition-colors ${rightPanel === "usage" ? "text-foreground bg-accent" : "text-muted-foreground"}`}
          >
            <Info className="w-4 h-4" />
          </button>
          <button
            onClick={() => setRightPanel((p) => (p === "attachments" ? null : "attachments"))}
            title="Attached files"
            className={cn(
              "p-1.5 rounded hover:bg-accent transition-colors relative",
              rightPanel === "attachments" ? "text-foreground bg-accent" : "text-muted-foreground"
            )}
          >
            <Paperclip className="w-4 h-4" />
            {availableFiles.length > 0 && (
              <span className="absolute top-0.5 right-0.5 w-1.5 h-1.5 rounded-full bg-primary" />
            )}
          </button>
          <button
            onClick={() => setRightPanel((p) => (p === "webhook" ? null : "webhook"))}
            title="Webhook settings"
            className={cn(
              "p-1.5 rounded hover:bg-accent transition-colors relative",
              rightPanel === "webhook" ? "text-foreground bg-accent" : "text-muted-foreground"
            )}
          >
            <Webhook className="w-4 h-4" />
            {chat?.webhook_url && (
              <span className="absolute top-0.5 right-0.5 w-1.5 h-1.5 rounded-full bg-green-400" />
            )}
          </button>
          {project?.repo_url && project?.repo_credential_id && (
            <button
              onClick={() => setRightPanel((p) => (p === "files" ? null : "files"))}
              title="Repository explorer"
              className={`p-1.5 rounded hover:bg-accent transition-colors ${rightPanel === "files" ? "text-foreground bg-accent" : "text-muted-foreground"}`}
            >
              <FolderCode className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* Body: messages + optional task panel */}
      <div className="flex flex-1 min-h-0">
        {/* LEFT: Sub-agent activities panel */}
        {uiMode !== "simple" && showActivitiesPanel && (() => {
          const running = subAgentActivities.filter((a) => !a.done);
          const done = subAgentActivities.filter((a) => a.done);
          const sorted = [...running, ...done];
          const totalPages = Math.ceil(sorted.length / ACTIVITIES_PER_PAGE);
          const paged = sorted.slice(activitiesPage * ACTIVITIES_PER_PAGE, (activitiesPage + 1) * ACTIVITIES_PER_PAGE);
          return (
            <div className="flex flex-col h-full w-64 border-r border-border bg-card shrink-0 overflow-hidden">
              <div className="flex items-center justify-between px-3 py-2.5 border-b border-border shrink-0">
                <div className="flex items-center gap-2">
                  <Layers className="w-3.5 h-3.5 text-muted-foreground" />
                  <span className="text-xs font-semibold">Sub-agents</span>
                  {running.length > 0 && (
                    <span className="text-[10px] bg-primary/10 text-primary px-1.5 py-0.5 rounded font-mono">
                      {running.length} active
                    </span>
                  )}
                </div>
                <button
                  onClick={() => { userClosedActivitiesRef.current = true; setShowActivitiesPanel(false); }}
                  className="p-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
              <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
                {sorted.length === 0 ? (
                  <p className="text-xs text-muted-foreground text-center py-8">No sub-agent activity yet.</p>
                ) : paged.map((a) => {
                  const isCollapsed = collapsedActivities.has(a.taskId);
                  return (
                    <div key={a.taskId} className={cn(
                      "rounded-lg border text-xs overflow-hidden",
                      a.failed ? "border-destructive/40 bg-destructive/5" : a.done ? "border-border bg-muted/30" : "border-primary/30 bg-primary/5"
                    )}>
                      <div className="flex items-center gap-1.5 px-2.5 py-2 border-b border-inherit">
                        <button
                          onClick={() => setCollapsedActivities((prev) => {
                            const next = new Set(prev);
                            next.has(a.taskId) ? next.delete(a.taskId) : next.add(a.taskId);
                            return next;
                          })}
                          className="shrink-0 text-muted-foreground hover:text-foreground transition-colors"
                        >
                          {isCollapsed ? <ChevronRight className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                        </button>
                        <span className={cn(
                          "w-1.5 h-1.5 rounded-full shrink-0",
                          a.failed ? "bg-destructive" : a.done ? "bg-green-400" : "bg-primary animate-pulse"
                        )} />
                        <div className="flex-1 min-w-0">
                          <div className="font-medium text-foreground truncate">{a.agentName}</div>
                          <div className="text-muted-foreground truncate text-[10px] leading-tight">{a.taskTitle}</div>
                        </div>
                        {a.subChatId && (
                          <a
                            href={`/chat/${a.subChatId}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground transition-colors shrink-0"
                            title="Open sub-chat"
                          >
                            <MessageSquare className="w-3 h-3" />
                          </a>
                        )}
                      </div>
                      {!isCollapsed && (
                        <div className="px-2.5 py-2 space-y-1 bg-muted/20">
                          {a.steps.map((step, stepIdx) => (
                            <div
                              key={step.stepId}
                              className="flex items-start gap-1.5 text-[10px] animate-fade-in"
                              style={{ animationDelay: `${stepIdx * 40}ms`, animationFillMode: "both" }}
                            >
                              {step.status === "success" ? (
                                <CheckCircle className="w-2.5 h-2.5 text-green-500 shrink-0 mt-0.5" />
                              ) : step.status === "failed" ? (
                                <XCircle className="w-2.5 h-2.5 text-destructive shrink-0 mt-0.5" />
                              ) : (
                                <Clock className="w-2.5 h-2.5 text-primary shrink-0 mt-0.5 animate-pulse" />
                              )}
                              <span className="text-foreground leading-tight">{step.label}</span>
                              {step.error && <span className="text-destructive ml-1">{step.error}</span>}
                            </div>
                          ))}
                          {!a.done && a.steps.length === 0 && (
                            <p className="text-[10px] text-muted-foreground italic animate-pulse py-0.5">Analyzing…</p>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
              {totalPages > 1 && (
                <div className="flex items-center justify-between px-3 py-2 border-t border-border shrink-0 text-xs text-muted-foreground">
                  <button
                    onClick={() => setActivitiesPage((p) => Math.max(0, p - 1))}
                    disabled={activitiesPage === 0}
                    className="p-1 rounded hover:bg-accent disabled:opacity-40 transition-colors"
                  >
                    <ChevronLeft className="w-3.5 h-3.5" />
                  </button>
                  <span>{activitiesPage + 1} / {totalPages}</span>
                  <button
                    onClick={() => setActivitiesPage((p) => Math.min(totalPages - 1, p + 1))}
                    disabled={activitiesPage >= totalPages - 1}
                    className="p-1 rounded hover:bg-accent disabled:opacity-40 transition-colors"
                  >
                    <ChevronRight className="w-3.5 h-3.5" />
                  </button>
                </div>
              )}
            </div>
          );
        })()}
        <div className="flex flex-col flex-1 min-w-0 relative">
          {/* Messages */}
          <div ref={scrollContainerRef} className="flex-1 overflow-y-auto">
            {historyLoading ? (
              <div className="flex items-center justify-center h-full">
                <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <div className="max-w-3xl mx-auto py-4">
                {messages.length === 0 && !isStreaming && (
                  <div className="text-center py-16 text-muted-foreground text-sm">
                    Send a message to start the conversation.
                  </div>
                )}
                {messages
                  .filter((msg) => {
                    // A delegating turn (e.g. log_entry + task_create) has empty visible
                    // content but carries an anchored action group ("Agent · N actions").
                    // Keep it so that card survives a page refresh — dropping it orphaned
                    // the reconstructed group and the actions vanished on reload.
                    if (!msg.content || !msg.content.trim().length) {
                      if (!agentActionGroups.some((g) => g.messageId === msg.id)) return false;
                    }
                    // Hide system-injected messages (tool results, nudge prompts). These are
                    // always excluded=true, role="user", with no user_id and a metadata.kind.
                    // A user-excluded message (the eye toggle) must STAY visible — dimmed via
                    // opacity — so it can be re-included: user messages carry a user_id, and
                    // excluded assistant/agent messages have no user_id but are real agent
                    // messages (role assistant / agent_id / agent_name), so spare those.
                    if (msg.excluded && !msg.user_id) {
                      const isAgentMsg = !!msg.agent_id || msg.role === "assistant" || !!msg.agent_name;
                      if (!isAgentMsg) return false;
                    }
                    return true;
                  })
                  .map((msg, idx, filteredMsgs) => {
                    // Determine if this message is from an agent. Rely only on structural
                    // signals (role / agent_id / agent_name); content sniffing produces
                    // false positives when user prose mentions "[Tool results …]" verbatim.
                    const isAgentMessage = !!msg.agent_id || msg.role === "assistant" || !!msg.agent_name;
                    const displayAgentName = isAgentMessage ? msg.agent_name : null;
                    const displayRole = isAgentMessage ? "assistant" : "user";

                    // Group consecutive messages from the same sender (WhatsApp-style)
                    const getSenderKey = (m: Message) =>
                      m.role === "user"
                        ? `user:${m.user_id ?? "anon"}`
                        : `agent:${m.agent_id ?? "assistant"}`;
                    const prevMsg = idx > 0 ? filteredMsgs[idx - 1] : null;
                    const prevHadActionGroups = prevMsg
                      ? agentActionGroups.some((g) => g.messageId === prevMsg.id)
                      : false;
                    const isContinuation = !!(
                      prevMsg &&
                      !prevHadActionGroups &&
                      getSenderKey(msg) === getSenderKey(prevMsg)
                    );

                    return (
                      // Keyed Fragment: without a key here React reconciles these map
                      // items by index, so when sibling structure shifts (orphan action
                      // cards appearing/disappearing per sub-agent step) the ChatMessages
                      // remount and their header + fade-in replays — the per-step blink.
                      <Fragment key={msg.id}>
                        {/* Action + approval cards render ABOVE this message's bubble:
                            the tool calls happened to produce the turn, so they read as
                            "agent did X, then said Y" — and stay above the final answer
                            instead of dangling beneath it. */}
                        {agentActionGroups
                          .filter((g) => g.messageId === msg.id)
                          .map((g) => renderActionGroup(g))}
                        {pendingApprovals
                          .filter((a) => a.messageId === msg.id)
                          .map((a) => renderApprovalCard(a))}
                        <ChatMessage
                          role={displayRole}
                          content={msg.content}
                          providerUsed={msg.provider_used}
                          agentName={displayAgentName}
                          userName={msg.user_name}
                          userId={msg.metadata_?.tg_user_display ? (currentUser?.id ?? null) : (msg.user_id ?? null)}
                          currentUserId={currentUser?.id ?? null}
                          avatarEmoji={
                            (msg.metadata_?.tg_user_display ? currentUser?.id : msg.user_id) === currentUser?.id
                              ? (currentUser?.avatar_emoji ?? undefined)
                              : (allParticipants.find(p => p.id === msg.user_id)?.avatar_emoji ?? undefined)
                          }
                          metadata={msg.metadata_ as never}
                          messageId={msg.id}
                          excluded={msg.excluded}
                          isContinuation={isContinuation}
                          createdAt={msg.created_at ?? undefined}
                          subordinateAgentName={
                            // For task_brief: lookup the sub-chat's primary agent name
                            // from any message authored by it. The brief itself is from the
                            // parent (different agent_id), so we scan the rest of history.
                            (msg.metadata_ as { kind?: string } | undefined)?.kind === "task_brief"
                              ? (messages.find(
                                  (m) =>
                                    m.id !== msg.id &&
                                    m.agent_id &&
                                    m.agent_id === chat?.agent_id &&
                                    !!m.agent_name,
                                )?.agent_name ?? null)
                              : null
                          }
                          onEditSubmit={handleEditSubmit}
                          onExcludedToggle={handleExcludedToggle}
                        />
                      </Fragment>
                    );
                  })}

                {/* Orphan action cards — live groups whose anchor message isn't in the
                    list yet (the assistant message arrives on stream_end). Rendered
                    ABOVE the streaming bubble so the card sits ABOVE the text both during
                    streaming and once anchored on finalize (anchored cards also render
                    above their message) — consistent, no above→below jump. */}
                {agentActionGroups
                  .filter((g) => !messages.some((m) => m.id === g.messageId))
                  .map((g) => renderActionGroup(g))}

                {/* Orphan approval cards — pending ones whose anchor message isn't in
                    the list yet (decided ones show anchored in the thread, not here). */}
                {pendingApprovals
                  .filter((a) => a.status === "pending" && (!a.messageId || !messages.some((m) => m.id === a.messageId)))
                  .map((a) => renderApprovalCard(a))}

                {streamingContent !== null && (() => {
                  const visibleMsgs = messages.filter((m) => m.content && m.content.trim().length > 0);
                  const lastMsg = visibleMsgs[visibleMsgs.length - 1];
                  const streamIsContinuation = !!(lastMsg && lastMsg.role === "assistant");
                  return (
                    <ChatMessage
                      role="assistant"
                      content={streamingContent}
                      isStreaming={isStreaming}
                      userId={null}
                      currentUserId={currentUser?.id ?? null}
                      isContinuation={streamIsContinuation}
                    />
                  );
                })()}

                <div ref={bottomRef} />
              </div>
            )}
          </div>

          {/* Scroll to bottom button */}
          {showScrollBtn && (
            <button
              onClick={() => bottomRef.current?.scrollIntoView({ behavior: "smooth" })}
              className="absolute bottom-24 right-4 z-10 w-8 h-8 rounded-full bg-card border border-border shadow-md flex items-center justify-center hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
              title="Scroll to bottom"
            >
              <ChevronDown className="w-4 h-4" />
            </button>
          )}

          {/* Agent activity status bar — shown whenever agent is active, tools run, or tasks pending */}
          {(() => {
            // Names of sub-agents working right now (incl. autonomous runs under this
            // chat) — so the user can see WHAT is running beneath the conversation.
            const runningAgents = Array.from(
              new Set(subAgentActivities.filter((a) => !a.done).map((a) => a.agentName).filter(Boolean))
            );
            const subAgentLabel =
              runningAgents.length === 0 ? null
              : runningAgents.length === 1 ? `${runningAgents[0]} is working…`
              : `${runningAgents.length} agents working: ${runningAgents.slice(0, 3).join(", ")}${runningAgents.length > 3 ? "…" : ""}`;
            const effectiveStatus = agentStatus ?? (
              subAgentLabel ? { label: subAgentLabel }
              : (isStreaming || tasks.some(t => ["pending", "queued", "in_progress"].includes(t.status)))
                ? { label: "Working…" }
                : null
            );
            return effectiveStatus ? (
              // Branded activity strip — now also carries live fallback-chain status
              // (which provider/model is being tried, failovers, retries) so the user
              // can see what the agent is doing instead of staring at an empty bubble.
              <div className="flex items-center gap-2 px-4 py-1.5 border-t border-border bg-background/60 shrink-0">
                <Zap className={cn(
                  "w-3 h-3 shrink-0",
                  effectiveStatus.tool ? "text-primary animate-pulse" : "text-muted-foreground animate-pulse",
                )} />
                <span className="text-xs text-muted-foreground truncate">{effectiveStatus.label}</span>
              </div>
            ) : null;
          })()}

          {/* Input */}
          <ChatInput
            chatId={chatId}
            currentChainId={chat?.provider_chain_id}
            currentDirectProviderId={chat?.direct_provider_id}
            defaultAgentId={project?.pm_agent_id}
            onSend={handleSend}
            onStop={handleStop}
            isStreaming={isStreaming || subAgentActivities.some((a) => !a.done)}
            disabled={!isConnected}
            availableFiles={availableFiles}
            onFilesUploaded={(files) => setAvailableFiles((prev) => {
              const ids = new Set(prev.map((f) => f.id));
              return [...prev, ...files.filter((f) => !ids.has(f.id))];
            })}
          />
        </div>

        {rightPanel === "tasks" && (() => {
          const selectedTask = selectedTaskId ? tasks.find((t) => t.id === selectedTaskId) ?? null : null;
          return selectedTask ? (
            <TaskDetailPanel
              task={selectedTask}
              allTasks={tasks}
              onClose={() => setSelectedTaskId(null)}
              onSelectTask={(t) => setSelectedTaskId(t.id)}
            />
          ) : (
            <div className="flex flex-col h-full w-64 border-l border-border bg-card shrink-0 overflow-hidden">
              <div className="flex items-center justify-between px-3 py-2.5 border-b border-border shrink-0">
                <div className="flex items-center gap-2">
                  <ListTodo className="w-3.5 h-3.5 text-muted-foreground" />
                  <span className="text-xs font-semibold">Tasks</span>
                  {tasks.length > 0 && (
                    <span className="text-[10px] bg-accent px-1.5 py-0.5 rounded font-mono text-muted-foreground">
                      {tasks.filter((t) => t.status === "completed").length}/{tasks.length}
                    </span>
                  )}
                </div>
                <button
                  onClick={() => setRightPanel(null)}
                  className="p-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
              <FlowTaskTree
                tasks={tasks}
                selectedId={null}
                onSelect={(t) => {
                  if (t.sub_chat_id) {
                    router.push(`/chat/${t.sub_chat_id}`);
                  } else {
                    setSelectedTaskId(t.id);
                  }
                }}
              />
            </div>
          );
        })()}
{rightPanel === "logs" && (
          <LogPanel
            chatId={chatId}
            liveEntries={liveLogs}
            onClose={() => setRightPanel(null)}
          />
        )}
        {rightPanel === "notes" && (
          <NotesPanel
            chatId={chatId}
            onClose={() => setRightPanel(null)}
          />
        )}
        {rightPanel === "usage" && (
          <ConversationUsagePanel chatId={chatId} isStreaming={isStreaming} onClose={() => setRightPanel(null)} />
        )}
        {rightPanel === "plan" && (
          <PlanPanel plan={activePlan} onClose={() => setRightPanel(null)} />
        )}
        {rightPanel === "attachments" && (
          <ChatFilesPanel
            chatId={chatId}
            onClose={() => setRightPanel(null)}
          />
        )}
        {rightPanel === "files" && project && (
          <ErrorBoundary
            fallbackTitle="Repository panel failed to load"
            onClose={() => setRightPanel(null)}
            resetKey={project.id}
          >
            <FileExplorerPanel
              project={{
                id: project.id,
                name: project.name,
                repo_url: project.repo_url,
                repo_type: project.repo_type,
                repo_branch: project.repo_branch,
                repo_credential_id: project.repo_credential_id,
              }}
              onClose={() => setRightPanel(null)}
            />
          </ErrorBoundary>
        )}
        {rightPanel === "webhook" && (
          <WebhookSettingsPanel
            chatId={chatId}
            onClose={() => setRightPanel(null)}
          />
        )}
        {rightPanel === "graph" && (
          <ExecutionGraphPanel
            chatId={chatId}
            onClose={() => setRightPanel(null)}
          />
        )}
      </div>
    </div>
  );
}
