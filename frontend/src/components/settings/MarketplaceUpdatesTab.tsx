"use client";

import { useEffect, useState, useCallback } from "react";
import { RefreshCw, ArrowUpCircle, Check, Lock, Package } from "lucide-react";
import toast from "react-hot-toast";
import { marketplaceApi, type InstalledPackageUpdate } from "@/lib/api";

const TYPE_LABEL: Record<string, string> = {
  skill: "Skill", tool: "Tool", persona: "Persona", agent: "Agent",
};

export default function MarketplaceUpdatesTab() {
  const [items, setItems] = useState<InstalledPackageUpdate[]>([]);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [applying, setApplying] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await marketplaceApi.listUpdates();
      setItems(res.data.items);
    } catch {
      toast.error("Failed to load installed packages");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const check = async () => {
    setChecking(true);
    try {
      const res = await marketplaceApi.checkUpdates();
      await load();
      toast.success(res.data.updates_available > 0
        ? `${res.data.updates_available} update${res.data.updates_available !== 1 ? "s" : ""} available`
        : "Everything is up to date");
    } catch {
      toast.error("Update check failed");
    } finally {
      setChecking(false);
    }
  };

  const apply = async (it: InstalledPackageUpdate) => {
    setApplying(it.id);
    try {
      const res = await marketplaceApi.applyUpdate(it.id);
      toast.success(`${it.name} updated to v${res.data.version}`);
      await load();
    } catch (e: unknown) {
      const err = e as { response?: { status?: number; data?: { detail?: string } } };
      if (err.response?.status === 402) {
        toast.error("This paid package needs a valid purchase/license to update");
      } else {
        toast.error(err.response?.data?.detail || `Failed to update ${it.name}`);
      }
    } finally {
      setApplying(null);
    }
  };

  const updatable = items.filter((i) => i.update_available);

  const applyAll = async () => {
    for (const it of updatable) await apply(it);
  };

  return (
    <div className="space-y-5 max-w-3xl">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Installed from marketplace</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Skills, tools, personas, and agents installed from a marketplace. Check for newer
            versions and update them here.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {updatable.length > 1 && (
            <button
              onClick={applyAll}
              disabled={!!applying}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary text-primary-foreground px-3 py-1.5 text-xs font-medium disabled:opacity-50"
            >
              <ArrowUpCircle className="h-3.5 w-3.5" />
              Update all ({updatable.length})
            </button>
          )}
          <button
            onClick={check}
            disabled={checking}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${checking ? "animate-spin" : ""}`} />
            {checking ? "Checking…" : "Check for updates"}
          </button>
        </div>
      </div>

      {loading ? (
        <div className="py-12 flex justify-center">
          <div className="h-6 w-6 rounded-full border-2 border-primary border-t-transparent animate-spin" />
        </div>
      ) : items.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground">
          <Package className="h-9 w-9 mx-auto mb-3 opacity-30" />
          <p className="text-sm">No marketplace packages installed yet.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {items.map((it) => (
            <div
              key={it.id}
              className="flex items-center gap-3 rounded-lg border border-border p-3"
            >
              <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-accent text-muted-foreground shrink-0 w-16 text-center">
                {TYPE_LABEL[it.item_type] ?? it.item_type}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium truncate">{it.name}</span>
                  {it.pricing_type !== "free" && (
                    <span title="Paid package" className="text-emerald-400"><Lock className="h-3 w-3" /></span>
                  )}
                </div>
                <p className="text-xs text-muted-foreground font-mono mt-0.5">
                  v{it.installed_version}
                  {it.update_available && (
                    <span className="text-emerald-400"> → v{it.available_version}</span>
                  )}
                </p>
              </div>
              {it.update_available ? (
                <button
                  onClick={() => apply(it)}
                  disabled={applying === it.id}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 px-3 py-1.5 text-xs font-medium hover:bg-emerald-500/25 disabled:opacity-50 shrink-0"
                >
                  <ArrowUpCircle className="h-3.5 w-3.5" />
                  {applying === it.id ? "Updating…" : "Update"}
                </button>
              ) : (
                <span className="inline-flex items-center gap-1 text-xs text-muted-foreground shrink-0">
                  <Check className="h-3.5 w-3.5 text-emerald-400" />
                  Up to date
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
