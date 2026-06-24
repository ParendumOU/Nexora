import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(date: string | Date): string {
  const d = typeof date === "string" ? new Date(date) : date;
  const now = new Date();
  const diff = now.getTime() - d.getTime();
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);

  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  if (hours < 24) return `${hours}h ago`;
  if (days < 7) return `${days}d ago`;
  return d.toLocaleDateString();
}

export function truncate(str: string, maxLength: number): string {
  return str.length > maxLength ? str.slice(0, maxLength) + "…" : str;
}

export function getWsUrl(chatId: string): string {
  const token = localStorage.getItem("access_token") || "";
  const isSecure = window.location.protocol === "https:";
  const wsProto = isSecure ? "wss" : "ws";
  const host = window.location.host;
  return `${wsProto}://${host}/ws/chat/${chatId}?token=${token}`;
}

export function getUserWsUrl(): string {
  const token = localStorage.getItem("access_token") || "";
  const isSecure = window.location.protocol === "https:";
  const wsProto = isSecure ? "wss" : "ws";
  const host = window.location.host;
  return `${wsProto}://${host}/ws/user?token=${token}`;
}

export async function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const el = document.createElement("textarea");
  el.value = text;
  el.style.cssText = "position:fixed;opacity:0;pointer-events:none";
  document.body.appendChild(el);
  el.select();
  document.execCommand("copy");
  document.body.removeChild(el);
}
