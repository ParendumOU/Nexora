"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { chatFilesApi } from "@/lib/api";
import {
  FileText, Image, File, Archive, Code2, Trash2, Download,
  Loader2, X, Upload, Folder, FolderOpen, ChevronRight, ChevronDown,
} from "lucide-react";
import { cn } from "@/lib/utils";

export interface ChatFile {
  id: string;
  name: string;
  folder?: string;
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

// ── Folder tree ───────────────────────────────────────────────────────────────
interface TreeNode {
  name: string;
  path: string;
  folders: Map<string, TreeNode>;
  files: ChatFile[];
}

function buildTree(files: ChatFile[]): TreeNode {
  const root: TreeNode = { name: "", path: "", folders: new Map(), files: [] };
  for (const f of files) {
    const segs = (f.folder || "").split("/").map((s) => s.trim()).filter(Boolean);
    let cur = root;
    for (const seg of segs) {
      let next = cur.folders.get(seg);
      if (!next) {
        next = { name: seg, path: cur.path ? `${cur.path}/${seg}` : seg, folders: new Map(), files: [] };
        cur.folders.set(seg, next);
      }
      cur = next;
    }
    cur.files.push(f);
  }
  return root;
}

interface Props {
  chatId: string;
  onClose: () => void;
}

export function ChatFilesPanel({ chatId, onClose }: Props) {
  const qc = useQueryClient();
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const { data: files = [], isLoading } = useQuery<ChatFile[]>({
    queryKey: ["chat-files", chatId],
    queryFn: () => chatFilesApi.list(chatId).then((r) => r.data),
    enabled: !!chatId,
    refetchInterval: 10_000,
  });

  const deleteMut = useMutation({
    mutationFn: ({ fileId }: { fileId: string }) => chatFilesApi.delete(chatId, fileId),
    onMutate: ({ fileId }) => setDeletingId(fileId),
    onSettled: () => {
      setDeletingId(null);
      qc.invalidateQueries({ queryKey: ["chat-files", chatId] });
    },
  });

  const downloadFile = async (file: ChatFile) => {
    const token = localStorage.getItem("access_token");
    const url = chatFilesApi.contentUrl(chatId, file.id);
    const res = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = file.name;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const FileRow = ({ file, depth }: { file: ChatFile; depth: number }) => {
    const Icon = fileIcon(file.content_type, file.name);
    const isDel = deletingId === file.id;
    return (
      <div
        className={cn(
          "group flex items-start gap-2 p-1.5 rounded-lg hover:bg-accent/50 transition-colors",
          isDel && "opacity-50 pointer-events-none"
        )}
        style={{ paddingLeft: 8 + depth * 14 }}
      >
        <div className="shrink-0 mt-0.5 w-6 h-6 rounded-md bg-accent flex items-center justify-center">
          <Icon className="w-3.5 h-3.5 text-muted-foreground" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium truncate" title={file.name}>{file.name}</p>
          <p className="text-[10px] text-muted-foreground">{formatSize(file.size)} · {formatDate(file.created_at)}</p>
        </div>
        <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
          <button onClick={() => downloadFile(file)} className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground transition-colors" title="Download">
            <Download className="w-3 h-3" />
          </button>
          <button onClick={() => deleteMut.mutate({ fileId: file.id })} className="p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors" title="Delete">
            {isDel ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
          </button>
        </div>
      </div>
    );
  };

  const FolderNode = ({ node, depth }: { node: TreeNode; depth: number }) => {
    const subFolders = Array.from(node.folders.values()).sort((a, b) => a.name.localeCompare(b.name));
    const sortedFiles = [...node.files].sort((a, b) => a.name.localeCompare(b.name));
    return (
      <>
        {subFolders.map((f) => {
          const isCol = collapsed[f.path] === true;
          return (
            <div key={f.path}>
              <button
                onClick={() => setCollapsed((p) => ({ ...p, [f.path]: !isCol }))}
                className="w-full flex items-center gap-1.5 p-1.5 rounded-lg hover:bg-accent/50 transition-colors text-left"
                style={{ paddingLeft: 8 + depth * 14 }}
              >
                {isCol ? <ChevronRight className="w-3 h-3 text-muted-foreground shrink-0" /> : <ChevronDown className="w-3 h-3 text-muted-foreground shrink-0" />}
                {isCol ? <Folder className="w-3.5 h-3.5 text-primary/70 shrink-0" /> : <FolderOpen className="w-3.5 h-3.5 text-primary/70 shrink-0" />}
                <span className="text-xs font-medium truncate">{f.name}</span>
                <span className="text-[10px] text-muted-foreground ml-auto">{countFiles(f)}</span>
              </button>
              {!isCol && <FolderNode node={f} depth={depth + 1} />}
            </div>
          );
        })}
        {sortedFiles.map((file) => <FileRow key={file.id} file={file} depth={depth} />)}
      </>
    );
  };

  const tree = buildTree(files);

  return (
    <div className="flex flex-col h-full w-72 border-l border-border bg-card shrink-0 overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <Upload className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold">Files</span>
          {files.length > 0 && (
            <span className="text-[10px] bg-accent text-foreground px-1.5 py-0.5 rounded font-mono">{files.length}</span>
          )}
        </div>
        <button onClick={onClose} className="p-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
        {isLoading && (
          <div className="flex items-center justify-center py-8"><Loader2 className="w-4 h-4 animate-spin text-muted-foreground" /></div>
        )}
        {!isLoading && files.length === 0 && (
          <div className="flex flex-col items-center justify-center py-8 gap-2 text-center">
            <Upload className="w-8 h-8 text-muted-foreground/40" />
            <p className="text-xs text-muted-foreground">No files yet</p>
            <p className="text-[10px] text-muted-foreground/60">Drag & drop, or agents deliver here</p>
          </div>
        )}
        {!isLoading && files.length > 0 && <FolderNode node={tree} depth={0} />}
      </div>

      <div className="px-3 py-2 border-t border-border shrink-0">
        <p className="text-[10px] text-muted-foreground text-center">All chats in this thread share these files</p>
      </div>
    </div>
  );
}

function countFiles(node: TreeNode): number {
  let n = node.files.length;
  for (const f of node.folders.values()) n += countFiles(f);
  return n;
}
