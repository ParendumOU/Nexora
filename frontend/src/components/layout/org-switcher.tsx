"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Check, ChevronDown, Plus, Settings, X, Lock } from "lucide-react";
import { cn } from "@/lib/utils";
import { orgsApi } from "@/lib/api";
import { useAuthStore, ActiveOrg } from "@/store/auth";
import toast from "react-hot-toast";

const PRESET_COLORS = ["#6366f1", "#8b5cf6", "#ec4899", "#f59e0b", "#10b981", "#3b82f6"];

export interface OrgItem {
  id: string;
  name: string;
  icon: string | null;
  color: string | null;
  role: string;
  is_owner: boolean;
  is_personal: boolean;
  member_count: number;
}

export function OrgChip({ org, size = "md" }: { org: { name: string; icon: string | null; color: string | null }; size?: "sm" | "md" }) {
  const bg = org.color || "#6366f1";
  const initial = org.name.charAt(0).toUpperCase();
  const sz = size === "sm" ? "w-5 h-5 text-[10px]" : "w-7 h-7 text-sm";
  return (
    <div
      className={cn("rounded-lg flex items-center justify-center font-bold text-white shrink-0", sz)}
      style={{ backgroundColor: bg }}
    >
      {org.icon || initial}
    </div>
  );
}

function CreateOrgForm({ onClose, onCreated }: { onClose: () => void; onCreated: (org: OrgItem) => void }) {
  const [name, setName] = useState("");
  const [icon, setIcon] = useState("");
  const [color, setColor] = useState(PRESET_COLORS[0]);
  const qc = useQueryClient();

  const createMutation = useMutation({
    mutationFn: () => orgsApi.create({ name, icon: icon || null, color }).then((r) => r.data),
    onSuccess: (org) => {
      qc.invalidateQueries({ queryKey: ["orgs"] });
      onCreated(org);
      toast.success(`Organization "${org.name}" created`);
    },
    onError: () => toast.error("Failed to create organization"),
  });

  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-semibold text-foreground">New organization</span>
        <button onClick={onClose} className="p-0.5 rounded hover:bg-accent transition-colors text-muted-foreground">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="flex gap-2 items-center">
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center text-white font-bold text-sm shrink-0"
          style={{ backgroundColor: color }}
        >
          {icon || (name.charAt(0).toUpperCase() || "?")}
        </div>
        <input
          value={icon}
          onChange={(e) => setIcon(e.target.value)}
          placeholder="Emoji"
          maxLength={4}
          className="w-14 text-center border border-border rounded-lg px-1 py-1 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-primary"
        />
      </div>

      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Organization name"
        className="w-full border border-border rounded-lg px-2 py-1.5 text-xs bg-background focus:outline-none focus:ring-1 focus:ring-primary"
        onKeyDown={(e) => e.key === "Enter" && name.trim() && createMutation.mutate()}
      />

      <div className="flex gap-1.5 flex-wrap">
        {PRESET_COLORS.map((c) => (
          <button
            key={c}
            onClick={() => setColor(c)}
            className={cn(
              "w-5 h-5 rounded-full transition-all",
              color === c ? "ring-2 ring-offset-1 ring-foreground scale-110" : "hover:scale-110"
            )}
            style={{ backgroundColor: c }}
          />
        ))}
      </div>

      <button
        onClick={() => createMutation.mutate()}
        disabled={!name.trim() || createMutation.isPending}
        className="w-full py-1.5 rounded-lg bg-primary text-primary-foreground text-xs font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
      >
        {createMutation.isPending ? "Creating…" : "Create"}
      </button>
    </div>
  );
}

