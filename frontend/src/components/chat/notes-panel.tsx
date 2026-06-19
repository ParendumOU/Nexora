"use client";
import { useState, useCallback, Fragment } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { chatsApi } from "@/lib/api";
import {
  X, Plus, Loader2, NotebookPen, Pencil, Trash2,
  ChevronLeft, ChevronRight,
} from "lucide-react";
import toast from "react-hot-toast";

interface ChatNote {
  id: string;
  chat_id: string;
  content: string;
  description: string | null;
  author: string | null;
  source_chat_id: string | null;
  created_at: string;
  updated_at: string;
}

interface NotesPanelProps {
  chatId: string;
  onClose: () => void;
}

const PAGE_SIZE = 15;

function formatDate(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

// ── Modal ────────────────────────────────────────────────────────────────────
function NoteModal({
  title,
  note,
  onSave,
  onClose,
  saving,
}: {
  title: string;
  note?: ChatNote;
  onSave: (data: { content: string; description: string; author: string }) => void;
  onClose: () => void;
  saving: boolean;
}) {
  const [content, setContent] = useState(note?.content ?? "");
  const [description, setDescription] = useState(note?.description ?? "");
  const [author, setAuthor] = useState(note?.author ?? "");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-card border border-border rounded-xl shadow-xl w-full max-w-lg mx-4 flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <span className="text-sm font-semibold">{title}</span>
          <button onClick={onClose} className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-4 flex flex-col gap-3">
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Description (optional)</label>
            <input
              className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              placeholder="What is this note about?"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Author (optional)</label>
            <input
              className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              placeholder="Name or role"
              value={author}
              onChange={(e) => setAuthor(e.target.value)}
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Content</label>
            <textarea
              className="w-full h-40 resize-none bg-background border border-border rounded-lg px-3 py-2 text-sm font-mono text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              placeholder="Note content…"
              value={content}
              onChange={(e) => setContent(e.target.value)}
            />
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-border">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded-lg border border-border hover:bg-accent transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => onSave({ content, description, author })}
            disabled={saving || !content.trim()}
            className="px-3 py-1.5 text-sm rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-40 flex items-center gap-1.5"
          >
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

// ── View Modal ───────────────────────────────────────────────────────────────
function NoteViewModal({ note, onClose, onEdit }: { note: ChatNote; onClose: () => void; onEdit: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-card border border-border rounded-xl shadow-xl w-full max-w-lg mx-4 flex flex-col max-h-[80vh]">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
          <div className="flex flex-col gap-0.5 min-w-0">
            {note.description && (
              <span className="text-sm font-semibold truncate">{note.description}</span>
            )}
            <span className="text-xs text-muted-foreground">
              {note.author || "Unknown"} · {formatDate(note.created_at)}
            </span>
          </div>
          <div className="flex items-center gap-1 shrink-0 ml-2">
            <button
              onClick={onEdit}
              className="p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
              title="Edit"
            >
              <Pencil className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
        <div className="p-4 overflow-y-auto flex-1">
          <pre className="text-sm font-mono text-foreground whitespace-pre-wrap break-words">{note.content}</pre>
        </div>
      </div>
    </div>
  );
}

// ── Main Panel ───────────────────────────────────────────────────────────────
export function NotesPanel({ chatId, onClose }: NotesPanelProps) {
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [viewNote, setViewNote] = useState<ChatNote | null>(null);
  const [editNote, setEditNote] = useState<ChatNote | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  const queryKey = ["chat-notes", chatId, page];

  const { data, isLoading } = useQuery({
    queryKey,
    queryFn: () => chatsApi.getNotes(chatId, page, PAGE_SIZE).then((r) => r.data),
    enabled: !!chatId,
    staleTime: 10_000,
  });

  const notes: ChatNote[] = data?.notes ?? [];
  const total: number = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const invalidate = useCallback(() => {
    qc.invalidateQueries({ queryKey: ["chat-notes", chatId] });
  }, [qc, chatId]);

  const createMut = useMutation({
    mutationFn: (d: { content: string; description: string; author: string }) =>
      chatsApi.createNote(chatId, d),
    onSuccess: () => { toast.success("Note added"); setShowCreate(false); invalidate(); },
    onError: () => toast.error("Failed to add note"),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: { content?: string; description?: string; author?: string } }) =>
      chatsApi.updateNote(chatId, id, data),
    onSuccess: () => { toast.success("Note updated"); setEditNote(null); setViewNote(null); invalidate(); },
    onError: () => toast.error("Failed to update note"),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => chatsApi.deleteNote(chatId, id),
    onSuccess: () => { toast.success("Note deleted"); setDeleteConfirm(null); invalidate(); },
    onError: () => toast.error("Failed to delete note"),
  });

  return (
    <Fragment>
      <div className="flex flex-col h-full w-72 border-l border-border bg-card shrink-0 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-3 py-2.5 border-b border-border shrink-0">
          <div className="flex items-center gap-2">
            <NotebookPen className="w-3.5 h-3.5 text-muted-foreground" />
            <span className="text-xs font-semibold">Chat Notes</span>
            {total > 0 && (
              <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded-full">{total}</span>
            )}
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setShowCreate(true)}
              title="Add note"
              className="p-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
            >
              <Plus className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={onClose}
              className="p-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* List */}
        {isLoading ? (
          <div className="flex items-center justify-center flex-1">
            <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
          </div>
        ) : notes.length === 0 ? (
          <div className="flex flex-col items-center justify-center flex-1 gap-2 text-muted-foreground px-4">
            <NotebookPen className="w-8 h-8 opacity-30" />
            <p className="text-xs text-center">No notes yet. Agents and users can add notes here.</p>
            <button
              onClick={() => setShowCreate(true)}
              className="mt-1 text-xs px-3 py-1.5 rounded-lg border border-border hover:bg-accent transition-colors"
            >
              Add first note
            </button>
          </div>
        ) : (
          <div className="flex flex-col flex-1 min-h-0 overflow-y-auto divide-y divide-border">
            {notes.map((note) => (
              <div
                key={note.id}
                className="group px-3 py-2.5 hover:bg-accent/40 cursor-pointer transition-colors"
                onClick={() => setViewNote(note)}
              >
                <div className="flex items-start justify-between gap-1">
                  <div className="flex flex-col gap-0.5 min-w-0 flex-1">
                    {note.description && (
                      <span className="text-xs font-medium text-foreground truncate">{note.description}</span>
                    )}
                    <span className="text-[10px] text-muted-foreground">
                      {note.author || "Unknown"} · {formatDate(note.created_at)}
                    </span>
                    <p className="text-[11px] text-muted-foreground line-clamp-2 mt-0.5 font-mono">
                      {note.content}
                    </p>
                  </div>
                  <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0 ml-1">
                    <button
                      onClick={(e) => { e.stopPropagation(); setEditNote(note); }}
                      className="p-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
                      title="Edit"
                    >
                      <Pencil className="w-3 h-3" />
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); setDeleteConfirm(note.id); }}
                      className="p-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-destructive"
                      title="Delete"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between px-3 py-2 border-t border-border shrink-0">
            <button
              disabled={page === 1}
              onClick={() => setPage((p) => p - 1)}
              className="p-1 rounded hover:bg-accent disabled:opacity-30 transition-colors"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
            </button>
            <span className="text-[10px] text-muted-foreground">
              {page} / {totalPages}
            </span>
            <button
              disabled={page === totalPages}
              onClick={() => setPage((p) => p + 1)}
              className="p-1 rounded hover:bg-accent disabled:opacity-30 transition-colors"
            >
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        <p className="text-[10px] text-muted-foreground text-center px-3 py-2 shrink-0 border-t border-border">
          Shared across all sub-agents
        </p>
      </div>

      {/* Delete confirm */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-card border border-border rounded-xl shadow-xl p-5 w-72 flex flex-col gap-4">
            <p className="text-sm font-medium">Delete this note?</p>
            <p className="text-xs text-muted-foreground">This cannot be undone.</p>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="px-3 py-1.5 text-xs rounded-lg border border-border hover:bg-accent transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => deleteMut.mutate(deleteConfirm)}
                disabled={deleteMut.isPending}
                className="px-3 py-1.5 text-xs rounded-lg bg-destructive text-destructive-foreground hover:bg-destructive/90 transition-colors disabled:opacity-40"
              >
                {deleteMut.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* View modal */}
      {viewNote && !editNote && (
        <NoteViewModal
          note={viewNote}
          onClose={() => setViewNote(null)}
          onEdit={() => setEditNote(viewNote)}
        />
      )}

      {/* Edit modal */}
      {editNote && (
        <NoteModal
          title="Edit Note"
          note={editNote}
          saving={updateMut.isPending}
          onClose={() => setEditNote(null)}
          onSave={(d) => updateMut.mutate({ id: editNote.id, data: d })}
        />
      )}

      {/* Create modal */}
      {showCreate && (
        <NoteModal
          title="Add Note"
          saving={createMut.isPending}
          onClose={() => setShowCreate(false)}
          onSave={(d) => createMut.mutate(d)}
        />
      )}
    </Fragment>
  );
}
