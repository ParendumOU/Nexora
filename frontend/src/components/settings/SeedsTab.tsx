"use client";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Loader2, Upload, Download, Package, X, AlertTriangle, CheckCircle2, XCircle } from "lucide-react";

interface SeedCatalogItem {
  type: string;
  key: string;
  name: string;
  description: string;
  category: string;
  source: "builtin" | "custom";
  is_builtin: boolean;
}

interface MissingDep {
  slug: string;
  key: string;
  name: string;
  type: string;
  version: string;
}

interface SeedsTabProps {
  loadingSeeds: boolean;
  seedCatalog: SeedCatalogItem[];
  seedImporting: boolean;
  seedTypeFilter: "all" | "tool" | "skill" | "persona" | "agent";
  onSeedTypeFilter: (t: "all" | "tool" | "skill" | "persona" | "agent") => void;
  onSeedImport: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onExportAllCustom: () => void;
  onDeleteCustomSeed: (item: { type: string; key: string }) => void;
  missingDeps?: MissingDep[];
  installingDeps?: boolean;
  depInstallResults?: { installed: string[]; failed: string[] } | null;
  onInstallDeps?: () => void;
  onDismissDeps?: () => void;
}

function SeedsTab({
  loadingSeeds,
  seedCatalog,
  seedImporting,
  seedTypeFilter,
  onSeedTypeFilter,
  onSeedImport,
  onExportAllCustom,
  onDeleteCustomSeed,
  missingDeps = [],
  installingDeps = false,
  depInstallResults = null,
  onInstallDeps,
  onDismissDeps,
}: SeedsTabProps) {
  return (
    <>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold">Seed Library</h2>
          <p className="text-xs text-muted-foreground mt-0.5 max-w-sm">
            Built-in seeds are bundled with the platform. Custom seeds can be imported via ZIP and exported to share with other instances.
          </p>
        </div>
        <div className="flex gap-2 shrink-0">
          <label className={cn(
            "flex items-center gap-1.5 h-8 px-3 rounded-md border border-input bg-transparent text-xs font-medium cursor-pointer",
            "hover:bg-accent transition-colors",
            seedImporting && "opacity-50 pointer-events-none"
          )}>
            {seedImporting
              ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
              : <Upload className="w-3.5 h-3.5" />}
            Import ZIP
            <input type="file" accept=".zip" className="hidden" onChange={onSeedImport} disabled={seedImporting} />
          </label>
          <Button size="sm" variant="outline" onClick={onExportAllCustom} className="gap-1.5">
            <Download className="w-3.5 h-3.5" />Export Custom
          </Button>
        </div>
      </div>

      {/* Missing deps banner */}
      {missingDeps.length > 0 && !depInstallResults && (
        <div className="border border-amber-800/40 bg-amber-950/20 rounded-xl p-4 space-y-3">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-semibold text-amber-300">Missing dependencies</p>
                <p className="text-xs text-amber-400/80 mt-0.5">
                  This package requires {missingDeps.length} dependenc{missingDeps.length === 1 ? "y" : "ies"} not yet installed on this instance.
                </p>
              </div>
            </div>
            <button onClick={onDismissDeps} className="text-muted-foreground hover:text-foreground transition-colors shrink-0">
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="space-y-1.5">
            {missingDeps.map((dep) => (
              <div key={dep.slug} className="flex items-center gap-2.5 px-3 py-2 bg-amber-950/30 rounded-lg border border-amber-800/30">
                <span className="text-xs font-mono text-amber-300/70 w-14 shrink-0">{dep.type}</span>
                <span className="text-xs font-semibold text-amber-200 flex-1">{dep.name}</span>
                <span className="text-xs text-amber-400/60 font-mono">{dep.version}</span>
              </div>
            ))}
          </div>
          <div className="flex gap-2 pt-1">
            <Button
              size="sm"
              onClick={onInstallDeps}
              disabled={installingDeps}
              className="bg-amber-600 hover:bg-amber-500 text-white border-0 gap-1.5"
            >
              {installingDeps ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
              {installingDeps ? "Installing…" : "Auto-install from Marketplace"}
            </Button>
            <Button size="sm" variant="ghost" onClick={onDismissDeps} className="text-muted-foreground">
              Skip
            </Button>
          </div>
        </div>
      )}

      {/* Dep install results */}
      {depInstallResults && (
        <div className={cn(
          "border rounded-xl p-4 space-y-2",
          depInstallResults.failed.length === 0
            ? "border-emerald-800/40 bg-emerald-950/20"
            : "border-amber-800/40 bg-amber-950/20"
        )}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {depInstallResults.failed.length === 0
                ? <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                : <AlertTriangle className="w-4 h-4 text-amber-400" />}
              <p className="text-sm font-semibold">
                {depInstallResults.installed.length > 0 && `${depInstallResults.installed.length} installed`}
                {depInstallResults.failed.length > 0 && `, ${depInstallResults.failed.length} failed`}
              </p>
            </div>
            <button onClick={onDismissDeps} className="text-muted-foreground hover:text-foreground transition-colors">
              <X className="w-4 h-4" />
            </button>
          </div>
          {depInstallResults.failed.length > 0 && (
            <div className="space-y-1">
              {depInstallResults.failed.map((f, i) => (
                <div key={i} className="flex items-center gap-2 text-xs text-amber-300">
                  <XCircle className="w-3 h-3 shrink-0" />
                  {f}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Seed type filter tabs */}
      {!loadingSeeds && seedCatalog.length > 0 && (
        <div className="flex gap-1 flex-wrap">
          {(["all", "skill", "tool", "persona", "agent"] as const).map((t) => {
            const count = t === "all" ? seedCatalog.length : seedCatalog.filter((s) => s.type === t).length;
            return (
              <button
                key={t}
                onClick={() => onSeedTypeFilter(t)}
                className={cn(
                  "text-xs px-2.5 py-1 rounded-full border transition-colors capitalize",
                  seedTypeFilter === t ? "bg-primary text-primary-foreground border-primary" : "border-border hover:bg-accent"
                )}
              >
                {t === "all" ? "All" : `${t}s`} ({count})
              </button>
            );
          })}
        </div>
      )}

      {loadingSeeds ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />Loading catalog…
        </div>
      ) : seedCatalog.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-14 border border-dashed border-border rounded-xl text-center max-w-md">
          <Package className="w-8 h-8 text-muted-foreground/40" />
          <div>
            <p className="text-sm font-medium">No seeds found</p>
            <p className="text-xs text-muted-foreground mt-0.5">Seeds are loaded from <code className="text-[10px] bg-accent px-1 rounded">src/seeds/</code> on startup</p>
          </div>
        </div>
      ) : (
        <div className="space-y-6 max-w-2xl">
          {(["tool", "skill", "persona", "agent"] as const).filter((t) => seedTypeFilter === "all" || seedTypeFilter === t).map((seedType) => {
            const items = seedCatalog.filter((s) => s.type === seedType);
            if (!items.length) return null;
            const builtins = items.filter((i) => i.source === "builtin");
            const customs = items.filter((i) => i.source === "custom");
            return (
              <div key={seedType}>
                <div className="flex items-center gap-2 mb-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    {seedType}s
                  </h3>
                  <span className="text-xs text-muted-foreground/60">{items.length} total</span>
                  {customs.length > 0 && (
                    <span className="text-[10px] text-primary font-medium ml-auto">{customs.length} custom</span>
                  )}
                </div>
                <div className="space-y-1 border-l border-border pl-4">
                  {builtins.map((item) => (
                    <div key={item.key} className="flex items-center gap-3 px-3 py-2 bg-card border border-border rounded-lg">
                      <span className="text-xs font-mono text-muted-foreground w-4 shrink-0">⬡</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium truncate">{item.name}</p>
                        {item.description && (
                          <p className="text-[10px] text-muted-foreground truncate">{item.description}</p>
                        )}
                      </div>
                      {item.category && (
                        <span className="text-[10px] text-muted-foreground/60 shrink-0">{item.category}</span>
                      )}
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-accent text-muted-foreground shrink-0">builtin</span>
                    </div>
                  ))}
                  {customs.map((item) => (
                    <div key={item.key} className="flex items-center gap-3 px-3 py-2 bg-card border border-primary/20 rounded-lg">
                      <span className="text-xs font-mono text-primary w-4 shrink-0">✦</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium truncate">{item.name}</p>
                        {item.description && (
                          <p className="text-[10px] text-muted-foreground truncate">{item.description}</p>
                        )}
                      </div>
                      {item.category && (
                        <span className="text-[10px] text-muted-foreground/60 shrink-0">{item.category}</span>
                      )}
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary shrink-0">custom</span>
                      <button
                        onClick={() => onDeleteCustomSeed({ type: item.type, key: item.key })}
                        className="p-1 rounded hover:bg-destructive/10 hover:text-destructive transition-colors text-muted-foreground shrink-0"
                        title="Delete custom seed"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div className="p-4 bg-accent/20 border border-border rounded-lg space-y-1 max-w-2xl">
        <p className="text-xs font-semibold flex items-center gap-1.5">
          <Package className="w-3.5 h-3.5 text-primary" />ZIP format
        </p>
        <p className="text-xs text-muted-foreground leading-relaxed">
          Export to get a ZIP with your custom seeds. To add new seeds, structure the ZIP as{" "}
          <code className="text-[10px] bg-accent px-1 rounded">tool/custom/&lt;key&gt;/tool.json</code> and import it here.
          Built-in seeds are part of the source code and cannot be deleted from the UI.
        </p>
      </div>
    </>
  );
}

export default SeedsTab;
