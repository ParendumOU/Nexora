"use client";
import { cn } from "@/lib/utils";

export interface CapabilityRow {
  key: string;
  label: string;
  description: string | null;
  meta?: string;
  isOn: boolean;
  onToggle: () => void;
}

export function CapabilityTable({
  rows,
  emptyText,
  readOnly = false,
}: {
  rows: CapabilityRow[];
  emptyText: string;
  readOnly?: boolean;
}) {
  if (rows.length === 0) {
    return (
      <p className="text-xs text-muted-foreground text-center py-8 px-4">{emptyText}</p>
    );
  }

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <div className="overflow-y-auto max-h-64">
        <table className="w-full text-xs">
          <thead className="sticky top-0 z-10">
            <tr className="bg-accent/40 border-b border-border">
              <th className="w-9 px-3 py-2" />
              <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Name</th>
              <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Description</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/60">
            {rows.map((row) => (
              <tr
                key={row.key}
                onClick={readOnly ? undefined : row.onToggle}
                className={cn(
                  "transition-colors",
                  !readOnly && "cursor-pointer",
                  row.isOn
                    ? "bg-primary/5 hover:bg-primary/8"
                    : !readOnly && "hover:bg-accent/30"
                )}
              >
                <td className="px-3 py-2.5">
                  <div className={cn(
                    "w-4 h-4 rounded border flex items-center justify-center transition-colors shrink-0",
                    row.isOn ? "bg-primary border-primary" : "border-border bg-background"
                  )}>
                    {row.isOn && (
                      <span className="text-[9px] text-primary-foreground font-bold leading-none">✓</span>
                    )}
                  </div>
                </td>
                <td className="px-3 py-2.5 font-medium text-foreground whitespace-nowrap">
                  {row.label}
                  {row.meta && (
                    <span className="ml-1.5 text-[10px] font-normal text-muted-foreground">{row.meta}</span>
                  )}
                </td>
                <td className="px-3 py-2.5 text-muted-foreground">
                  <span className="line-clamp-2 leading-snug">{row.description ?? "—"}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
