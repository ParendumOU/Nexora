import axios from "axios";

const api = axios.create({
  baseURL: "/api",
  headers: { "Content-Type": "application/json" },
});

// Single in-flight refresh promise — prevents simultaneous refresh races
let _refreshPromise: Promise<string> | null = null;

function _decodeExp(token: string): number | null {
  try {
    const part = token.split(".")[1];
    const json = atob(part.replace(/-/g, "+").replace(/_/g, "/"));
    const payload = JSON.parse(json);
    return typeof payload.exp === "number" ? payload.exp : null;
  } catch {
    return null;
  }
}

// Refresh the access token (deduped). Uses bare axios so it never re-enters the
// `api` interceptors. Rejects if there is no refresh token.
function _refresh(): Promise<string> {
  if (!_refreshPromise) {
    const refresh = localStorage.getItem("refresh_token");
    if (!refresh) return Promise.reject(new Error("no refresh token"));
    _refreshPromise = axios
      .post("/api/auth/refresh", { refresh_token: refresh })
      .then((res) => {
        localStorage.setItem("access_token", res.data.access_token);
        localStorage.setItem("refresh_token", res.data.refresh_token);
        return res.data.access_token as string;
      })
      .finally(() => { _refreshPromise = null; });
  }
  return _refreshPromise;
}

/**
 * Return a valid (non-expired) access token, refreshing proactively when it is
 * expired or within 30s of expiry. Prevents the 401-storm-then-refresh pattern.
 * Used by the axios request interceptor and the user WebSocket before connect.
 */
export async function ensureFreshToken(): Promise<string | null> {
  const token = localStorage.getItem("access_token");
  if (!token) return null;
  const exp = _decodeExp(token);
  if (exp && exp * 1000 - Date.now() < 30_000) {
    try {
      return await _refresh();
    } catch {
      return token; // let the request proceed; the 401 path will handle it
    }
  }
  return token;
}

api.interceptors.request.use(async (config) => {
  const token = await ensureFreshToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

function _clearSession() {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
  // Clear Zustand persisted auth so the redirect doesn't flash the workspace
  try {
    const stored = JSON.parse(localStorage.getItem("auth-storage") || "{}");
    if (stored.state) {
      stored.state.isAuthenticated = false;
      stored.state.user = null;
      localStorage.setItem("auth-storage", JSON.stringify(stored));
    }
  } catch {}
  window.location.replace("/login");
}

api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const originalRequest = error.config;

    // Only attempt refresh once per request
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;
      const refresh = localStorage.getItem("refresh_token");

      if (!refresh) {
        _clearSession();
        return Promise.reject(error);
      }

      try {
        const newToken = await _refresh();
        originalRequest.headers.Authorization = `Bearer ${newToken}`;
        return api(originalRequest);
      } catch {
        _clearSession();
        return Promise.reject(error);
      }
    }

    return Promise.reject(error);
  }
);

export default api;

// ─── Auth ───────────────────────────────────────────────────────
export const authApi = {
  firstRun: () => api.get("/auth/first-run"),
  register: (data: { email: string; password: string; full_name: string; org_name?: string; invite_token?: string }) =>
    api.post("/auth/register", data),
  login: (data: { email: string; password: string }) => api.post("/auth/login", data),
  totpLogin: (data: { totp_token: string; code: string }) => api.post("/auth/totp-login", data),
  forgotPassword: (email: string) => api.post("/auth/forgot-password", { email }),
  resetPassword: (token: string, password: string) => api.post("/auth/reset-password", { token, password }),
  me: () => api.get("/users/me"),
  validateInvite: (token: string) => api.get(`/auth/invite/${token}`),
  createInvite: (data: { email?: string }) => api.post("/auth/invite", data),
  oauthProviders: () => api.get<{ google: boolean; github: boolean }>("/auth/oauth/providers"),
};

export const totpApi = {
  status:      ()                   => api.get("/users/me/totp/status"),
  setup:       ()                   => api.post("/users/me/totp/setup"),
  verifySetup: (code: string)       => api.post("/users/me/totp/verify-setup", { code }),
  disable:     (code: string)       => api.post("/users/me/totp/disable", { code }),
};

// ─── Users ──────────────────────────────────────────────────────
export const usersApi = {
  me: () => api.get("/users/me"),
  update: (data: {
    full_name?: string;
    avatar_url?: string | null;
    avatar_emoji?: string | null;
    notes?: string | null;
    contact_info?: string | null;
  }) => api.patch("/users/me", data),
  changePassword: (data: { current_password: string; new_password: string }) =>
    api.patch("/users/me/password", data),
  listAll: () => api.get("/users/"),
  setActive: (userId: string, isActive: boolean) =>
    api.patch(`/users/${userId}/active`, { is_active: isActive }),
  getMarketplaceKey: () => api.get<{ configured: boolean }>("/users/me/marketplace-key"),
  setMarketplaceKey: (key: string) => api.put("/users/me/marketplace-key", { key }),
};

export const userApiKeysApi = {
  list: () => api.get("/users/me/api-keys/"),
  create: (name: string) => api.post("/users/me/api-keys/", { name }),
  rotate: (id: string) => api.post(`/users/me/api-keys/${id}/rotate`),
  revoke: (id: string) => api.delete(`/users/me/api-keys/${id}`),
};

export const devicesApi = {
  // Mint a pairing code + QR for the Nexora mobile app.
  start: (baseUrl?: string) => api.post("/auth/device/start", { base_url: baseUrl }),
  list: () => api.get("/auth/device"),
  revoke: (id: string) => api.delete(`/auth/device/${id}`),
};

