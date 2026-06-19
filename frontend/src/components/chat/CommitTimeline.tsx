"use client";

import { GitCommit } from "lucide-react";
import type { CommitEntry } from "@/lib/file-tree";

export function CommitTimeline({ commits }: { commits: CommitEntry[] }) {
  if (commits.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center flex-1 gap-2 text-center px-6 py-12">
        <GitCommit className="w-6 h-6 text-muted-foreground/40" />
        <p className="text-xs text-muted-foreground">No commits found</p>
      </div>
    );
  }

  return (
    <div className="overflow-y-auto flex-1 py-2 px-3">
      {commits.map((c, i) => (
        <div key={c.sha} className="flex gap-3 pb-3">
          <div className="flex flex-col items-center">
            <div className="w-2 h-2 rounded-full bg-primary shrink-0 mt-1" />
            {i < commits.length - 1 && <div className="w-px flex-1 bg-border mt-1" />}
          </div>
          <div className="flex-1 min-w-0 pb-1">
            <p className="text-xs text-foreground truncate leading-tight">{c.message}</p>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-[10px] font-mono text-muted-foreground/70 bg-accent/50 px-1 rounded">{c.sha}</span>
              <span className="text-[10px] text-muted-foreground/60 truncate">{c.author}</span>
            </div>
            <p className="text-[10px] text-muted-foreground/40 mt-0.5">
              {new Date(c.date).toLocaleString([], { dateStyle: "short", timeStyle: "short" })}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}
