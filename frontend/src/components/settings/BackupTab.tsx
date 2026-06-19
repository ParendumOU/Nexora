"use client";

import { useState } from "react";
import { Database, Download, Upload, RefreshCw, AlertTriangle, ShieldAlert, ArrowRightLeft } from "lucide-react";
import toast from "react-hot-toast";
import { platformBackupApi } from "@/lib/api";
import { useAuthStore } from "@/store/auth";

type ExportStatus = "idle" | "running" | "done" | "failed";

export default function BackupTab() {
  const isSuperuser = useAuthStore((s) => s.user?.is_superuser);

  const [includeVectors, setIncludeVectors] = useState(false);
  const [exportStatus, setExportStatus] = useState<ExportStatus>("idle");
  const [jobId, setJobId] = useState<string | null>(null);

  const [importMode, setImportMode] = useState<"skip" | "overwrite">("skip");
  const [reembed, setReembed] = useState(true);
  const [importing, setImporting] = useState(false);
  const [importSummary, setImportSummary] = useState<Record<string, unknown> | null>(null);

  const [targetUrl, setTargetUrl] = useState("");
  const [targetToken, setTargetToken] = useState("");
  const [migrateVectors, setMigrateVectors] = useState(false);
  const [migrateStatus, setMigrateStatus] = useState<ExportStatus>("idle");
  const [migrateSummary, setMigrateSummary] = useState<Record<string, unknown> | null>(null);

  if (!isSuperuser) {
    return (
      <div className="max-w-2xl">
        <div className="rounded-xl border border-border bg-card p-6 flex items-start gap-3">
          <ShieldAlert className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
          <div>
            <h2 className="text-sm font-semibold">Superuser only</h2>
            <p className="text-xs text-muted-foreground mt-1">
              Full-platform backup and restore is restricted to superusers.
            </p>
          </div>
        </div>
      </div>
    );
  }

  async function runExport() {
    setExportStatus("running");
    setJobId(null);
    try {
      const { data } = await platformBackupApi.startExport({
        scope: "instance",
        include_vectors: includeVectors,
      });
      const id = data.job_id as string;
      setJobId(id);
      // Poll until done.
      for (;;) {
        await new Promise((r) => setTimeout(r, 3000));
        const { data: s } = await platformBackupApi.status(id);
        if (s.status === "done") {
          const blob = await platformBackupApi.download(id);
          const url = URL.createObjectURL(new Blob([blob.data], { type: "application/zip" }));
          const a = document.createElement("a");
          a.href = url;
          a.download = `nexora-backup-instance.zip`;
          a.click();
          URL.revokeObjectURL(url);
          setExportStatus("done");
          toast.success("Backup ready — download started");
          return;
        }
        if (s.status === "failed") {
          setExportStatus("failed");
          toast.error(`Export failed: ${s.error ?? "unknown error"}`);
          return;
        }
      }
    } catch {
      setExportStatus("failed");
      toast.error("Could not start export");
    }
  }

  async function handleImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    setImportSummary(null);
    try {
      const { data } = await platformBackupApi.import(file, { mode: importMode, reembed });
      setImportSummary(data.summary);
      toast.success("Restore complete");
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Restore failed";
      toast.error(detail);
    } finally {
      setImporting(false);
      e.target.value = "";
    }
  }

  async function runMigrate() {
    const url = targetUrl.trim().replace(/\/+$/, "");
    if (!url || !targetToken.trim()) {
      toast.error("Target URL and token are required");
      return;
    }
    setMigrateStatus("running");
    setMigrateSummary(null);
    try {
      const { data } = await platformBackupApi.migrate({
        target_url: url,
        target_token: targetToken.trim(),
        scope: "instance",
        include_vectors: migrateVectors,
      });
      const id = data.job_id as string;
      for (;;) {
        await new Promise((r) => setTimeout(r, 3000));
        const { data: s } = await platformBackupApi.status(id);
        if (s.status === "done") {
          setMigrateStatus("done");
          setMigrateSummary(s.summary ?? null);
          toast.success("Migration complete");
          return;
        }
        if (s.status === "failed") {
          setMigrateStatus("failed");
          toast.error(`Migration failed: ${s.error ?? "unknown error"}`);
          return;
        }
      }
    } catch (err: unknown) {
      setMigrateStatus("failed");
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Could not start migration";
      toast.error(detail);
    }
  }

  return (
    <div className="max-w-2xl space-y-8">
      <div>
        <h2 className="text-sm font-semibold flex items-center gap-2">
          <Database className="w-4 h-4" /> Platform backup
        </h2>
        <p className="text-xs text-muted-foreground mt-0.5">
          Export the entire instance — every org, agent, chat, knowledge base, provider, and
          custom seed — into one portable ZIP, and restore it into a fresh instance.
        </p>
      </div>

      {/* Export */}
      <section className="rounded-xl border border-border bg-card p-5 space-y-4">
        <h3 className="text-xs font-medium text-foreground">Export</h3>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={includeVectors}
            onChange={(e) => setIncludeVectors(e.target.checked)}
            className="accent-primary"
          />
          Include embedding vectors (larger file; only useful when the target uses the same
          embedding model — otherwise vectors are regenerated on import)
        </label>
        <button
          onClick={runExport}
          disabled={exportStatus === "running"}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-white text-xs font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
        >
          {exportStatus === "running" ? (
            <RefreshCw className="w-4 h-4 animate-spin" />
          ) : (
            <Download className="w-4 h-4" />
          )}
          {exportStatus === "running" ? "Building backup…" : "Export full instance"}
        </button>
        {exportStatus === "running" && jobId && (
          <p className="text-[11px] text-muted-foreground">Job {jobId} — this may take a while for large instances.</p>
        )}
      </section>

      {/* Migrate (direct push to another instance) */}
      <section className="rounded-xl border border-border bg-card p-5 space-y-4">
        <h3 className="text-xs font-medium text-foreground flex items-center gap-2">
          <ArrowRightLeft className="w-4 h-4" /> Migrate to another instance
        </h3>
        <p className="text-[11px] text-muted-foreground">
          Move everything from this instance into a new one in a single step — e.g. upgrading
          from the free community core to a licensed NexoraCloud deployment without losing your
          orgs, agents, chats, knowledge bases, or settings. This server builds a backup and
          pushes it straight into the target&apos;s restore endpoint (mode: skip existing).
        </p>
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
          <p className="text-[11px] text-muted-foreground">
            The target must run the same <code>ENCRYPTION_KEY</code> (encrypted secrets ship
            as-is) and the token must belong to a <strong>superuser on the target</strong>.
            User passwords and per-device pairings don&apos;t transfer — users reset password /
            re-pair on the new instance.
          </p>
        </div>
        <div className="space-y-3">
          <label className="block text-xs text-muted-foreground">
            Target instance URL
            <input
              type="url"
              value={targetUrl}
              onChange={(e) => setTargetUrl(e.target.value)}
              placeholder="https://cloud.example.com"
              className="mt-1 w-full bg-background border border-border rounded px-2 py-1.5 text-xs"
            />
          </label>
          <label className="block text-xs text-muted-foreground">
            Target superuser token (access JWT or <code>nxr_</code> API key)
            <input
              type="password"
              value={targetToken}
              onChange={(e) => setTargetToken(e.target.value)}
              placeholder="nxr_… or a superuser access token"
              className="mt-1 w-full bg-background border border-border rounded px-2 py-1.5 text-xs font-mono"
            />
          </label>
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={migrateVectors}
              onChange={(e) => setMigrateVectors(e.target.checked)}
              className="accent-primary"
            />
            Ship embedding vectors verbatim (only if the target uses the same embedding model;
            otherwise they&apos;re re-embedded on arrival)
          </label>
        </div>
        <button
          onClick={runMigrate}
          disabled={migrateStatus === "running"}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-white text-xs font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
        >
          {migrateStatus === "running" ? (
            <RefreshCw className="w-4 h-4 animate-spin" />
          ) : (
            <ArrowRightLeft className="w-4 h-4" />
          )}
          {migrateStatus === "running" ? "Migrating…" : "Migrate now"}
        </button>
        {migrateSummary && (
          <div className="text-[11px] text-muted-foreground border border-border rounded-lg p-3 max-h-48 overflow-auto">
            <pre className="whitespace-pre-wrap">{JSON.stringify(migrateSummary, null, 2)}</pre>
          </div>
        )}
      </section>

      {/* Import */}
      <section className="rounded-xl border border-border bg-card p-5 space-y-4">
        <h3 className="text-xs font-medium text-foreground">Restore</h3>
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
          <p className="text-[11px] text-muted-foreground">
            The target instance must share the source <code>ENCRYPTION_KEY</code> — encrypted
            secrets (provider keys, tokens) are shipped as-is and import is rejected on key
            mismatch. Restore into a freshly-migrated instance.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            Mode
            <select
              value={importMode}
              onChange={(e) => setImportMode(e.target.value as "skip" | "overwrite")}
              className="bg-background border border-border rounded px-2 py-1 text-xs"
            >
              <option value="skip">skip existing</option>
              <option value="overwrite">overwrite existing</option>
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={reembed}
              onChange={(e) => setReembed(e.target.checked)}
              className="accent-primary"
            />
            Re-embed knowledge/memory if vectors absent
          </label>
        </div>

        <label className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-border text-xs font-medium hover:bg-muted/50 transition-colors cursor-pointer w-fit">
          {importing ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
          {importing ? "Restoring…" : "Choose backup ZIP"}
          <input type="file" accept=".zip" onChange={handleImport} disabled={importing} className="hidden" />
        </label>

        {importSummary && (
          <div className="text-[11px] text-muted-foreground border border-border rounded-lg p-3 max-h-48 overflow-auto">
            <pre className="whitespace-pre-wrap">{JSON.stringify(importSummary, null, 2)}</pre>
          </div>
        )}
      </section>
    </div>
  );
}