export const backupApi = {
  exportMine: () => api.get("/users/me/backup/export", { responseType: "blob" }),
  importMine: (payload: object) => api.post("/users/me/backup/import", payload),
  exportAll: () => api.get("/users/backup/export", { responseType: "blob" }),
};

// Full-platform backup / restore (superuser-only).
export const platformBackupApi = {
  startExport: (body: { scope: "instance" | "org"; org_ids?: string[]; include_vectors?: boolean }) =>
    api.post("/platform-backup/export", body),
  status: (jobId: string) => api.get(`/platform-backup/${jobId}`),
  downloadUrl: (jobId: string) => `/platform-backup/${jobId}/download`,
  download: (jobId: string) =>
    api.get(`/platform-backup/${jobId}/download`, { responseType: "blob" }),
  import: (file: File, opts: { mode?: string; reembed?: boolean; allow_secret_loss?: boolean } = {}) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("mode", opts.mode ?? "skip");
    fd.append("reembed", String(opts.reembed ?? true));
    fd.append("allow_secret_loss", String(opts.allow_secret_loss ?? false));
    return api.post("/platform-backup/import", fd);
  },
  // Direct migration: build a backup here and push it straight into a target instance.
  migrate: (body: {
    target_url: string;
    target_token: string;
    scope?: "instance" | "org";
    org_ids?: string[];
    include_vectors?: boolean;
  }) => api.post("/platform-backup/migrate", body),
};

export const notificationsApi = {
  list: () => api.get("/notifications/"),
  markRead: (id: string) => api.post(`/notifications/${id}/read`),
  markAllRead: () => api.post("/notifications/read-all"),
  delete: (id: string) => api.delete(`/notifications/${id}`),
};

// ─── Search ─────────────────────────────────────────────────────
export const searchApi = {
  search: (q: string, limit = 20) => api.get("/search", { params: { q, limit } }),
  /** Global full-text search across all user chats and messages. */
  global: (q: string, limit = 20) => api.get("/search", { params: { q, limit } }),
};

export interface InstalledPackageUpdate {
  id: string;
  item_type: string;
  source_slug: string;
  origin: string;
  name: string;
  installed_version: string;
  available_version: string | null;
  pricing_type: string;
  update_available: boolean;
  last_checked_at: string | null;
}

// ─── Marketplace import risk acknowledgment (GitLab #158) ──────────────────
/** Coarse third-party liability signal from the marketplace. */
export type MarketplaceWarningLevel = "standard" | "elevated" | "high";

/** Body of the 409 returned by POST /marketplace/import when a low-reputation
 *  package requires explicit risk acknowledgment. FastAPI wraps the HTTPException
 *  detail under a top-level `detail` key. */
export interface RiskAcknowledgmentRequired {
  error: "risk_acknowledgment_required";
  slug: string;
  type: string;
  warning_level: MarketplaceWarningLevel;
  trust_tier: string;
  below_like_threshold: boolean;
  below_download_threshold: boolean;
  disclaimer: string;
  message: string;
}

/** Successful import response (GitLab #158 fields included). */
export interface MarketplaceImportResult {
  installed: boolean;
  slug: string;
  type: string;
  name: string;
  disclaimer?: string;
  warning_level?: MarketplaceWarningLevel;
  trust_tier?: string;
  risk_acknowledged?: boolean;
  python_requirements?: ToolEnvStatus[];
  required_env_vars?: { key: string; tools: string[] }[];
  installed_dependencies?: { slug: string; type: string }[];
  skipped_dependencies?: { slug: string; type: string; reason: string }[];
  failed_dependencies?: { slug: string; type: string; reason: string }[];
  dependencies_note?: string;
}

export const marketplaceApi = {
  list: (params?: { q?: string; item_type?: string; page?: number; per_page?: number }) =>
    api.get("/marketplace", { params }),
  get: (slug: string) => api.get(`/marketplace/${slug}`),
  install: (slug: string) => api.post(`/marketplace/${slug}/install`),
  /**
   * Import a marketplace package by URL. When `acknowledgeRisk` is true the
   * backend will install a low-reputation (elevated/high warning) package that
   * would otherwise 409 with `risk_acknowledgment_required` (GitLab #158).
   */
  importFromUrl: (url: string, acknowledgeRisk = false) =>
    api.post<MarketplaceImportResult>("/marketplace/import", { url, acknowledge_risk: acknowledgeRisk }),
  // Update tracking
  listUpdates: () =>
    api.get<{ items: InstalledPackageUpdate[]; updates_available: number }>("/marketplace/updates"),
  checkUpdates: () =>
    api.post<{ checked: boolean; updates_available: number; items: InstalledPackageUpdate[] }>("/marketplace/updates/check"),
  applyUpdate: (installedId: string) =>
    api.post<{ updated: boolean; slug: string; type: string; version: string }>(`/marketplace/updates/${installedId}/apply`),
};

// ─── Tool environments (per-pack Python venvs for tools with requirements) ──
export interface ToolEnvStatus {
  requirements: string[];
  env_hash: string | null;
  provisioned: boolean;
  enabled?: boolean;
}
export const toolEnvsApi = {
  list: () => api.get<{ items: { env_hash: string; requirements: string[] }[]; enabled: boolean }>("/tool-envs"),
  status: (requirements: string[]) =>
    api.post<ToolEnvStatus>("/tool-envs/status", { requirements }),
  provision: (requirements: string[]) =>
    api.post<{ ok: boolean; env_hash?: string | null; error?: string; cached?: boolean }>(
      "/tool-envs/provision", { requirements },
    ),
};

