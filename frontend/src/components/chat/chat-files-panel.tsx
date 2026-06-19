"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { chatFilesApi } from "@/lib/api";
import {
  FileText, Image, File, Archive, Code2, Trash2, Download,
  Loader2, X, Upload,
} from "lucide-react";
import { cn } from "@/lib/utils";

export interface ChatFile {
  id: string;
  name: string;
  size: number;
  content_type: string;
  chat_id: string;
  created_at: string;
}

function fileIcon(contentType: string, name: string) {
  if (contentType.startsWith("image/")) return Image;
  if (contentType.startsWith("text/") || /\.(md|txt|log|csv)$/i.test(name)) return FileText;
  if (/\.(zip|tar|gz|rar|7z)$/i.test(name)) return Archive;
  if (/\.(js|ts|tsx|jsx|py|go|rs|java|c|cpp|h|sh|json|yaml|yml|toml|sql|html|css|xml)$/i.test(name)) return Code2;
  return File;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

interface Props {
  chatId: string;
  onClose: () => void;
}

export function ChatFilesPanel({ chatId, onClose }: Props) {
  const qc = useQueryClient();
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const { data: files = [], isLoading } = useQuery<ChatFile[]>({
    queryKey: ["chat-files", chatId],
    queryFn: () => chatFilesApi.list(chatId).then((r) => r.data),
    enabled: !!chatId,
    refetchInterval: 10_000,
  });

  const deleteMut = useMutation({
    mutationFn: ({ fileId }: { fileId: string }) =>
      chatFilesApi.delete(chatId, fileId),
    onMutate: ({ fileId }) => setDeletingId(fileId),
    onSettled: () => {
      setDeletingId(null);
      qc.invalidateQueries({ queryKey: ["chat-files", chatId] });
    },
  });

  return (
    <div className="flex flex-col h-full w-72 border-l border-border bg-card shrink-0 overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <Upload className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold">Attachments</span>
          {files.length > 0 && (
            <span className="text-[10px] bg-accent text-foreground px-1.5 py-0.5 rounded font-mono">
              {files.length}
            </span>
          )}
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {isLoading && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
          </div>
        )}

        {!isLoading && files.length === 0 && (
          <div className="flex flex-col items-center justify-center py-8 gap-2 text-center">
            <Upload className="w-8 h-8 text-muted-foreground/40" />
            <p className="text-xs text-muted-foreground">No files yet</p>
            <p className="text-[10px] text-muted-foreground/60">
              Drag & drop or use the paperclip
            </p>
          </div>
        )}

        {files.map((file) => {
          const Icon = fileIcon(file.content_type, file.name);
          const isDel = deletingId === file.id;
          return (
            <div
              key={file.id}
              className={cn(
                "group flex items-start gap-2.5 p-2 rounded-lg hover:bg-accent/50 transition-colors",
                isDel && "opacity-50 pointer-events-none"
              )}
            >
              <div className="shrink-0 mt-0.5 w-7 h-7 rounded-md bg-accent flex items-center justify-center">
                <Icon className="w-3.5 h-3.5 text-muted-foreground" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium truncate" title={file.name}>
                  {file.name}
                </p>
                <p className="text-[10px] text-muted-foreground">
                  {formatSize(file.size)} · {formatDate(file.created_at)}
                </p>
              </div>
              <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                <button
                  onClick={async () => {
                    const token = localStorage.getItem("access_token");
                    const url = chatFilesApi.contentUrl(chatId, file.id);
                    const res = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
                    const blob = await res.blob();
                    const a = document.createElement("a");
                    a.href = URL.createObjectURL(blob);
                    a.download = file.name;
                    a.click();
                    URL.revokeObjectURL(a.href);
                  }}
                  className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
                  title="Download"
                >
                  <Download className="w-3 h-3" />
                </button>
                <button
                  onClick={() => deleteMut.mutate({ fileId: file.id })}
                  className="p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors"
                  title="Delete"
                >
                  {isDel ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      <div className="px-3 py-2 border-t border-border shrink-0">
        <p className="text-[10px] text-muted-foreground text-center">
          All chats in this thread share these files
        </p>
      </div>
    </div>
  );
}
