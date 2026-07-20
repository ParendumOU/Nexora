"use client";
import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  FolderKanban, Plus, Loader2, Trash2, Bot, ChevronRight,
  GitBranch, Calendar,
} from "lucide-react";
import { projectsApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  PageShell, PageHeader, PageBody, FilterBar, PageSearch, PageLoading, PageEmpty,
} from "@/components/layout/page-shell";
import toast from "react-hot-toast";
import * as Dialog from "@radix-ui/react-dialog";

type Project = {
  id: string;
  name: string;
  description: string | null;
  repo_url: string | null;
  repo_type: string | null;
  status: string;
  pm_agent_id: string | null;
  pm_agent_name: string | null;
  tools: string[];
  mcps: unknown[];
  created_at: string;
};

// ─── Create dialog ────────────────────────────────────────────────────────────

function CreateProjectDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const qc = useQueryClient();
  const [form, setForm] = useState({ name: "", description: "", repo_url: "", repo_type: "github" });
  const [loading, setLoading] = useState(false);

  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const handleCreate = async () => {
    if (!form.name.trim()) { toast.error("Project name is required"); return; }
    setLoading(true);
    try {
      const res = await projectsApi.create({
        name: form.name.trim(),
        description: form.description.trim() || undefined,
        repo_url: form.repo_url.trim() || undefined,
        repo_type: form.repo_url.trim() ? form.repo_type : undefined,
      });
      qc.invalidateQueries({ queryKey: ["projects"] });
      toast.success("Project created");
      onClose();
      setForm({ name: "", description: "", repo_url: "", repo_type: "github" });
      onCreated(res.data.id);
    } catch {
      toast.error("Failed to create project");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-md bg-card border border-border rounded-2xl p-6 shadow-2xl space-y-4">
          <Dialog.Title className="text-base font-semibold">New Project</Dialog.Title>
          <p className="text-sm text-muted-foreground">
            A Project Manager AI is automatically created to coordinate your team.
          </p>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Project name *</label>
              <Input placeholder="My Awesome App" value={form.name} onChange={set("name")} autoFocus />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Description</label>
              <Input placeholder="What are you building?" value={form.description} onChange={set("description")} />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Repository URL (optional)</label>
              <Input placeholder="https://github.com/org/repo" value={form.repo_url} onChange={set("repo_url")} />
            </div>
          </div>
          <div className="flex justify-between pt-2">
            <Button variant="ghost" onClick={onClose} disabled={loading}>Cancel</Button>
            <Button onClick={handleCreate} disabled={loading}>
              {loading && <Loader2 className="w-4 h-4 animate-spin mr-1.5" />}
              Create Project
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// ─── Project row ──────────────────────────────────────────────────────────────

function fmtRelative(iso: string) {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function ProjectRow({
  project,
  onClick,
  onDelete,
}: {
  project: Project;
  onClick: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      onClick={onClick}
      className="flex items-center gap-4 px-5 py-3.5 hover:bg-accent/30 transition-colors group cursor-pointer border-b border-border/60 last:border-0"
    >
      <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
        <FolderKanban className="w-4 h-4 text-primary" />
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap mb-0.5">
          <span className="text-sm font-medium text-foreground">{project.name}</span>
          {project.repo_url && (
            <span
              onClick={(e) => e.stopPropagation()}
              className="flex items-center gap-1 text-[10px] text-muted-foreground"
            >
              <GitBranch className="w-3 h-3" />
              <a href={project.repo_url} target="_blank" rel="noopener noreferrer"
                className="hover:text-primary truncate max-w-[160px]">
                {project.repo_url.replace("https://", "")}
              </a>
            </span>
          )}
        </div>
        {project.description && (
          <p className="text-xs text-muted-foreground leading-snug line-clamp-1">{project.description}</p>
        )}
      </div>

      <div className="flex items-center gap-4 shrink-0 text-[11px] text-muted-foreground">
        {project.tools?.length > 0 && (
          <span className="flex items-center gap-1">
            Tools: {project.tools.length}
          </span>
        )}
        {project.pm_agent_name && (
          <span className="flex items-center gap-1">
            <Bot className="w-3 h-3 text-green-400" />
            PM
          </span>
        )}
        {project.created_at && (
          <span className="flex items-center gap-1">
            <Calendar className="w-3 h-3" />
            {fmtRelative(project.created_at)}
          </span>
        )}
      </div>

      <div className="flex items-center gap-1 shrink-0">
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          className="opacity-0 group-hover:opacity-100 p-1 rounded hover:text-destructive transition-all text-muted-foreground"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
        <ChevronRight className="w-4 h-4 text-muted-foreground/40 opacity-0 group-hover:opacity-100 transition-all" />
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

type FilterType = "all" | "active";

export default function ProjectsPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<FilterType>("all");

  const { data: projects = [], isLoading } = useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: () => projectsApi.list().then((r) => r.data),
  });

  const deleteProject = useMutation({
    mutationFn: (id: string) => projectsApi.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      toast.success("Project deleted");
    },
  });

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return projects.filter((p) => {
      const matchesSearch = !q || p.name.toLowerCase().includes(q) || (p.description ?? "").toLowerCase().includes(q);
      const matchesFilter = filter === "all" || p.status === "active";
      return matchesSearch && matchesFilter;
    });
  }, [projects, search, filter]);

  const FILTERS: { id: FilterType; label: string; count: number }[] = [
    { id: "all", label: "All", count: projects.length },
    { id: "active", label: "Active", count: projects.filter((p) => p.status === "active").length },
  ];

  return (
    <PageShell>
      <PageHeader
        icon={FolderKanban}
        title="Projects"
        subtitle={`${projects.length} project${projects.length !== 1 ? "s" : ""} · each gets a dedicated PM agent`}
        actions={
          <Button onClick={() => setShowCreate(true)} size="sm" className="gap-1.5">
            <Plus className="w-3.5 h-3.5" />New Project
          </Button>
        }
      />

      <FilterBar options={FILTERS} value={filter} onChange={setFilter} />

      <PageSearch
        value={search}
        onChange={setSearch}
        placeholder="Search by name or description…"
      />

      <PageBody>
        {isLoading ? (
          <PageLoading />
        ) : filtered.length === 0 ? (
          <PageEmpty
            icon={FolderKanban}
            message={search ? "No projects match your search" : "No projects yet"}
          >
            {!search && (
              <Button size="sm" variant="outline" onClick={() => setShowCreate(true)}>
                <Plus className="w-3.5 h-3.5 mr-1.5" />Create your first project
              </Button>
            )}
          </PageEmpty>
        ) : (
          filtered.map((p) => (
            <ProjectRow
              key={p.id}
              project={p}
              onClick={() => router.push(`/projects/${p.id}`)}
              onDelete={() => deleteProject.mutate(p.id)}
            />
          ))
        )}
      </PageBody>

      <CreateProjectDialog
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={(id) => router.push(`/projects/${id}`)}
      />
    </PageShell>
  );
}
