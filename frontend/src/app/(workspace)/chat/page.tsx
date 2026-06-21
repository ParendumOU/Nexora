"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { MessageSquare, Bot, FolderKanban, ChevronDown, X } from "lucide-react";
import { chatsApi, projectsApi } from "@/lib/api";
import { BrandMark } from "@/components/BrandMark";
import { Button } from "@/components/ui/button";
import { ProjectPicker } from "@/components/ui/project-picker";

const STARTERS = [
  "Help me plan a new feature for my project",
  "Review this code and suggest improvements",
  "Set up a CI/CD pipeline for my repository",
  "Write unit tests for my latest code changes",
];

interface Project { id: string; name: string; description?: string; repo_url?: string | null }

function triggerLabel(ids: string[], projects: Project[]): string {
  if (ids.length === 0) return "No project";
  if (ids.length === 1) return projects.find((p) => p.id === ids[0])?.name ?? "1 project";
  return `${ids.length} projects`;
}

export default function ChatHomePage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [selectedProjectIds, setSelectedProjectIds] = useState<string[]>([]);

  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: () => projectsApi.list().then((r) => r.data),
  });

  const createChat = useMutation({
    mutationFn: (content?: string) =>
      chatsApi.create({
        title: content ? content.slice(0, 60) : "New Chat",
        project_ids: selectedProjectIds.length > 0 ? selectedProjectIds : undefined,
      }),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["chats"] });
      router.push(`/chat/${res.data.id}`);
    },
  });

  return (
    <div className="flex flex-col items-center justify-center h-full px-4 animate-fade-in">
      <div className="w-full max-w-2xl space-y-8">
        {/* Hero */}
        <div className="text-center space-y-3">
          <BrandMark className="w-14 h-14 mb-2 inline-block" />
          <h1 className="text-2xl font-semibold tracking-tight">How can I help you today?</h1>
          <p className="text-muted-foreground text-sm">
            Start a chat, create a project, or build an agent.
          </p>
        </div>

        {/* Project selector */}
        <div className="flex items-center justify-center gap-2">
          <ProjectPicker
            multiple
            projects={projects}
            value={selectedProjectIds}
            onChange={setSelectedProjectIds}
          >
            <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border bg-card hover:bg-accent hover:border-primary/30 transition-colors text-sm font-medium">
              <FolderKanban className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
              <span className="truncate max-w-[200px]">
                {triggerLabel(selectedProjectIds, projects)}
              </span>
              <ChevronDown className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
            </button>
          </ProjectPicker>

          {selectedProjectIds.length > 0 && (
            <button
              onClick={() => setSelectedProjectIds([])}
              className="p-1 rounded hover:bg-accent text-muted-foreground transition-colors"
              title="Clear projects"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        {/* Quick starters */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {STARTERS.map((s) => (
            <button
              key={s}
              onClick={() => createChat.mutate(s)}
              className="text-left px-4 py-3 rounded-xl border border-border bg-card hover:bg-accent hover:border-primary/30 transition-colors text-sm text-foreground"
            >
              {s}
            </button>
          ))}
        </div>

        {/* Action buttons */}
        <div className="flex items-center justify-center gap-3">
          <Button onClick={() => createChat.mutate(undefined)} variant="default" className="gap-2">
            <MessageSquare className="w-4 h-4" />
            New Chat
          </Button>
          <Button onClick={() => router.push("/projects")} variant="outline" className="gap-2">
            <FolderKanban className="w-4 h-4" />
            Projects
          </Button>
          <Button onClick={() => router.push("/agents")} variant="outline" className="gap-2">
            <Bot className="w-4 h-4" />
            Agents
          </Button>
        </div>
      </div>
    </div>
  );
}
