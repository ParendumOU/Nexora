"use client";

import { useState, useRef, useEffect, ReactNode } from "react";
import { FolderKanban, Search, Check } from "lucide-react";
import * as Popover from "@radix-ui/react-popover";
import { cn } from "@/lib/utils";

interface Project {
  id: string;
  name: string;
  description?: string | null;
  repo_url?: string | null;
}

function repoSlug(url: string | null | undefined): string | null {
  if (!url) return null;
  const m = url.match(/(?:github\.com|gitlab\.com)[:/](.+?)(?:\.git)?(?:\/?$)/i);
  if (!m) return null;
  const slug = m[1].replace(/\/$/, "");
  return slug.length > 40 ? slug.slice(0, 38) + "…" : slug;
}

// ── Single-select ─────────────────────────────────────────────────────────────

interface ProjectPickerSingleProps {
  multiple?: false;
  projects: Project[];
  value: string | null;
  onChange: (id: string | null) => void;
  children: ReactNode;
}

// ── Multi-select ──────────────────────────────────────────────────────────────

interface ProjectPickerMultiProps {
  multiple: true;
  projects: Project[];
  value: string[];
  onChange: (ids: string[]) => void;
  children: ReactNode;
}

type ProjectPickerProps = ProjectPickerSingleProps | ProjectPickerMultiProps;

// ── Shared list content ───────────────────────────────────────────────────────

function PickerContent({
  projects,
  multiple,
  isSelected,
  onToggle,
  onClose,
}: {
  projects: Project[];
  multiple: boolean;
  isSelected: (id: string | null) => boolean;
  onToggle: (id: string | null) => void;
  onClose: () => void;
}) {
  const [search, setSearch] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setTimeout(() => inputRef.current?.focus(), 50);
  }, []);

  const tokens = search.toLowerCase().split(/\s+/).filter(Boolean);
  const filtered = projects.filter((p) => {
    if (!tokens.length) return true;
    const haystack = [p.name, p.description, p.repo_url].filter(Boolean).join(" ").toLowerCase();
    return tokens.every((t) => haystack.includes(t));
  });

  const handleClick = (id: string | null) => {
    onToggle(id);
    if (!multiple) onClose();
  };

  return (
    <>
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border">
        <Search className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
        <input
          ref={inputRef}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search projects…"
          className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
        />
      </div>

      <div className="overflow-y-auto max-h-64 p-1">
        <button
          onClick={() => handleClick(null)}
          className={cn(
            "flex items-center gap-2 w-full px-2.5 py-2 rounded-lg text-sm transition-colors",
            isSelected(null) ? "bg-primary/10 text-primary" : "hover:bg-accent text-muted-foreground"
          )}
        >
          <span className="flex-1 text-left">No project</span>
          {isSelected(null) && <Check className="w-3.5 h-3.5 shrink-0" />}
        </button>

        {filtered.length > 0 ? (
          <div className="space-y-0.5 mt-0.5">
            {filtered.map((p) => {
              const slug = repoSlug(p.repo_url);
              return (
                <button
                  key={p.id}
                  onClick={() => handleClick(p.id)}
                  className={cn(
                    "flex items-start gap-2 w-full px-2.5 py-2 rounded-lg text-sm transition-colors text-left",
                    isSelected(p.id) ? "bg-primary/10 text-primary" : "hover:bg-accent text-foreground"
                  )}
                >
                  <FolderKanban className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <span className="block truncate">{p.name}</span>
                    {p.description && (
                      <span className="text-[10px] text-muted-foreground truncate block">{p.description}</span>
                    )}
                    {slug && (
                      <span className="text-[10px] text-muted-foreground/60 truncate block font-mono">{slug}</span>
                    )}
                  </div>
                  {isSelected(p.id) && <Check className="w-3.5 h-3.5 shrink-0 mt-0.5" />}
                </button>
              );
            })}
          </div>
        ) : (
          <p className="text-[11px] text-muted-foreground px-2.5 py-3 text-center">
            {search ? "No projects match." : (
              <>No projects yet. <a href="/projects" className="text-primary underline">Create one</a></>
            )}
          </p>
        )}
      </div>

      {projects.length > 0 && (
        <div className="border-t border-border px-3 py-1.5 flex items-center justify-between">
          <p className="text-[10px] text-muted-foreground">
            {filtered.length} of {projects.length} project{projects.length !== 1 ? "s" : ""}
          </p>
          {multiple && !isSelected(null) && (
            <button onClick={onClose} className="text-[10px] text-primary hover:underline">
              Done
            </button>
          )}
        </div>
      )}
    </>
  );
}

// ── Main export ───────────────────────────────────────────────────────────────

export function ProjectPicker(props: ProjectPickerProps) {
  const [open, setOpen] = useState(false);
  const { projects, children } = props;

  const isSelected = (id: string | null): boolean => {
    if (props.multiple) {
      return id === null ? props.value.length === 0 : props.value.includes(id);
    }
    return id === null ? props.value === null : props.value === id;
  };

  const onToggle = (id: string | null) => {
    if (props.multiple) {
      if (id === null) {
        props.onChange([]);
      } else {
        const current = props.value;
        props.onChange(
          current.includes(id) ? current.filter((x) => x !== id) : [...current, id]
        );
      }
    } else {
      props.onChange(id);
    }
  };

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>{children}</Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          side="bottom"
          align="center"
          sideOffset={6}
          className="z-50 w-72 rounded-xl border border-border bg-card shadow-xl overflow-hidden animate-fade-in"
        >
          <PickerContent
            projects={projects}
            multiple={props.multiple === true}
            isSelected={isSelected}
            onToggle={onToggle}
            onClose={() => setOpen(false)}
          />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
