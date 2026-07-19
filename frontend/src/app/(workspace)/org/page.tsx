"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { orgsApi, authApi } from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import { Copy, Check, Trash2, UserPlus, RefreshCw, AlertTriangle, LogOut, ChevronDown } from "lucide-react";
import { cn, copyToClipboard } from "@/lib/utils";
import toast from "react-hot-toast";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { GroupsTab } from "@/components/org/GroupsTab";

const PRESET_COLORS = ["#6366f1", "#8b5cf6", "#ec4899", "#f59e0b", "#10b981", "#3b82f6"];

type Tab = "general" | "members" | "groups" | "invites";

const ROLES = [
  { value: "viewer", label: "Viewer", description: "Read-only access to agents and knowledge bases" },
  { value: "member", label: "Member", description: "Can create and edit agents and knowledge bases" },
  { value: "admin", label: "Admin", description: "Can manage members and org settings" },
  { value: "owner", label: "Owner", description: "Transfer ownership to this person" },
] as const;

interface OrgItem {
  id: string; name: string; slug: string; icon: string | null; color: string | null;
  role: string; is_owner: boolean; is_personal: boolean; member_count: number;
}
interface Member {
  user_id: string; full_name: string; email: string; avatar_url?: string | null;
  role: string; joined_at: string;
}
interface DeletionSummary {
  categories: Record<string, { label: string; count: number }>;
  projects: number;
  reassign_to_org_id: string | null;
}

function RoleBadge({ role }: { role: string }) {
  return (
    <span className={cn(
      "text-[10px] px-2 py-0.5 rounded-full font-medium shrink-0",
      role === "owner" ? "bg-primary/10 text-primary" :
      role === "admin" ? "bg-amber-500/10 text-amber-500" :
      role === "member" ? "bg-accent text-muted-foreground" :
      "bg-muted/60 text-muted-foreground/70"  // viewer
    )}>
      {role}
    </span>
  );
}