export function OrgSwitcher({ collapsed }: { collapsed: boolean }) {
  const router = useRouter();
  const qc = useQueryClient();
  const { activeOrg, setActiveOrg, switchOrg: storeSwitch } = useAuthStore();
  const [showCreate, setShowCreate] = useState(false);
  const [open, setOpen] = useState(false);

  const { data: orgs = [] } = useQuery<OrgItem[]>({
    queryKey: ["orgs"],
    queryFn: () => orgsApi.list().then((r) => r.data),
  });

  useEffect(() => {
    if (orgs.length === 0) return;
    if (!activeOrg) {
      const first = orgs[0];
      setActiveOrg({ id: first.id, name: first.name, icon: first.icon, color: first.color, role: first.role, is_personal: first.is_personal });
    }
  }, [orgs, activeOrg, setActiveOrg]);

  const switchMutation = useMutation({
    mutationFn: (org: OrgItem) => orgsApi.switchOrg(org.id).then((r) => r.data),
    onSuccess: async (data, org) => {
      storeSwitch(
        { access_token: data.access_token, refresh_token: data.refresh_token },
        { id: org.id, name: org.name, icon: org.icon, color: org.color, role: org.role, is_personal: org.is_personal }
      );
      setOpen(false);
      // Force immediate refetch of all active queries with new token
      await qc.invalidateQueries();
      qc.refetchQueries({ type: "active" });
    },
  });

  const current = activeOrg
    ? (orgs.find((o) => o.id === activeOrg.id) ?? orgs[0])
    : orgs[0];

  if (!current) {
    return (
      <div className={cn("px-2 py-1.5", collapsed && "flex justify-center")}>
        <div className="w-7 h-7 rounded-lg bg-accent animate-pulse" />
      </div>
    );
  }

  const handleCreated = (newOrg: OrgItem) => {
    setShowCreate(false);
    setOpen(false);
  };

  if (collapsed) {
    return (
      <DropdownMenu.Root open={open} onOpenChange={setOpen}>
        <DropdownMenu.Trigger asChild>
          <button className="flex justify-center w-full px-1 py-1.5 hover:bg-sidebar-accent/60 rounded-lg transition-colors">
            <OrgChip org={current} />
          </button>
        </DropdownMenu.Trigger>
        <OrgDropdownContent
          orgs={orgs}
          current={current}
          showCreate={showCreate}
          onShowCreate={() => setShowCreate(true)}
          onHideCreate={() => setShowCreate(false)}
          onCreated={handleCreated}
          onSwitch={(o) => switchMutation.mutate(o)}
          onSettings={() => { setOpen(false); router.push("/org"); }}
          side="right"
        />
      </DropdownMenu.Root>
    );
  }

  return (
    <DropdownMenu.Root open={open} onOpenChange={setOpen}>
      <DropdownMenu.Trigger asChild>
        <button className="flex items-center gap-2 w-full px-2 py-1.5 rounded-lg hover:bg-sidebar-accent/60 transition-colors group">
          <OrgChip org={current} />
          <div className="flex-1 min-w-0 text-left">
            <div className="text-xs font-semibold truncate text-sidebar-foreground">{current.name}</div>
            <div className="text-[10px] text-muted-foreground capitalize flex items-center gap-1">
              {current.role}
              {current.is_personal && <Lock className="w-2.5 h-2.5 opacity-60" />}
            </div>
          </div>
          <ChevronDown className="w-3.5 h-3.5 text-muted-foreground shrink-0 group-hover:text-foreground transition-colors" />
        </button>
      </DropdownMenu.Trigger>
      <OrgDropdownContent
        orgs={orgs}
        current={current}
        showCreate={showCreate}
        onShowCreate={() => setShowCreate(true)}
        onHideCreate={() => setShowCreate(false)}
        onCreated={handleCreated}
        onSwitch={(o) => switchMutation.mutate(o)}
        onSettings={() => { setOpen(false); router.push("/org"); }}
        side="bottom"
      />
    </DropdownMenu.Root>
  );
}

function OrgDropdownContent({
  orgs, current, showCreate, onShowCreate, onHideCreate, onCreated,
  onSwitch, onSettings, side,
}: {
  orgs: OrgItem[];
  current: OrgItem;
  showCreate: boolean;
  onShowCreate: () => void;
  onHideCreate: () => void;
  onCreated: (org: OrgItem) => void;
  onSwitch: (o: OrgItem) => void;
  onSettings: () => void;
  side: "right" | "bottom";
}) {
  return (
    <DropdownMenu.Portal>
      <DropdownMenu.Content
        side={side}
        align="start"
        sideOffset={4}
        className="z-50 min-w-[240px] rounded-xl border border-border bg-card shadow-xl overflow-hidden"
        onInteractOutside={showCreate ? (e) => e.preventDefault() : undefined}
      >
        {showCreate ? (
          <CreateOrgForm onClose={onHideCreate} onCreated={onCreated} />
        ) : (
          <div className="p-1.5">
            <div className="px-2 py-1 text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">
              Organizations
            </div>

            {orgs.map((org) => (
              <DropdownMenu.Item
                key={org.id}
                className="flex items-center gap-2.5 px-2 py-2 rounded-lg cursor-pointer hover:bg-accent outline-none transition-colors"
                onClick={() => org.id !== current.id && onSwitch(org)}
              >
                <OrgChip org={org} size="sm" />
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-medium truncate flex items-center gap-1">
                    {org.name}
                    {org.is_personal && <span title="Personal org"><Lock className="w-2.5 h-2.5 text-muted-foreground shrink-0" /></span>}
                  </div>
                  <div className="text-[10px] text-muted-foreground">{org.member_count} member{org.member_count !== 1 ? "s" : ""}</div>
                </div>
                {org.id === current.id && <Check className="w-3.5 h-3.5 text-primary shrink-0" />}
              </DropdownMenu.Item>
            ))}

            <DropdownMenu.Separator className="my-1 border-t border-border" />

            <DropdownMenu.Item
              className="flex items-center gap-2 px-2 py-1.5 rounded-lg cursor-pointer hover:bg-accent outline-none transition-colors text-xs"
              onClick={onShowCreate}
            >
              <Plus className="w-3.5 h-3.5 text-primary" />
              <span>New organization</span>
            </DropdownMenu.Item>

            <DropdownMenu.Item
              className="flex items-center gap-2 px-2 py-1.5 rounded-lg cursor-pointer hover:bg-accent outline-none transition-colors text-xs text-muted-foreground"
              onClick={onSettings}
            >
              <Settings className="w-3.5 h-3.5" />
              Organization settings
            </DropdownMenu.Item>
          </div>
        )}
      </DropdownMenu.Content>
    </DropdownMenu.Portal>
  );
}