// ─── Environment variables (org + user scoped tool credentials) ──
export interface EnvVar {
  id: string;
  scope: "org" | "user";
  org_id: string | null;
  key: string;
  name: string;
  description: string | null;
  has_value: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}
export interface EnvVarResolveEntry {
  key: string;
  configured: { id: string; scope: "org" | "user"; name: string; org_id: string | null }[];
}
export const envVarsApi = {
  list: (params?: { scope?: "org" | "user"; org_id?: string }) =>
    api.get<{ env_vars: EnvVar[] }>("/env-vars", { params }),
  create: (data: { scope: "org" | "user"; org_id?: string | null; key: string; name: string; value: string; description?: string }) =>
    api.post<EnvVar>("/env-vars", data),
  update: (id: string, data: { value?: string; description?: string; name?: string }) =>
    api.patch<EnvVar>(`/env-vars/${id}`, data),
  delete: (id: string) => api.delete(`/env-vars/${id}`),
  resolve: (keys: string[], org_id?: string) =>
    api.post<{ keys: EnvVarResolveEntry[] }>("/env-vars/resolve", { keys, org_id }),
};

// ─── Chats ──────────────────────────────────────────────────────
export const chatsApi = {
  // No parent_id → top-level chats only (fast sidebar load). parent_id=<chat> → that
  // chat's direct children (lazy, one level), since an autonomous run can spawn thousands
  // of sub-chats and loading them all made the sidebar crawl.
  list: (params?: { agent_id?: string; parent_id?: string }) => api.get("/chats/", { params }),
  create: (data: { title?: string; project_id?: string; project_ids?: string[]; agent_id?: string; provider_chain_id?: string }) =>
    api.post("/chats/", data),
  get: (id: string) => api.get(`/chats/${id}`),
  messages: (id: string) => api.get(`/chats/${id}/messages`),
  // Per-chat runtime toggles (YOLO, Autopilot) — persisted so they survive refresh/switch.
  getFlags: (id: string) => api.get(`/chats/${id}/flags`),
  setFlags: (id: string, body: { yolo?: boolean; autopilot?: boolean }) =>
    api.post(`/chats/${id}/flags`, body),
  updateTitle: (id: string, title: string) => api.patch(`/chats/${id}/title`, { title }),
  delete: (id: string) => api.delete(`/chats/${id}`),
  bulkDelete: (ids: string[]) => api.post(`/chats/bulk-delete`, { ids }),
  resume: (id: string) => api.post(`/chats/${id}/resume`),
  setProviderChain: (id: string, chainId: string | null) =>
    api.patch(`/chats/${id}/provider-chain`, { provider_chain_id: chainId }),
  setDirectProvider: (id: string, providerId: string | null) =>
    api.patch(`/chats/${id}/provider-chain`, { direct_provider_id: providerId }),
  participants: (id: string) => api.get(`/chats/${id}/participants`),
  join: (id: string) => api.post(`/chats/${id}/join`),
  fork: (id: string, beforeMessageId: string) =>
    api.post(`/chats/${id}/fork`, { before_message_id: beforeMessageId }),
  setMessageExcluded: (chatId: string, messageId: string, excluded: boolean) =>
    api.patch(`/chats/${chatId}/messages/${messageId}/excluded`, { excluded }),
  // active_only (default true) returns only unfinished chats + the paths connecting them
  // — fast on a run with thousands of sub-chats. Pass false for the full tree ("Show all").
  hierarchy: (id: string, activeOnly: boolean = true) =>
    api.get(`/chats/${id}/hierarchy`, { params: { active_only: activeOnly } }),
  cancelAll: (id: string) => api.post(`/chats/${id}/cancel-all`),
  usage: (id: string) => api.get(`/chats/${id}/usage`),
  getNotes: (id: string, page = 1, pageSize = 20) =>
    api.get(`/chats/${id}/notes`, { params: { page, page_size: pageSize } }),
  createNote: (id: string, data: { content: string; description?: string; author?: string }) =>
    api.post(`/chats/${id}/notes`, data),
  updateNote: (id: string, noteId: string, data: { content?: string; description?: string; author?: string }) =>
    api.patch(`/chats/${id}/notes/${noteId}`, data),
  deleteNote: (id: string, noteId: string) =>
    api.delete(`/chats/${id}/notes/${noteId}`),
  exportUrl: (id: string, format: "json" | "markdown") =>
    `/api/chats/${id}/export?format=${format}`,
  search: (q: string, page = 1, perPage = 10) =>
    api.get("/chats/search", { params: { q, page, per_page: perPage } }),
  executionTreeSnapshot: (id: string) => api.get(`/chats/${id}/execution-tree/snapshot`),
  executionTreeUrl: (id: string) => `/api/chats/${id}/execution-tree`,
  updateWebhook: (
    id: string,
    data: {
      webhook_url?: string | null;
      webhook_secret?: string | null;
      sync_response?: boolean;
      sync_timeout?: number;
    }
  ) => api.patch(`/chats/${id}/webhook`, data),
};