function RoleDropdown({
  currentRole,
  targetUserId,
  isOwner,
  orgId,
  onSuccess,
}: {
  currentRole: string;
  targetUserId: string;
  isOwner: boolean;
  orgId: string;
  onSuccess: () => void;
}) {
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();
  const { activeOrg, setActiveOrg } = useAuthStore();

  const roleMutation = useMutation({
    mutationFn: (role: string) => orgsApi.updateMemberRole(orgId, targetUserId, role).then((r) => r.data),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["org-members", orgId] });
      qc.invalidateQueries({ queryKey: ["orgs"] });
      if (data.role === "owner" && activeOrg?.id === orgId) {
        setActiveOrg({ ...activeOrg, role: "admin" });
      }
      toast.success("Role updated");
      onSuccess();
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(msg || "Failed to update role");
    },
  });

  const availableRoles = ROLES.filter((r) => {
    if (r.value === "owner") return isOwner;
    return true;
  });

  return (
    <DropdownMenu.Root open={open} onOpenChange={setOpen}>
      <DropdownMenu.Trigger asChild>
        <button className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full font-medium bg-accent text-muted-foreground hover:bg-accent/80 transition-colors">
          <RoleBadge role={currentRole} />
          <ChevronDown className="w-2.5 h-2.5 -ml-1" />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          side="bottom"
          align="end"
          sideOffset={4}
          className="z-50 min-w-[200px] rounded-xl border border-border bg-card shadow-xl overflow-hidden p-1"
        >
          {availableRoles.map((r) => (
            <DropdownMenu.Item
              key={r.value}
              className={cn(
                "flex flex-col px-3 py-2 rounded-lg cursor-pointer outline-none transition-colors",
                r.value === currentRole ? "bg-accent/60" : "hover:bg-accent"
              )}
              onClick={() => {
                if (r.value !== currentRole) roleMutation.mutate(r.value);
              }}
            >
              <span className="text-xs font-medium">{r.label}</span>
              <span className="text-[10px] text-muted-foreground">{r.description}</span>
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

export default function OrgSettingsPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const { activeOrg, setActiveOrg } = useAuthStore();
  const [tab, setTab] = useState<Tab>("general");
  const [inviteToken, setInviteToken] = useState<string | null>(null);
  const [inviteExpires, setInviteExpires] = useState<string | null>(null);
  const [copiedOrg, setCopiedOrg] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmLeave, setConfirmLeave] = useState(false);

  const { data: orgs = [] } = useQuery<OrgItem[]>({
    queryKey: ["orgs"],
    queryFn: () => orgsApi.list().then((r) => r.data),
  });

  const currentOrgId = activeOrg?.id ?? orgs[0]?.id;
  const org = orgs.find((o) => o.id === currentOrgId) ?? orgs[0];

  const [form, setForm] = useState({ name: "", icon: "", color: "" });
  const [formInit, setFormInit] = useState(false);

  if (org && !formInit) {
    setForm({ name: org.name, icon: org.icon ?? "", color: org.color ?? PRESET_COLORS[0] });
    setFormInit(true);
  }

  const { data: members = [] } = useQuery<Member[]>({
    queryKey: ["org-members", currentOrgId],
    queryFn: () => orgsApi.members(currentOrgId!).then((r) => r.data),
    enabled: !!currentOrgId,
  });

  // Deletion form: per-category resource counts + which to wipe (rest reassigned).
  const { data: delSummary } = useQuery<DeletionSummary>({
    queryKey: ["org-deletion-summary", currentOrgId],
    queryFn: () => orgsApi.deletionSummary(currentOrgId!).then((r) => r.data),
    enabled: !!currentOrgId && confirmDelete,
  });
  const [wipeSet, setWipeSet] = useState<Set<string>>(new Set());
  const toggleWipe = (key: string) =>
    setWipeSet((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const updateMutation = useMutation({
    mutationFn: () =>
      orgsApi.update(currentOrgId!, { name: form.name, icon: form.icon || undefined, color: form.color || undefined }).then((r) => r.data),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ["orgs"] });
      if (activeOrg) setActiveOrg({ ...activeOrg, name: updated.name, icon: updated.icon, color: updated.color });
      toast.success("Saved");
    },
  });

  const removeMutation = useMutation({
    mutationFn: (userId: string) => orgsApi.removeMember(currentOrgId!, userId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["org-members", currentOrgId] });
      toast.success("Member removed");
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(msg || "Failed to remove member");
    },
  });

  const leaveMutation = useMutation({
    mutationFn: () => orgsApi.leave(currentOrgId!),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["orgs"] });
      setActiveOrg(null);
      toast.success("You have left the organization");
      router.push("/");
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(msg || "Failed to leave organization");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => orgsApi.delete(currentOrgId!, { wipe: [...wipeSet] }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["orgs"] });
      setActiveOrg(null);
      toast.success("Organization deleted");
      router.push("/");
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(msg || "Failed to delete organization");
    },
  });

  const inviteMutation = useMutation({
    mutationFn: () => orgsApi.createInvite(currentOrgId!).then((r) => r.data),
    onSuccess: (data) => {
      setInviteToken(data.token);
      setInviteExpires(data.expires_at);
    },
  });

  const [combinedInviteUrl, setCombinedInviteUrl] = useState<string | null>(null);
  const [copiedCombined, setCopiedCombined] = useState(false);

  const combinedInviteMutation = useMutation({
    mutationFn: async () => {
      const [signupData, orgData] = await Promise.all([
        authApi.createInvite({}).then((r) => r.data),
        orgsApi.createInvite(currentOrgId!).then((r) => r.data),
      ]);
      return { signupToken: signupData.token, orgToken: orgData.token };
    },
    onSuccess: ({ signupToken, orgToken }) => {
      const base = typeof window !== "undefined" ? window.location.origin : "";
      setCombinedInviteUrl(`${base}/register?invite=${signupToken}&join=${orgToken}`);
    },
  });

  const inviteUrl = inviteToken
    ? `${typeof window !== "undefined" ? window.location.origin : ""}/join?token=${inviteToken}`
    : null;

  const copyInvite = () => {
    if (!inviteUrl) return;
    copyToClipboard(inviteUrl);
    setCopiedOrg(true);
    setTimeout(() => setCopiedOrg(false), 2000);
  };

  if (!org) {
    return <div className="flex items-center justify-center h-full text-muted-foreground text-sm">Loading…</div>;
  }

  const isAdmin = org.role === "owner" || org.role === "admin";
  const isOwner = org.role === "owner";
  const currentUserId = members.find((m) => m.role === org.role)?.user_id;

  return (
    <div className="max-w-2xl mx-auto px-6 py-8">
      <div className="flex items-center gap-3 mb-6">
        <div
          className="w-10 h-10 rounded-xl flex items-center justify-center text-xl font-bold text-white"
          style={{ backgroundColor: org.color || PRESET_COLORS[0] }}
        >
          {org.icon || org.name.charAt(0).toUpperCase()}
        </div>
        <div>
          <h1 className="text-lg font-semibold">{org.name}</h1>
          <p className="text-xs text-muted-foreground">{org.member_count} member{org.member_count !== 1 ? "s" : ""} · {org.role}</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 border-b border-border">
        {((isAdmin ? ["general", "members", "groups", "invites"] : ["general", "members", "invites"]) as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "px-3 py-2 text-sm font-medium capitalize border-b-2 transition-colors -mb-px",
              tab === t ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {/* General tab */}
      {tab === "general" && (
        <div className="space-y-5">
          <div>
            <label className="block text-xs font-medium mb-1.5">Icon (emoji)</label>
            <input
              value={form.icon}
              onChange={(e) => setForm((f) => ({ ...f, icon: e.target.value }))}
              placeholder="🚀"
              maxLength={4}
              disabled={!isAdmin}
              className="w-20 text-center text-xl border border-border rounded-lg px-2 py-2 bg-background focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
            />
          </div>

          <div>
            <label className="block text-xs font-medium mb-1.5">Name</label>
            <input
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              disabled={!isAdmin}
              className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
            />
          </div>

          <div>
            <label className="block text-xs font-medium mb-2">Color</label>
            <div className="flex gap-2 items-center">
              {PRESET_COLORS.map((c) => (
                <button
                  key={c}
                  onClick={() => isAdmin && setForm((f) => ({ ...f, color: c }))}
                  className={cn(
                    "w-7 h-7 rounded-full transition-all",
                    form.color === c ? "ring-2 ring-offset-2 ring-foreground scale-110" : "hover:scale-110"
                  )}
                  style={{ backgroundColor: c }}
                />
              ))}
              <input
                type="color"
                value={form.color || "#6366f1"}
                onChange={(e) => isAdmin && setForm((f) => ({ ...f, color: e.target.value }))}
                disabled={!isAdmin}
                className="w-7 h-7 rounded-full cursor-pointer border border-border bg-transparent"
                title="Custom color"
              />
            </div>
          </div>

          {isAdmin && (
            <button
              onClick={() => updateMutation.mutate()}
              disabled={updateMutation.isPending}
              className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
            >
              {updateMutation.isPending ? "Saving…" : "Save changes"}
            </button>
          )}

          {/* Danger zone */}
          {!org.is_personal && (
            <div className="pt-6 mt-6 border-t border-border space-y-4">
              <h3 className="text-sm font-medium text-destructive">Danger zone</h3>

              {/* Leave org — available to non-owners */}
              {!org.is_owner && (
                <div>
                  <p className="text-xs text-muted-foreground mb-2">
                    Leave this organization. You will lose access to all its projects and chats.
                  </p>
                  {!confirmLeave ? (
                    <button
                      onClick={() => setConfirmLeave(true)}
                      className="flex items-center gap-2 px-4 py-2 rounded-lg border border-destructive/40 text-destructive text-sm font-medium hover:bg-destructive/10 transition-colors"
                    >
                      <LogOut className="w-4 h-4" />
                      Leave organization
                    </button>
                  ) : (
                    <div className="p-4 rounded-xl border border-destructive/40 bg-destructive/5 space-y-3">
                      <div className="flex items-start gap-2">
                        <AlertTriangle className="w-4 h-4 text-destructive shrink-0 mt-0.5" />
                        <p className="text-sm text-destructive font-medium">
                          Leave &ldquo;{org.name}&rdquo;? You will lose access immediately.
                        </p>
                      </div>
                      <div className="flex gap-2">
                        <button
                          onClick={() => leaveMutation.mutate()}
                          disabled={leaveMutation.isPending}
                          className="px-3 py-1.5 rounded-lg bg-destructive text-destructive-foreground text-sm font-medium hover:bg-destructive/90 transition-colors disabled:opacity-50"
                        >
                          {leaveMutation.isPending ? "Leaving…" : "Yes, leave"}
                        </button>
                        <button
                          onClick={() => setConfirmLeave(false)}
                          className="px-3 py-1.5 rounded-lg border border-border text-sm hover:bg-accent transition-colors"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Delete org — owner only */}
              {org.is_owner && (
                <div>
                  <p className="text-xs text-muted-foreground mb-2">
                    Permanently delete this organization and all its data. This cannot be undone.
                  </p>
                  {!confirmDelete ? (
                    <button
                      onClick={() => setConfirmDelete(true)}
                      className="flex items-center gap-2 px-4 py-2 rounded-lg border border-destructive/40 text-destructive text-sm font-medium hover:bg-destructive/10 transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                      Delete organization
                    </button>
                  ) : (
                    <div className="p-4 rounded-xl border border-destructive/40 bg-destructive/5 space-y-3">
                      <div className="flex items-start gap-2">
                        <AlertTriangle className="w-4 h-4 text-destructive shrink-0 mt-0.5" />
                        <p className="text-sm text-destructive font-medium">
                          Delete &ldquo;{org.name}&rdquo;? Choose what to delete — anything left unchecked is
                          moved to your personal organization.
                        </p>
                      </div>

                      {/* Per-category wipe / keep */}
                      <div className="rounded-lg border border-border divide-y divide-border overflow-hidden">
                        {delSummary
                          ? Object.entries(delSummary.categories).map(([key, c]) => {
                              const wipe = wipeSet.has(key);
                              return (
                                <label
                                  key={key}
                                  className="flex items-center justify-between gap-3 px-3 py-2 bg-card cursor-pointer hover:bg-accent/40"
                                >
                                  <div className="flex items-center gap-2 min-w-0">
                                    <input
                                      type="checkbox"
                                      checked={wipe}
                                      onChange={() => toggleWipe(key)}
                                      className="accent-destructive"
                                    />
                                    <span className="text-sm truncate">{c.label}</span>
                                    <span className="text-xs text-muted-foreground">({c.count})</span>
                                  </div>
                                  <span className={cn("text-[11px] font-medium", wipe ? "text-destructive" : "text-muted-foreground")}>
                                    {wipe ? "Delete" : "Move to personal"}
                                  </span>
                                </label>
                              );
                            })
                          : <p className="px-3 py-2 text-xs text-muted-foreground">Loading resources…</p>}
                      </div>

                      {delSummary && delSummary.projects > 0 && (
                        <p className="text-xs text-muted-foreground">
                          {delSummary.projects} project{delSummary.projects !== 1 ? "s" : ""} will be moved to your
                          personal organization.
                        </p>
                      )}

                      <div className="flex gap-2">
                        <button
                          onClick={() => deleteMutation.mutate()}
                          disabled={deleteMutation.isPending}
                          className="px-3 py-1.5 rounded-lg bg-destructive text-destructive-foreground text-sm font-medium hover:bg-destructive/90 transition-colors disabled:opacity-50"
                        >
                          {deleteMutation.isPending ? "Deleting…" : "Delete organization"}
                        </button>
                        <button
                          onClick={() => { setConfirmDelete(false); setWipeSet(new Set()); }}
                          className="px-3 py-1.5 rounded-lg border border-border text-sm hover:bg-accent transition-colors"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Members tab */}
      {tab === "members" && (
        <div className="space-y-2">
          {members.map((m) => {
            const isMe = m.user_id === currentUserId;
            // Admins can manage non-owners; owners can manage everyone including admins
            const canManage = isAdmin && !isMe && (m.role !== "owner" || isOwner);
            return (
              <div key={m.user_id} className="flex items-center gap-3 p-3 rounded-xl border border-border bg-card">
                <div className="w-8 h-8 rounded-full bg-accent flex items-center justify-center text-sm font-bold shrink-0">
                  {m.full_name.charAt(0).toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate flex items-center gap-1.5">
                    {m.full_name}
                    {isMe && <span className="text-[10px] text-muted-foreground">(you)</span>}
                  </div>
                  <div className="text-[11px] text-muted-foreground truncate">{m.email}</div>
                </div>

                {canManage ? (
                  <RoleDropdown
                    currentRole={m.role}
                    targetUserId={m.user_id}
                    isOwner={org.is_owner}
                    orgId={currentOrgId!}
                    onSuccess={() => {}}
                  />
                ) : (
                  <RoleBadge role={m.role} />
                )}

                {canManage && (
                  <button
                    onClick={() => removeMutation.mutate(m.user_id)}
                    disabled={removeMutation.isPending}
                    className="p-1 rounded hover:bg-destructive/10 hover:text-destructive text-muted-foreground transition-colors"
                    title="Remove member"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            );
          })}
          {members.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-8">No members yet.</p>
          )}
        </div>
      )}

      {/* Groups tab — admin-managed permission groups */}
      {tab === "groups" && isAdmin && <GroupsTab members={members} />}

      {/* Invites tab */}
      {tab === "invites" && (
        <div className="space-y-5">
          {/* Recommended: combined invite (register + join in one link) */}
          <div className="space-y-3 p-4 rounded-xl border border-primary/20 bg-primary/5">
            <div>
              <p className="text-sm font-medium flex items-center gap-1.5">
                <UserPlus className="w-3.5 h-3.5 text-primary" />
                Invite new teammate <span className="text-[10px] bg-primary/20 text-primary px-1.5 py-0.5 rounded font-medium">Recommended</span>
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                One link handles everything: they register an account and join this org automatically.
              </p>
            </div>
            {isAdmin && (
              <button
                onClick={() => combinedInviteMutation.mutate()}
                disabled={combinedInviteMutation.isPending}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                {combinedInviteMutation.isPending
                  ? <><RefreshCw className="w-4 h-4 animate-spin" />Generating…</>
                  : <><UserPlus className="w-4 h-4" />Generate invite link</>}
              </button>
            )}
            {combinedInviteUrl && (
              <div className="p-3 rounded-xl border border-border bg-card space-y-2">
                <div className="flex items-center gap-2">
                  <input readOnly value={combinedInviteUrl}
                    className="flex-1 text-xs font-mono bg-background border border-border rounded-lg px-3 py-2 focus:outline-none" />
                  <button onClick={() => { copyToClipboard(combinedInviteUrl); setCopiedCombined(true); setTimeout(() => setCopiedCombined(false), 2000); }}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-accent text-sm font-medium hover:bg-accent/80 transition-colors shrink-0">
                    {copiedCombined ? <Check className="w-4 h-4 text-green-400" /> : <Copy className="w-4 h-4" />}
                    {copiedCombined ? "Copied!" : "Copy"}
                  </button>
                </div>
                <p className="text-[10px] text-muted-foreground">Single use · expires in 7 days</p>
              </div>
            )}
          </div>

          {/* For existing users */}
          <div className="space-y-3">
            <div>
              <p className="text-xs font-medium text-muted-foreground">Already have an account?</p>
            </div>
            {isAdmin && (
              <button
                onClick={() => inviteMutation.mutate()}
                disabled={inviteMutation.isPending}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-border bg-card text-xs font-medium hover:border-primary/40 transition-colors disabled:opacity-50"
              >
                {inviteMutation.isPending
                  ? <><RefreshCw className="w-3 h-3 animate-spin" />Generating…</>
                  : "Generate org invite link"}
              </button>
            )}
            {inviteUrl && (
              <div className="p-3 rounded-xl border border-border bg-card space-y-2">
                <div className="flex items-center gap-2">
                  <input readOnly value={inviteUrl}
                    className="flex-1 text-xs font-mono bg-background border border-border rounded-lg px-3 py-2 focus:outline-none" />
                  <button onClick={() => { copyToClipboard(inviteUrl); setCopiedOrg(true); setTimeout(() => setCopiedOrg(false), 2000); }}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-accent text-xs font-medium hover:bg-accent/80 transition-colors shrink-0">
                    {copiedOrg ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
                    {copiedOrg ? "Copied!" : "Copy"}
                  </button>
                </div>
                {inviteExpires && (
                  <p className="text-[10px] text-muted-foreground">
                    Expires {new Date(inviteExpires).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
