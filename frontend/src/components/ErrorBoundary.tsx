"use client";

import { Component, type ReactNode, type ErrorInfo } from "react";
import { AlertTriangle } from "lucide-react";

interface Props {
  children: ReactNode;
  /** Heading shown when a child throws. */
  fallbackTitle?: string;
  /** Optional close handler (e.g. to dismiss a side panel). */
  onClose?: () => void;
  /** Remount children when this value changes (e.g. the open resource id). */
  resetKey?: unknown;
}

interface State {
  error: Error | null;
}

/**
 * Contains a render-time exception so it degrades to an inline message instead of
 * crashing the whole app ("Application error: a client-side exception has occurred").
 * It also SHOWS the error message, so the actual cause is visible without opening devtools.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Surface to the console for full stack; the inline UI shows the message.
    console.error("[ErrorBoundary]", error, info);
  }

  componentDidUpdate(prev: Props) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  reset = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      return (
        <div className="flex flex-col h-full items-center justify-center gap-3 p-6 text-center border-l border-border bg-card shrink-0">
          <AlertTriangle className="w-6 h-6 text-orange-400" />
          <p className="text-sm font-medium text-foreground">
            {this.props.fallbackTitle ?? "Something went wrong"}
          </p>
          <p className="text-[11px] text-muted-foreground font-mono break-words max-w-full">
            {this.state.error.message || String(this.state.error)}
          </p>
          <div className="flex gap-2">
            <button
              onClick={this.reset}
              className="text-xs px-2.5 py-1 rounded bg-accent hover:bg-accent/70 transition-colors"
            >
              Retry
            </button>
            {this.props.onClose && (
              <button
                onClick={this.props.onClose}
                className="text-xs px-2.5 py-1 rounded bg-accent hover:bg-accent/70 transition-colors"
              >
                Close
              </button>
            )}
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