// ─── Chat Files ──────────────────────────────────────────────────
export const chatFilesApi = {
  list: (chatId: string) => api.get(`/chats/${chatId}/files`),
  upload: (chatId: string, files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return api.post(`/chats/${chatId}/files`, fd, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },
  delete: (chatId: string, fileId: string) =>
    api.delete(`/chats/${chatId}/files/${fileId}`),
  contentUrl: (chatId: string, fileId: string) =>
    `/api/chats/${chatId}/files/${fileId}/content`,
};

// ─── Agents ─────────────────────────────────────────────────────
export const agentsApi = {
  list: () => api.get("/agents"),
  create: (data: object) => api.post("/agents", data),
  get: (id: string) => api.get(`/agents/${id}`),
  update: (id: string, data: object) => api.patch(`/agents/${id}`, data),
  delete: (id: string) => api.delete(`/agents/${id}`),
  builtinTypes: () => api.get("/agents/types/builtin"),
  builtinFiles: (key: string) => api.get(`/agents/builtin/${key}/files`),
  analytics: (id: string, days = 30) => api.get(`/agents/${id}/analytics`, { params: { days } }),
  getTemplates: () => api.get("/agents/templates"),
  getShare: (id: string) => api.get<{ share_token: string; share_enabled: boolean; share_url: string }>(`/agents/${id}/share`),
  enableShare: (id: string) => api.post<{ share_token: string; share_enabled: boolean; share_url: string }>(`/agents/${id}/share`),
  disableShare: (id: string) => api.delete(`/agents/${id}/share`),
  listVersions: (id: string) => api.get(`/agents/${id}/versions`),
  getVersion: (id: string, versionId: string) => api.get(`/agents/${id}/versions/${versionId}`),
  revertToVersion: (id: string, versionId: string) => api.post(`/agents/${id}/versions/${versionId}/revert`),
};

// ─── Skills catalog ──────────────────────────────────────────────
export const skillsApi = {
  builtin: () => api.get("/skills/builtin"),
  builtinFiles: (key: string) => api.get(`/skills/builtin/${key}/files`),
  builtinExport: (key: string) => api.get(`/skills/builtin/${key}/export`, { responseType: "blob" }),
  list: () => api.get("/skills"),
  create: (data: { key: string; name: string; description?: string; category?: string }) =>
    api.post("/skills", data),
  delete: (id: string) => api.delete(`/skills/${id}`),
  export: (id: string) => api.get(`/skills/${id}/export`, { responseType: "blob" }),
  // File management
  files: (id: string) => api.get(`/skills/${id}/files`),
  getFile: (id: string, path: string) => api.get(`/skills/${id}/files/${path}`),
  putFile: (id: string, path: string, content: string) =>
    api.put(`/skills/${id}/files/${path}`, { content }),
  deleteFile: (id: string, path: string) => api.delete(`/skills/${id}/files/${path}`),
};

// ─── Organizations ──────────────────────────────────────────────
export const orgsApi = {
  list: () => api.get("/orgs"),
  create: (data: { name: string; icon?: string | null; color?: string | null }) =>
    api.post("/orgs", data),
  update: (id: string, data: { name?: string; icon?: string | null; color?: string | null }) =>
    api.patch(`/orgs/${id}`, data),
  deletionSummary: (id: string) => api.get(`/orgs/${id}/deletion-summary`),
  delete: (id: string, body?: { wipe?: string[]; reassign_to_org_id?: string }) =>
    api.delete(`/orgs/${id}`, { data: body ?? {} }),
  members: (id: string) => api.get(`/orgs/${id}/members`),
  removeMember: (orgId: string, userId: string) => api.delete(`/orgs/${orgId}/members/${userId}`),
  updateMemberRole: (orgId: string, userId: string, role: string) =>
    api.patch(`/orgs/${orgId}/members/${userId}`, { role }),
  leave: (orgId: string) => api.post(`/orgs/${orgId}/leave`),
  createInvite: (orgId: string, role = "member") => api.post(`/orgs/${orgId}/invites`, { role }),
  getInviteDetails: (token: string) => api.get(`/orgs/invite/${token}`),
  acceptInvite: (token: string) => api.post("/orgs/accept-invite", { token }),
  switchOrg: (org_id: string) => api.post("/orgs/switch", { org_id }),
};

// ─── Personas ───────────────────────────────────────────────────
export const personasApi = {
  builtin: () => api.get("/personas/builtin"),
  builtinFiles: (key: string) => api.get(`/personas/builtin/${key}/files`),
  builtinExport: (key: string) => api.get(`/personas/builtin/${key}/export`, { responseType: "blob" }),
  list: () => api.get("/personas"),
  create: (data: object) => api.post("/personas", data),
  update: (id: string, data: object) => api.patch(`/personas/${id}`, data),
  delete: (id: string) => api.delete(`/personas/${id}`),
  export: (id: string) => api.get(`/personas/${id}/export`, { responseType: "blob" }),
};

// ─── Tools catalog ───────────────────────────────────────────────
export const toolsApi = {
  builtin: () => api.get("/tools/builtin"),
  builtinFiles: (key: string) => api.get(`/tools/builtin/${key}/files`),
  builtinExport: (key: string) => api.get(`/tools/builtin/${key}/export`, { responseType: "blob" }),
  list: () => api.get("/tools"),
  create: (data: { key: string; name: string; description?: string; category?: string }) =>
    api.post("/tools", data),
  update: (id: string, data: object) => api.patch(`/tools/${id}`, data),
  delete: (id: string) => api.delete(`/tools/${id}`),
  export: (id: string) => api.get(`/tools/${id}/export`, { responseType: "blob" }),
  files: (id: string) => api.get(`/tools/${id}/files`),
  putFile: (id: string, path: string, content: string) =>
    api.put(`/tools/${id}/files/${path}`, { content }),
  deleteFile: (id: string, path: string) => api.delete(`/tools/${id}/files/${path}`),
};

// ─── MCP servers catalog ──────────────────────────────────────────
export const mcpServersApi = {
  list: () => api.get("/mcp-servers"),
  create: (data: { name: string; url: string; description?: string; config?: object; auth_type?: string; auth_value?: string }) =>
    api.post("/mcp-servers", data),
  update: (id: string, data: object) => api.patch(`/mcp-servers/${id}`, data),
  delete: (id: string) => api.delete(`/mcp-servers/${id}`),
  tools: (id: string) => api.get(`/mcp-servers/${id}/tools`),
  fetchTools: (id: string) => api.post(`/mcp-servers/${id}/tools/fetch`),
};

// ─── Agent Memories ──────────────────────────────────────────────
export interface ProfileFact {
  id: string;
  key: string;
  value: string;
  source: string | null;
  updated_at: string;
}

export const profileFactsApi = {
  list: () => api.get<ProfileFact[]>("/users/me/profile-facts"),
  upsert: (key: string, value: string) =>
    api.put<ProfileFact>(`/users/me/profile-facts/${encodeURIComponent(key)}`, { value }),
  delete: (key: string) => api.delete(`/users/me/profile-facts/${encodeURIComponent(key)}`),
};

export interface MemoryNoteSummary {
  id: string;
  path: string;
  title: string;
  tags: string[];
  agent_id: string | null;
  updated_at: string;
}

export interface MemoryNote extends MemoryNoteSummary {
  body_md: string;
  user_id: string | null;
  chat_id: string | null;
  created_at: string;
}

export interface MemoryGraph {
  nodes: Array<{
    id: string; type: "note" | "tag"; label: string;
    path?: string; tags?: string[]; agent_id?: string | null; folder?: string;
  }>;
  links: Array<{ source: string; target: string; type: "wikilink" | "tag" }>;
}

export const memoryNotesApi = {
  list: (params?: { folder?: string; tag?: string; agent_id?: string; search?: string }) =>
    api.get<MemoryNoteSummary[]>("/memory-notes", { params }),
  graph: (agentId?: string) =>
    api.get<MemoryGraph>("/memory-notes/graph", { params: agentId ? { agent_id: agentId } : undefined }),
  get: (id: string) => api.get<MemoryNote>(`/memory-notes/${id}`),
  create: (data: { title: string; body_md?: string; path?: string; tags?: string[] }) =>
    api.post<MemoryNote>("/memory-notes", data),
  update: (id: string, data: { title?: string; body_md?: string; path?: string; tags?: string[] }) =>
    api.patch<MemoryNote>(`/memory-notes/${id}`, data),
  move: (id: string, path: string) => api.post<MemoryNote>(`/memory-notes/${id}/move`, { path }),
  delete: (id: string) => api.delete(`/memory-notes/${id}`),
};

export const memoriesApi = {
  list: (agentId: string) => api.get(`/agents/${agentId}/memories`),
  create: (agentId: string, data: {
    type?: string; content: string; tags?: string[]; priority?: number;
  }) => api.post(`/agents/${agentId}/memories`, data),
  update: (agentId: string, memId: string, data: {
    type?: string; content?: string; tags?: string[]; priority?: number;
  }) => api.patch(`/agents/${agentId}/memories/${memId}`, data),
  delete: (agentId: string, memId: string) => api.delete(`/agents/${agentId}/memories/${memId}`),
};

// ─── Projects ───────────────────────────────────────────────────
export const gitCredentialsApi = {
  list: () => api.get("/git-credentials"),
  create: (data: { name: string; provider: string; token: string; color?: string; base_url?: string }) =>
    api.post("/git-credentials", data),
  update: (id: string, data: object) => api.patch(`/git-credentials/${id}`, data),
  delete: (id: string) => api.delete(`/git-credentials/${id}`),
  repos: (id: string) => api.get(`/git-credentials/${id}/repos`),
  expand: (id: string, nodeId?: string) =>
    api.get(`/git-credentials/${id}/repos/expand`, { params: nodeId ? { node_id: nodeId } : {} }),
};

export const gitProxyApi = {
  branches: (credentialId: string, repoUrl: string) =>
    api.get("/git-proxy/branches", { params: { credential_id: credentialId, repo_url: repoUrl } }),
  tree: (credentialId: string, repoUrl: string, branch: string) =>
    api.get("/git-proxy/tree", { params: { credential_id: credentialId, repo_url: repoUrl, branch } }),
  file: (credentialId: string, repoUrl: string, path: string, branch: string) =>
    api.get("/git-proxy/file", { params: { credential_id: credentialId, repo_url: repoUrl, path, branch } }),
  commits: (credentialId: string, repoUrl: string, branch: string) =>
    api.get("/git-proxy/commits", { params: { credential_id: credentialId, repo_url: repoUrl, branch } }),
  compare: (credentialId: string, repoUrl: string, base: string, head: string) =>
    api.get("/git-proxy/compare", { params: { credential_id: credentialId, repo_url: repoUrl, base, head } }),
  deleteBranch: (credentialId: string, repoUrl: string, branch: string) =>
    api.delete("/git-proxy/branches", { params: { credential_id: credentialId, repo_url: repoUrl, branch } }),
  merge: (data: { credential_id: string; repo_url: string; base: string; head: string; message?: string }) =>
    api.post("/git-proxy/merge", data),
  // #242 — where can this credential create a repo, and create one
  namespaces: (credentialId: string) =>
    api.get("/git-proxy/namespaces", { params: { credential_id: credentialId } }),
  createRepo: (data: { credential_id: string; name: string; namespace?: string; private?: boolean; description?: string }) =>
    api.post("/git-proxy/create-repo", data),
};

export const projectsApi = {
  list: () => api.get("/projects"),
  create: (data: object) => api.post("/projects", data),
  bulkImport: (repos: Array<{ name: string; repo_url: string; repo_type: string; credential_id?: string; description?: string; default_branch?: string }>) =>
    api.post("/projects/import", { repos }),
  get: (id: string) => api.get(`/projects/${id}`),
  update: (id: string, data: object) => api.patch(`/projects/${id}`, data),
  delete: (id: string) => api.delete(`/projects/${id}`),
  agents: (id: string) => api.get(`/projects/${id}/agents`),
  tasks: (id: string) => api.get(`/projects/${id}/tasks`),
  issues: (id: string) => api.get(`/projects/${id}/issues`),
  syncIssues: (id: string) => api.post(`/projects/${id}/sync-issues`),
  logs: (id: string) => api.get(`/projects/${id}/logs`),
};

// ─── Tasks ──────────────────────────────────────────────────────
export const tasksApi = {
  list: (chatId: string) => api.get(`/tasks?chat_id=${chatId}`),
  listBySubChat: (subChatId: string) => api.get(`/tasks?sub_chat_id=${subChatId}`),
  listAll: () => api.get("/tasks"),
  create: (data: {
    chat_id: string;
    title: string;
    description?: string;
    parent_id?: string;
    assigned_agent_id?: string;
    model_override?: string;
    position?: number;
  }) => api.post("/tasks", data),
  update: (id: string, data: {
    title?: string;
    description?: string;
    status?: string;
    assigned_agent_id?: string | null;
    model_override?: string | null;
    checklist?: Array<{ id: string; item: string; done: boolean }>;
    output?: string;
    position?: number;
  }) => api.patch(`/tasks/${id}`, data),
  interrupt: (id: string, data?: { reason?: string; reassign_to_agent_id?: string | null }) =>
    api.post(`/tasks/${id}/interrupt`, data ?? {}),
  delete: (id: string) => api.delete(`/tasks/${id}`),
};

// ─── Board ──────────────────────────────────────────────────────
export const boardApi = {
  byProject: (projectId: string, agentId?: string) =>
    api.get(`/board?project_id=${projectId}${agentId ? `&agent_id=${agentId}` : ""}`),
  byOrg: (agentId?: string) =>
    api.get(`/board${agentId ? `?agent_id=${agentId}` : ""}`),
};

// ─── Seeds ──────────────────────────────────────────────────────
export const seedsApi = {
  catalog: () => api.get("/seeds/catalog"),
  exportItems: (items: Array<{ type: string; key?: string }>) =>
    api.post("/seeds/export", { items }, { responseType: "blob" }),
  importZip: (file: File, overwrite = false) => {
    const fd = new FormData();
    fd.append("file", file);
    return api.post(`/seeds/import?overwrite=${overwrite}`, fd, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },
  deleteCustom: (type: string, key: string) => api.delete(`/seeds/custom/${type}/${key}`),
  installDeps: (deps: Array<{ slug: string; key: string; name: string; type: string; version: string }>) =>
    api.post("/seeds/install-deps", { deps }),
};

// ─── Issues ─────────────────────────────────────────────────────
export const issuesApi = {
  list: (params?: {
    project_id?: string;
    status?: string;
    priority?: string;
    assigned_agent_id?: string;
    label?: string;
    search?: string;
    limit?: number;
    offset?: number;
  }) => api.get("/issues", { params }),
  create: (data: {
    project_id: string;
    title: string;
    description?: string;
    priority?: string;
    labels?: string[];
    assigned_agent_id?: string;
    external_url?: string;
    external_ref?: string;
  }) => api.post("/issues", data),
  get: (id: string) => api.get(`/issues/${id}`),
  update: (id: string, data: {
    title?: string;
    description?: string;
    status?: string;
    priority?: string;
    labels?: string[];
    assigned_agent_id?: string | null;
    linked_task_id?: string | null;
    external_url?: string | null;
    external_ref?: string | null;
  }) => api.patch(`/issues/${id}`, data),
  delete: (id: string) => api.delete(`/issues/${id}`),
  comments: (issueId: string) => api.get(`/issues/${issueId}/comments`),
  addComment: (issueId: string, data: { content: string; metadata?: Record<string, unknown> }) =>
    api.post(`/issues/${issueId}/comments`, data),
  deleteComment: (issueId: string, commentId: string) =>
    api.delete(`/issues/${issueId}/comments/${commentId}`),
};

// ─── Proposals ──────────────────────────────────────────────────
export const proposalsApi = {
  list: (status?: string) =>
    api.get("/proposals", { params: status ? { status } : undefined }),
  approve: (id: string) => api.post(`/proposals/${id}/approve`),
  reject: (id: string) => api.post(`/proposals/${id}/reject`),
};

// ─── Agent workspaces (#243, superuser) ─────────────────────────
export const workspacesApi = {
  list: () => api.get("/workspaces"),
  remove: (name: string) => api.delete(`/workspaces/${encodeURIComponent(name)}`),
};

// ─── Goals / autonomy ───────────────────────────────────────────
export const goalsApi = {
  list: (status?: string) => api.get("/goals", { params: status ? { status } : undefined }),
  // Big red button: pause every active autonomous run in the org so the autonomy tick
  // stops dispatching them (they stay stopped across restarts until resumed).
  pauseAll: () => api.post("/goals/pause-all"),
  resumeAll: () => api.post("/goals/resume-all"),
};

// ─── Tool approvals (human-in-the-loop, #235) ───────────────────
export const approvalsApi = {
  list: (status = "pending") => api.get("/approvals", { params: { status } }),
  // rememberSimilar: also stop prompting for similar (same command content) calls
  // for the rest of this conversation tree (#235).
  approve: (id: string, rememberSimilar = false) =>
    api.post(`/approvals/${id}/approve`, null, rememberSimilar ? { params: { remember_similar: true } } : undefined),
  deny: (id: string) => api.post(`/approvals/${id}/deny`),
};

// ─── Logs ───────────────────────────────────────────────────────
export const logsApi = {
  list: (chatId: string, limit = 200) => api.get(`/logs?chat_id=${chatId}&limit=${limit}`),
  create: (data: {
    chat_id: string;
    task_id?: string;
    agent_id?: string;
    agent_name?: string;
    level?: "debug" | "info" | "warn" | "error";
    message: string;
    data?: Record<string, unknown>;
  }) => api.post("/logs", data),
};

// ─── Integrations ───────────────────────────────────────────────
export interface TelegramConversation {
  chat_id: string;
  title: string;
  agent_id: string | null;
  last_message: string | null;
  last_message_role: string | null;
  updated_at: string;
  created_at: string;
}

export const integrationsApi = {
  list: () => api.get("/integrations"),
  create: (data: { name: string; integration_type: string; config: Record<string, unknown> }) =>
    api.post("/integrations", data),
  update: (id: string, data: { name?: string; config?: Record<string, unknown>; is_active?: boolean }) =>
    api.patch(`/integrations/${id}`, data),
  setDefault: (id: string) => api.post(`/integrations/${id}/set-default`, {}),
  delete: (id: string) => api.delete(`/integrations/${id}`),
  listPending: (id: string) => api.get(`/integrations/${id}/pending`),
  accept: (id: string, code: string) => api.post(`/integrations/${id}/accept`, { code }),
  revokePending: (id: string, pendingId: string) => api.delete(`/integrations/${id}/pending/${pendingId}`),
  startBot: (id: string) => api.post<{ ok: boolean }>(`/integrations/${id}/start-bot`),
  stopBot: (id: string) => api.post<{ ok: boolean }>(`/integrations/${id}/stop-bot`),
  conversations: (id: string) => api.get<TelegramConversation[]>(`/integrations/${id}/conversations`),
  deleteConversation: (intId: string, chatId: string) =>
    api.delete(`/integrations/${intId}/conversations/${chatId}`),
};

// ─── Providers ──────────────────────────────────────────────────
export const providersApi = {
  list: () => api.get("/providers"),
  create: (data: object) => api.post("/providers", data),
  update: (id: string, data: object) => api.patch(`/providers/${id}`, data),
  delete: (id: string) => api.delete(`/providers/${id}`),
  restore: (id: string) => api.patch(`/providers/${id}/restore`),
  purge: (id: string) => api.delete(`/providers/${id}/purge`),
  chains: () => api.get("/providers/chains"),
  createChain: (data: { name: string; steps: Array<{ provider_type: string; model_name?: string | null }>; is_default?: boolean }) =>
    api.post("/providers/chains", data),
  updateChain: (id: string, data: { name?: string; steps?: Array<{ provider_type: string; model_name?: string | null }>; is_default?: boolean }) =>
    api.patch(`/providers/chains/${id}`, data),
  deleteChain: (id: string) => api.delete(`/providers/chains/${id}`),
  // OAuth CLI-based auth
  oauthStart: (data: { provider_type: string; account_name: string; model_name?: string }) =>
    api.post("/providers/auth/start", data),
  oauthStatus: (provider: string, accountName: string) =>
    api.get(`/providers/auth/${provider}/status/${encodeURIComponent(accountName)}`),
  oauthSubmitCode: (provider: string, accountName: string, code: string) =>
    api.post(`/providers/auth/${provider}/code/${encodeURIComponent(accountName)}`, { code }),
  oauthComplete: (provider: string, accountName: string, data: object) =>
    api.post(`/providers/auth/${provider}/complete/${encodeURIComponent(accountName)}`, data),
};


// ─── Provider Types (seed definitions) ──────────────────────────
export interface ProviderTypeDef {
  key: string;
  name: string;
  description: string;
  category: "oauth" | "api";
  auth_type: "oauth" | "apikey" | "none";
  stream_type: "claude" | "gemini" | "ollama" | "openai_compat";
  base_url: string | null;
  requires_base_url: boolean;
  default_model: string | null;
  models: string[];
  cli_command?: string | null;
  cli_login_args?: string[];
  credential_paths?: string[];
  credential_format?: string;
  website: string | null;
  source: "builtin" | "custom";
}

export const providerTypesApi = {
  list: () => api.get<ProviderTypeDef[]>("/provider-types"),
  get: (key: string) => api.get<ProviderTypeDef>(`/provider-types/${key}`),
  create: (data: Partial<ProviderTypeDef> & { key: string; name: string }) =>
    api.post<ProviderTypeDef>("/provider-types", data),
  update: (key: string, data: Partial<ProviderTypeDef>) =>
    api.patch<ProviderTypeDef>(`/provider-types/${key}`, data),
  delete: (key: string) => api.delete(`/provider-types/${key}`),
  export: () => api.get("/provider-types/export", { responseType: "blob" }),
  importZip: (file: File, overwrite = false) => {
    const fd = new FormData();
    fd.append("file", file);
    return api.post(`/provider-types/import?overwrite=${overwrite}`, fd, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },
  fetchModels: (data: { base_url: string; api_key?: string | null; stream_type: string }) =>
    api.post<{ models: string[] }>("/provider-types/fetch-models", data),
};

// ─── Schedules ──────────────────────────────────────────────────
export const schedulesApi = {
  list: () => api.get("/schedules"),
  create: (data: {
    name: string;
    description?: string;
    agent_id: string;
    prompt: string;
    cron_expr?: string | null;
    interval_minutes?: number | null;
  }) => api.post("/schedules", data),
  get: (id: string) => api.get(`/schedules/${id}`),
  update: (id: string, data: {
    name?: string;
    description?: string;
    agent_id?: string;
    prompt?: string;
    cron_expr?: string | null;
    interval_minutes?: number | null;
    is_active?: boolean;
  }) => api.patch(`/schedules/${id}`, data),
  delete: (id: string) => api.delete(`/schedules/${id}`),
  activate: (id: string) => api.post(`/schedules/${id}/activate`),
  deactivate: (id: string) => api.post(`/schedules/${id}/deactivate`),
  trigger: (id: string) => api.post(`/schedules/${id}/trigger`),
  runs: (id: string, limit = 50) => api.get(`/schedules/${id}/runs?limit=${limit}`),
  getRun: (runId: string) => api.get(`/schedules/runs/${runId}`),
};

// ─── Usage ──────────────────────────────────────────────────────
export const usageApi = {
  summary: (params?: { period_days?: number }) => api.get("/usage/summary", { params }),
};

// ─── Webhook Rules ──────────────────────────────────────────────
export const webhookRulesApi = {
  list: () => api.get("/webhook-rules"),
  create: (data: {
    source: string;
    event_type: string;
    filter_json?: Record<string, unknown> | null;
    agent_id: string;
    task_title_template: string;
    task_description_template?: string | null;
    webhook_secret?: string | null;
    project_id?: string | null;
    is_active?: boolean;
  }) => api.post("/webhook-rules", data),
  update: (id: string, data: Partial<{
    source: string;
    event_type: string;
    filter_json: Record<string, unknown> | null;
    agent_id: string;
    task_title_template: string;
    task_description_template: string | null;
    webhook_secret: string | null;
    project_id: string | null;
    is_active: boolean;
  }>) => api.put(`/webhook-rules/${id}`, data),
  delete: (id: string) => api.delete(`/webhook-rules/${id}`),
  log: (id: string, limit = 50) => api.get(`/webhook-rules/${id}/log?limit=${limit}`),
};

// ─── Model Profiles ─────────────────────────────────────────────
export const modelProfilesApi = {
  list: () => api.get("/model-profiles"),
  create: (data: {
    name: string;
    description?: string;
    tags: string[];
    provider_type?: string | null;
    provider_chain_id?: string | null;
    model_name?: string | null;
    is_active?: boolean;
    priority?: number;
  }) => api.post("/model-profiles", data),
  update: (id: string, data: {
    name?: string;
    description?: string;
    tags?: string[];
    provider_type?: string | null;
    provider_chain_id?: string | null;
    model_name?: string | null;
    is_active?: boolean;
    priority?: number;
  }) => api.patch(`/model-profiles/${id}`, data),
  delete: (id: string) => api.delete(`/model-profiles/${id}`),
  resolve: (tags: string) => api.get(`/model-profiles/resolve?tags=${encodeURIComponent(tags)}`),
};

// ─── Knowledge Bases ────────────────────────────────────────────
export const knowledgeBasesApi = {
  list: () => api.get("/knowledge-bases"),
  create: (data: {
    name: string;
    description?: string;
    project_id?: string;
    chunk_strategy?: string;
    chunk_size?: number;
    chunk_overlap?: number;
  }) => api.post("/knowledge-bases", data),
  get: (id: string) => api.get(`/knowledge-bases/${id}`),
  update: (id: string, data: {
    name?: string;
    description?: string;
    chunk_strategy?: string;
    chunk_size?: number;
    chunk_overlap?: number;
  }) => api.patch(`/knowledge-bases/${id}`, data),
  delete: (id: string) => api.delete(`/knowledge-bases/${id}`),
  // Files
  listFiles: (kbId: string) => api.get(`/knowledge-bases/${kbId}/files`),
  uploadFile: (kbId: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return api.post(`/knowledge-bases/${kbId}/files`, fd, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },
  deleteFile: (kbId: string, fileId: string) =>
    api.delete(`/knowledge-bases/${kbId}/files/${fileId}`),
  // URL ingestion
  ingestUrl: (kbId: string, url: string) =>
    api.post(`/knowledge-bases/${kbId}/ingest-url`, { url }),
  // Search
  search: (kbId: string, q: string, topK = 5) =>
    api.get(`/knowledge-bases/${kbId}/search`, { params: { q, top_k: topK } }),
};

// ─── Plans ──────────────────────────────────────────────────────
export const plansApi = {
  list: (chatId: string) => api.get(`/plans?chat_id=${chatId}`),
  create: (data: { chat_id: string; title: string; steps: { title: string; description?: string }[] }) =>
    api.post("/plans", data),
  updateStep: (stepId: string, data: { status?: string; note?: string; task_id?: string }) =>
    api.patch(`/plan-steps/${stepId}`, data),
  updatePlan: (planId: string, status: string) =>
    api.patch(`/plans/${planId}`, { status }),
};
