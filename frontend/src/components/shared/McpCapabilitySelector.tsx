"use client";

import { useMemo, useState } from "react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export interface McpCapabilityTool {
  name: string;
  description: string;
}

export interface McpCapabilityServer {
  id: string;
  name: string;
  url: string;
  description: string | null;
  known_tools: McpCapabilityTool[];
}

export interface McpCapabilitySelection {
  server_id?: string;
  name: string;
  url: string;
  allowed_tools?: string[];
}

const PAGE_SIZE = 8;

export function McpCapabilitySelector({
  catalogMcps,
  selectedMcps,
  onToggleMcp,
  onSetAllowedTools,
  emptyText,
  readOnly = false,
  footerText,
}: {
  catalogMcps: McpCapabilityServer[];
  selectedMcps: McpCapabilitySelection[];
  onToggleMcp: (mcp: McpCapabilityServer) => void;
  onSetAllowedTools: (mcp: McpCapabilityServer, allowedTools: string[]) => void;
  emptyText: string;
  readOnly?: boolean;
  footerText?: string;
}) {
  const [toolSearch, setToolSearch] = useState<Record<string, string>>({});
  const [toolPage, setToolPage] = useState<Record<string, number>>({});

  const selectedById = useMemo(() => {
    const map = new Map<string, McpCapabilitySelection>();
    for (const mcp of catalogMcps) {
      const selected = selectedMcps.find((entry) =>
        entry.server_id === mcp.id || entry.name === mcp.name || entry.url === mcp.url
      );
      if (selected) map.set(mcp.id, selected);
    }
    return map;
  }, [catalogMcps, selectedMcps]);

  if (catalogMcps.length === 0) {
    return <p className="text-xs text-muted-foreground text-center py-8 px-4">{emptyText}</p>;
  }

  return (
    <div className="space-y-3">
      <div className="border border-border rounded-lg overflow-hidden">
        <div className="divide-y divide-border">
          {catalogMcps.map((mcp) => {
            const selected = selectedById.get(mcp.id);
            const isOn = !!selected;
            const knownToolNames = (mcp.known_tools ?? []).map((tool) => tool.name);
            const selectedToolNames = selected?.allowed_tools ?? knownToolNames;
            const selectedToolCount = selectedToolNames.filter((tool) => knownToolNames.includes(tool)).length;
            const search = toolSearch[mcp.id] ?? "";
            const filteredTools = mcp.known_tools.filter((tool) =>
              !search ||
              tool.name.toLowerCase().includes(search.toLowerCase()) ||
              (tool.description || "").toLowerCase().includes(search.toLowerCase())
            );
            const totalPages = Math.max(1, Math.ceil(filteredTools.length / PAGE_SIZE));
            const currentPage = Math.min(toolPage[mcp.id] ?? 1, totalPages);
            const pageStart = (currentPage - 1) * PAGE_SIZE;
            const pagedTools = filteredTools.slice(pageStart, pageStart + PAGE_SIZE);

            return (
              <div key={mcp.id} className={cn("px-4 py-3", isOn ? "bg-primary/5" : "bg-card")}>
                <button
                  onClick={() => !readOnly && onToggleMcp(mcp)}
                  className={cn(
                    "w-full flex items-center gap-3 text-left transition-colors",
                    !readOnly && "cursor-pointer"
                  )}
                >
                  <div className={cn(
                    "w-4 h-4 rounded border flex items-center justify-center transition-colors shrink-0",
                    isOn ? "bg-primary border-primary" : "border-border bg-background"
                  )}>
                    {isOn && <span className="text-[9px] text-primary-foreground font-bold leading-none">✓</span>}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium text-foreground">{mcp.name}</span>
                      {knownToolNames.length > 0 && (
                        <span className="text-[10px] text-muted-foreground">
                          {isOn
                            ? (selectedToolCount === knownToolNames.length
                              ? `All ${knownToolNames.length} tools`
                              : `${selectedToolCount}/${knownToolNames.length} tools`)
                            : `${knownToolNames.length} tools discovered`}
                        </span>
                      )}
                    </div>
                    <p className="text-[11px] text-muted-foreground">{mcp.description ?? mcp.url}</p>
                  </div>
                </button>

                {isOn && knownToolNames.length > 0 && (
                  <div className="mt-3 ml-7 border border-border rounded-lg overflow-hidden">
                    <div className="px-3 py-2 border-b border-border bg-accent/10 flex items-center gap-2">
                      <Input
                        value={search}
                        onChange={(e) => {
                          const nextValue = e.target.value;
                          setToolSearch((prev) => ({ ...prev, [mcp.id]: nextValue }));
                          setToolPage((prev) => ({ ...prev, [mcp.id]: 1 }));
                        }}
                        placeholder="Search tools…"
                        className="h-7 text-xs"
                      />
                      <span className="text-[10px] text-muted-foreground whitespace-nowrap">
                        {filteredTools.length} result{filteredTools.length !== 1 ? "s" : ""}
                      </span>
                    </div>

                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-accent/20 border-b border-border">
                          <th className="w-9 px-3 py-2" />
                          <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Tool</th>
                          <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Description</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border/60">
                        {pagedTools.map((tool) => {
                          const toolOn = selectedToolNames.includes(tool.name);
                          const nextTools = toolOn
                            ? selectedToolNames.filter((name) => name !== tool.name)
                            : [...selectedToolNames, tool.name];

                          return (
                            <tr
                              key={tool.name}
                              onClick={() => !readOnly && onSetAllowedTools(mcp, nextTools)}
                              className={cn(
                                "transition-colors",
                                !readOnly && "cursor-pointer",
                                toolOn ? "bg-primary/5 hover:bg-primary/8" : !readOnly && "hover:bg-accent/30"
                              )}
                            >
                              <td className="px-3 py-2.5">
                                <div className={cn(
                                  "w-4 h-4 rounded border flex items-center justify-center transition-colors shrink-0",
                                  toolOn ? "bg-primary border-primary" : "border-border bg-background"
                                )}>
                                  {toolOn && <span className="text-[9px] text-primary-foreground font-bold leading-none">✓</span>}
                                </div>
                              </td>
                              <td className="px-3 py-2.5 font-mono text-foreground whitespace-nowrap">{tool.name}</td>
                              <td className="px-3 py-2.5 text-muted-foreground">
                                <span className="line-clamp-2 leading-snug">{tool.description || "—"}</span>
                              </td>
                            </tr>
                          );
                        })}
                        {pagedTools.length === 0 && (
                          <tr>
                            <td colSpan={3} className="px-3 py-6 text-center text-xs text-muted-foreground">
                              No tools match your search.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>

                    {filteredTools.length > PAGE_SIZE && (
                      <div className="px-3 py-2 border-t border-border bg-accent/10 flex items-center justify-between">
                        <span className="text-[10px] text-muted-foreground">
                          Page {currentPage} of {totalPages}
                        </span>
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => setToolPage((prev) => ({ ...prev, [mcp.id]: Math.max(1, currentPage - 1) }))}
                            disabled={currentPage === 1}
                            className="h-6 px-2 text-[10px] rounded border border-border disabled:opacity-40 hover:bg-accent"
                          >
                            Prev
                          </button>
                          <button
                            onClick={() => setToolPage((prev) => ({ ...prev, [mcp.id]: Math.min(totalPages, currentPage + 1) }))}
                            disabled={currentPage === totalPages}
                            className="h-6 px-2 text-[10px] rounded border border-border disabled:opacity-40 hover:bg-accent"
                          >
                            Next
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {footerText && (
        <p className="px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
          {footerText}
        </p>
      )}
    </div>
  );
}
