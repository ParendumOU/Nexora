"use client";
import { useState } from "react";
import { Bell, X, CheckCheck, ExternalLink } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { notificationsApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import Link from "next/link";

interface Notif {
  id: string;
  type: string;
  title: string;
  body: string | null;
  link: string | null;
  read: boolean;
  created_at: string;
}

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();

  const { data: notifications = [] } = useQuery<Notif[]>({
    queryKey: ["notifications"],
    queryFn: () => notificationsApi.list().then((r) => r.data),
    // Pushed live via the user WebSocket (useUserSocket); long fallback only.
    refetchInterval: 120_000,
    staleTime: 20_000,
  });

  const unread = notifications.filter((n) => !n.read).length;

  const markRead = useMutation({
    mutationFn: (id: string) => notificationsApi.markRead(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });

  const markAll = useMutation({
    mutationFn: () => notificationsApi.markAllRead(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });

  const dismiss = useMutation({
    mutationFn: (id: string) => notificationsApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });

  function handleOpen(notif: Notif) {
    if (!notif.read) markRead.mutate(notif.id);
  }

  return (
    <DropdownMenu.Root open={open} onOpenChange={setOpen}>
      <DropdownMenu.Trigger asChild>
        <button
          className={cn(
            "relative w-8 h-8 flex items-center justify-center rounded-md transition-colors shrink-0",
            open ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground hover:bg-accent"
          )}
          title="Notifications"
        >
          <Bell className="w-4 h-4" />
          {unread > 0 && (
            <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 rounded-full bg-primary text-primary-foreground text-[10px] font-bold flex items-center justify-center leading-none pointer-events-none">
              {unread > 99 ? "99+" : unread}
            </span>
          )}
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          side="bottom"
          align="start"
          sideOffset={8}
          className="z-[200] w-80 bg-card border border-border rounded-xl shadow-xl flex flex-col max-h-[480px] overflow-hidden"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
            <span className="text-sm font-semibold">Notifications</span>
            {unread > 0 && (
              <button
                onClick={() => markAll.mutate()}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                <CheckCheck className="w-3.5 h-3.5" />
                Mark all read
              </button>
            )}
          </div>

          {/* List */}
          <div className="overflow-y-auto flex-1">
            {notifications.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                No notifications yet
              </div>
            ) : (
              notifications.map((n) => (
                <div
                  key={n.id}
                  className={cn(
                    "group flex gap-3 px-4 py-3 border-b border-border/50 last:border-0 hover:bg-accent/40 transition-colors cursor-pointer",
                    !n.read && "bg-primary/5"
                  )}
                  onClick={() => handleOpen(n)}
                >
                  <div className="pt-1 shrink-0">
                    <span className={cn(
                      "block w-2 h-2 rounded-full mt-0.5",
                      !n.read ? "bg-primary" : "bg-transparent"
                    )} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium leading-snug truncate">{n.title}</p>
                    {n.body && (
                      <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{n.body}</p>
                    )}
                    <p className="text-[10px] text-muted-foreground/60 mt-1">
                      {new Date(n.created_at).toLocaleString()}
                    </p>
                    {n.link && (
                      <Link
                        href={n.link}
                        onClick={(e) => e.stopPropagation()}
                        className="inline-flex items-center gap-1 text-[11px] text-primary hover:underline mt-1"
                      >
                        <ExternalLink className="w-3 h-3" />
                        Open
                      </Link>
                    )}
                  </div>
                  <button
                    onClick={(e) => { e.stopPropagation(); dismiss.mutate(n.id); }}
                    className="shrink-0 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-foreground transition-all"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))
            )}
          </div>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
