"use client";
import { use, useState, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { knowledgeBasesApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Loader2, ChevronLeft, BookOpen, Upload, Link as LinkIcon,
  Trash2, FileText, Globe, AlertCircle, CheckCircle2, Clock, Settings2, Save,
} from "lucide-react";
import { cn } from "@/lib/utils";
import toast from "react-hot-toast";

interface KnowledgeBase {
  id: string;
  org_id: string;
  project_id: string | null;
  name: string;
  description: string | null;
  chunk_strategy: string;
  chunk_size: number;
  chunk_overlap: number;
  file_count: number;
}

interface KnowledgeFile {
  id: string;
  kb_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  status: string;
  chunk_count: number;
  error: string | null;
  source_url: string | null;
}

const STATUS_BADGE: Record<string, { label: string; cls: string; icon: React.ElementType }> = {
  pending:    { label: "Pending",    cls: "bg-amber-500/10 text-amber-400 border-amber-500/20",   icon: Clock },
  processing: { label: "Processing", cls: "bg-blue-500/10 text-blue-400 border-blue-500/20",      icon: Loader2 },
  ready:      { label: "Ready",      cls: "bg-green-500/10 text-green-400 border-green-500/20",   icon: CheckCircle2 },
  error:      { label: "Error",      cls: "bg-red-500/10 text-red-400 border-red-500/20",         icon: AlertCircle },
};

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

// ─── Chunking config ──────────────────────────────────────────────────────────

const STRATEGY_LABELS: Record<string, { label: string; description: string }> = {
  fixed:     { label: "Fixed",     description: "Split by character count with overlap" },
  sentence:  { label: "Sentence",  description: "Split on sentence boundaries (.!?)" },
  paragraph: { label: "Paragraph", description: "Split on double newlines (\\n\\n)" },
};

function ChunkingConfigPanel({ kb }: { kb: KnowledgeBase }) {
  const qc = useQueryClient();
  const [strategy, setStrategy] = useState(kb.chunk_strategy);
  const [chunkSize, setChunkSize] = useState(kb.chunk_size);
  const [chunkOverlap, setChunkOverlap] = useState(kb.chunk_overlap);
  const [saving, setSaving] = useState(false);

  const isDirty =
    strategy !== kb.chunk_strategy ||
    chunkSize !== kb.chunk_size ||
    chunkOverlap !== kb.chunk_overlap;

  const maxOverlap = Math.floor(chunkSize / 2);
  const effectiveOverlap = Math.min(chunkOverlap, maxOverlap);

  const handleSave = async () => {
    setSaving(true);
    try {
      await knowledgeBasesApi.update(kb.id, {
        chunk_strategy: strategy,
        chunk_size: chunkSize,
        chunk_overlap: effectiveOverlap,
      });
      toast.success("Chunking config saved");
      qc.invalidateQueries({ queryKey: ["knowledge-base", kb.id] });
      qc.invalidateQueries({ queryKey: ["knowledge-bases"] });
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } };
      toast.error(e.response?.data?.detail || "Failed to save chunking config");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2.5 bg-accent/10 border-b border-border">
        <Settings2 className="w-3.5 h-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Chunking Strategy</span>
      </div>

      <div className="p-4 space-y-4">
        {/* Strategy selector */}
        <div className="space-y-1.5">
          <label className="text-xs text-muted-foreground font-medium">Strategy</label>
          <div className="grid grid-cols-3 gap-2">
            {Object.entries(STRATEGY_LABELS).map(([key, { label, description }]) => (
              <button
                key={key}
                onClick={() => setStrategy(key)}
                className={cn(
                  "flex flex-col gap-0.5 px-3 py-2.5 rounded-lg border text-left transition-colors",
                  strategy === key
                    ? "border-primary bg-primary/10 text-foreground"
                    : "border-border hover:border-border/80 hover:bg-accent/20 text-muted-foreground"
                )}
              >
                <span className="text-xs font-semibold">{label}</span>
                <span className="text-[10px] leading-tight opacity-70">{description}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Chunk size slider */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label className="text-xs text-muted-foreground font-medium">Chunk Size</label>
            <span className="text-xs font-mono text-foreground">{chunkSize} chars</span>
          </div>
          <input
            type="range"
            min={64}
            max={2048}
            step={64}
            value={chunkSize}
            onChange={(e) => {
              const newSize = Number(e.target.value);
              setChunkSize(newSize);
              if (chunkOverlap > Math.floor(newSize / 2)) {
                setChunkOverlap(Math.floor(newSize / 2));
              }
            }}
            className="w-full accent-primary"
          />
          <div className="flex justify-between text-[10px] text-muted-foreground">
            <span>64</span>
            <span>2048</span>
          </div>
        </div>

        {/* Overlap slider */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label className="text-xs text-muted-foreground font-medium">Chunk Overlap</label>
            <span className="text-xs font-mono text-foreground">{effectiveOverlap} chars</span>
          </div>
          <input
            type="range"
            min={0}
            max={maxOverlap}
            step={Math.max(1, Math.floor(maxOverlap / 20))}
            value={effectiveOverlap}
            onChange={(e) => setChunkOverlap(Number(e.target.value))}
            className="w-full accent-primary"
          />
          <div className="flex justify-between text-[10px] text-muted-foreground">
            <span>0</span>
            <span>{maxOverlap} (max)</span>
          </div>
        </div>

        <p className="text-[11px] text-muted-foreground">
          Changes apply to newly ingested files only. Re-upload existing files to re-chunk with the new settings.
        </p>

        {isDirty && (
          <div className="flex justify-end">
            <Button size="sm" onClick={handleSave} disabled={saving} className="gap-1.5">
              {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
              {saving ? "Saving…" : "Save Config"}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Add Source tabs ──────────────────────────────────────────────────────────

type AddTab = "file" | "url";

function AddSourcePanel({ kbId }: { kbId: string }) {
  const qc = useQueryClient();
  const [tab, setTab] = useState<AddTab>("file");

  // File upload state
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  // URL ingestion state
  const [url, setUrl] = useState("");
  const [ingesting, setIngesting] = useState(false);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      await knowledgeBasesApi.uploadFile(kbId, file);
      toast.success(`"${file.name}" queued for processing`);
      qc.invalidateQueries({ queryKey: ["kb-files", kbId] });
      qc.invalidateQueries({ queryKey: ["knowledge-bases"] });
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } };
      toast.error(e.response?.data?.detail || "File upload failed");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const handleIngestUrl = async () => {
    const trimmed = url.trim();
    if (!trimmed) { toast.error("Enter a URL"); return; }
    if (!trimmed.startsWith("http://") && !trimmed.startsWith("https://")) {
      toast.error("URL must start with http:// or https://");
      return;
    }
    setIngesting(true);
    try {
      const res = await knowledgeBasesApi.ingestUrl(kbId, trimmed);
      toast.success(`Fetched "${res.data.title}" — ${res.data.chars.toLocaleString()} chars`);
      setUrl("");
      qc.invalidateQueries({ queryKey: ["kb-files", kbId] });
      qc.invalidateQueries({ queryKey: ["knowledge-bases"] });
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } };
      toast.error(e.response?.data?.detail || "Failed to fetch URL");
    } finally {
      setIngesting(false);
    }
  };

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      {/* Tabs */}
      <div className="flex border-b border-border bg-accent/10">
        {(["file", "url"] as AddTab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium transition-colors",
              tab === t
                ? "bg-card text-foreground border-b-2 border-primary"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {t === "file" ? <Upload className="w-3.5 h-3.5" /> : <Globe className="w-3.5 h-3.5" />}
            {t === "file" ? "Upload File" : "From URL"}
          </button>
        ))}
      </div>

      <div className="p-4">
        {tab === "file" && (
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              Supported: PDF, DOCX, TXT, MD, JSON, CSV, YAML, Python, TypeScript, Go, Rust, and more.
              Max 50 MB.
            </p>
            <div className="flex gap-2">
              <input
                ref={fileRef}
                type="file"
                className="hidden"
                onChange={handleFileUpload}
                accept=".pdf,.txt,.md,.docx,.py,.ts,.tsx,.js,.jsx,.json,.yaml,.yml,.csv,.rst,.html,.go,.rs,.rb"
              />
              <Button
                size="sm"
                variant="outline"
                onClick={() => fileRef.current?.click()}
                disabled={uploading}
                className="gap-1.5"
              >
                {uploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
                {uploading ? "Uploading…" : "Choose File"}
              </Button>
            </div>
          </div>
        )}

        {tab === "url" && (
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              Fetch a web page and extract its text content. Works with HTML pages and plain text.
            </p>
            <div className="flex gap-2">
              <Input
                type="url"
                placeholder="https://example.com/docs/page"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !ingesting && handleIngestUrl()}
                className="flex-1 h-8 text-sm font-mono"
              />
              <Button
                size="sm"
                onClick={handleIngestUrl}
                disabled={ingesting || !url.trim()}
                className="gap-1.5 shrink-0"
              >
                {ingesting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <LinkIcon className="w-3.5 h-3.5" />}
                {ingesting ? "Fetching…" : "Add URL"}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── File row ──────────────────────────────────────────────────────────────────

function FileRow({ file, kbId }: { file: KnowledgeFile; kbId: string }) {
  const qc = useQueryClient();

  const del = useMutation({
    mutationFn: () => knowledgeBasesApi.deleteFile(kbId, file.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["kb-files", kbId] });
      qc.invalidateQueries({ queryKey: ["knowledge-bases"] });
      toast.success("Document removed");
    },
    onError: () => toast.error("Failed to delete document"),
  });

  const st = STATUS_BADGE[file.status] ?? STATUS_BADGE.pending;
  const StatusIcon = st.icon;

  return (
    <div className="flex items-center gap-4 px-5 py-3 border-b border-border/60 last:border-0 hover:bg-accent/10 group transition-colors">
      <div className="w-7 h-7 rounded-md bg-primary/10 flex items-center justify-center shrink-0">
        {file.source_url ? (
          <Globe className="w-3.5 h-3.5 text-primary" />
        ) : (
          <FileText className="w-3.5 h-3.5 text-primary" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5 flex-wrap">
          <span className="text-sm font-medium truncate max-w-xs">{file.filename}</span>
          <Badge variant="outline" className={cn("text-[10px] h-4 px-1.5 flex items-center gap-1", st.cls)}>
            <StatusIcon className={cn("w-2.5 h-2.5", file.status === "processing" && "animate-spin")} />
            {st.label}
          </Badge>
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          {file.source_url ? (
            <a
              href={file.source_url}
              target="_blank"
              rel="noreferrer"
              className="font-mono truncate max-w-xs hover:text-foreground"
              onClick={(e) => e.stopPropagation()}
            >
              {file.source_url}
            </a>
          ) : (
            <span>{fmtBytes(file.size_bytes)}</span>
          )}
          {file.status === "ready" && (
            <span>{file.chunk_count} chunk{file.chunk_count !== 1 ? "s" : ""}</span>
          )}
          {file.error && (
            <span className="text-destructive truncate max-w-xs" title={file.error}>
              {file.error}
            </span>
          )}
        </div>
      </div>
      <button
        onClick={() => {
          if (confirm(`Remove "${file.filename}"?`)) del.mutate();
        }}
        className="opacity-0 group-hover:opacity-100 p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-destructive transition-all shrink-0"
      >
        <Trash2 className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function KnowledgeBaseDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();

  const { data: kb, isLoading: kbLoading } = useQuery<KnowledgeBase>({
    queryKey: ["knowledge-base", id],
    queryFn: () => knowledgeBasesApi.get(id).then((r) => r.data),
  });

  const { data: files = [], isLoading: filesLoading } = useQuery<KnowledgeFile[]>({
    queryKey: ["kb-files", id],
    queryFn: () => knowledgeBasesApi.listFiles(id).then((r) => r.data),
    refetchInterval: (query) => {
      // Poll while any file is processing/pending
      const data = query.state.data as KnowledgeFile[] | undefined;
      if (!data) return false;
      return data.some((f) => f.status === "pending" || f.status === "processing") ? 3000 : false;
    },
  });

  if (kbLoading) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        <Loader2 className="w-5 h-5 animate-spin mr-2" />Loading…
      </div>
    );
  }

  if (!kb) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-muted-foreground">
        <AlertCircle className="w-8 h-8 opacity-30" />
        <p>Knowledge base not found.</p>
        <Button size="sm" variant="outline" onClick={() => router.push("/knowledge-bases")}>
          <ChevronLeft className="w-3.5 h-3.5 mr-1.5" />Back
        </Button>
      </div>
    );
  }

  const readyCount = files.filter((f) => f.status === "ready").length;
  const totalChunks = files.reduce((acc, f) => acc + f.chunk_count, 0);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 py-4 border-b border-border shrink-0">
        <button
          onClick={() => router.push("/knowledge-bases")}
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground mb-2 transition-colors"
        >
          <ChevronLeft className="w-3.5 h-3.5" />
          Knowledge Bases
        </button>
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
            <BookOpen className="w-4 h-4 text-primary" />
          </div>
          <div>
            <h1 className="text-xl font-bold">{kb.name}</h1>
            <p className="text-sm text-muted-foreground">
              {files.length} document{files.length !== 1 ? "s" : ""}
              {readyCount > 0 && ` · ${readyCount} ready · ${totalChunks.toLocaleString()} chunks`}
            </p>
          </div>
        </div>
        {kb.description && (
          <p className="text-sm text-muted-foreground mt-2 ml-11">{kb.description}</p>
        )}
      </div>

      {/* Scroll content */}
      <div className="flex-1 overflow-auto">
        {/* Chunking config panel */}
        <div className="px-6 py-4 border-b border-border">
          <ChunkingConfigPanel kb={kb} />
        </div>

        {/* Add source panel */}
        <div className="px-6 py-4 border-b border-border">
          <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">
            Add Source
          </h2>
          <AddSourcePanel kbId={id} />
        </div>

        {/* Documents list */}
        <div>
          <div className="px-5 py-2 bg-accent/20 border-b border-border/60 flex items-center gap-2">
            <FileText className="w-3.5 h-3.5 text-muted-foreground" />
            <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">
              {files.length} document{files.length !== 1 ? "s" : ""}
            </span>
          </div>

          {filesLoading ? (
            <div className="flex items-center justify-center h-32 text-muted-foreground">
              <Loader2 className="w-4 h-4 animate-spin mr-2" />Loading documents…
            </div>
          ) : files.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-40 text-muted-foreground gap-2">
              <FileText className="w-8 h-8 opacity-20" />
              <p className="text-sm">No documents yet — upload a file or add a URL above.</p>
            </div>
          ) : (
            files.map((file) => (
              <FileRow key={file.id} file={file} kbId={id} />
            ))
          )}
        </div>
      </div>
    </div>
  );
}
