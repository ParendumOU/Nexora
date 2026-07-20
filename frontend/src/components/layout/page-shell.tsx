"use client";

import * as React from "react";
import { Loader2, Search, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/**
 * Shared chrome for every advanced-view management page (tasks, issues,
 * proposals, approvals, projects, channels, schedules, agents, personas,
 * skills, tools, MCP servers, knowledge bases, memory, organization).
 *
 * Every page uses the same header (icon tile + title + subtitle + actions),
 * the same filter pills and the same search field so the whole section reads
 * as one interface.
 */

// ─── Header ───────────────────────────────────────────────────────────────────

export function PageHeader({
  icon: Icon,
  title,
  subtitle,
  actions,
  children,
}: {
  icon: React.ElementType;
  title: string;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <div className="px-6 py-4 border-b border-border shrink-0">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
            <Icon className="w-4 h-4 text-primary" />
          </div>
          <div className="min-w-0">
            <h1 className="text-base font-semibold leading-tight truncate">{title}</h1>
            {subtitle && (
              <p className="text-xs text-muted-foreground leading-snug truncate">{subtitle}</p>
            )}
          </div>
        </div>
        {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
      </div>
      {children}
    </div>
  );
}

// ─── Filter pills ─────────────────────────────────────────────────────────────

export type FilterOption<T extends string = string> = {
  id: T;
  label: string;
  count?: number;
};

export function FilterBar<T extends string>({
  options,
  value,
  onChange,
  children,
  className,
}: {
  options: FilterOption<T>[];
  value: T;
  onChange: (id: T) => void;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "px-6 py-2 border-b border-border flex items-center gap-2 flex-wrap shrink-0",
        className
      )}
    >
      {options.map(({ id, label, count }) => (
        <FilterPill
          key={id}
          active={value === id}
          onClick={() => onChange(id)}
          label={label}
          count={count}
        />
      ))}
      {children}
    </div>
  );
}

export function FilterPill({
  active,
  onClick,
  label,
  count,
  className,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count?: number;
  className?: string;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "text-xs px-2.5 py-1 rounded-full border transition-colors",
        active
          ? "bg-primary text-primary-foreground border-primary"
          : "border-border text-muted-foreground hover:text-foreground hover:bg-accent",
        className
      )}
    >
      {label}
      {count !== undefined && ` (${count})`}
    </button>
  );
}

// ─── Section label ────────────────────────────────────────────────────────────

export function SectionLabel({
  icon: Icon,
  label,
  count,
  trailing,
}: {
  icon?: React.ElementType;
  label: string;
  count?: number;
  trailing?: React.ReactNode;
}) {
  return (
    <div className="px-5 py-2 bg-accent/20 border-b border-border/60 flex items-center gap-2">
      {Icon && <Icon className="w-3.5 h-3.5 text-muted-foreground" />}
      <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">
        {label}
        {count !== undefined && ` (${count})`}
      </span>
      {trailing && <div className="ml-auto">{trailing}</div>}
    </div>
  );
}

// ─── Search ───────────────────────────────────────────────────────────────────

export function PageSearch({
  value,
  onChange,
  placeholder = "Search…",
  children,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="px-6 py-2.5 border-b border-border shrink-0 flex items-center gap-2">
      <div className="relative flex-1">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
        <Input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="pl-8 h-8 text-sm"
        />
        {value && (
          <button
            onClick={() => onChange("")}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
      {children}
    </div>
  );
}

// ─── States ───────────────────────────────────────────────────────────────────

export function PageLoading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center h-40 text-muted-foreground text-sm">
      <Loader2 className="w-5 h-5 animate-spin mr-2" />
      {label}
    </div>
  );
}

export function PageEmpty({
  icon: Icon,
  message,
  children,
}: {
  icon: React.ElementType;
  message: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center h-60 gap-3 text-muted-foreground">
      <Icon className="w-10 h-10 opacity-20" />
      <p className="text-sm">{message}</p>
      {children}
    </div>
  );
}

// ─── Page wrapper ─────────────────────────────────────────────────────────────

export function PageShell({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-col h-full">{children}</div>;
}

export function PageBody({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <div className={cn("flex-1 overflow-auto", className)}>{children}</div>;
}
