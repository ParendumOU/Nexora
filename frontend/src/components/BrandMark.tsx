import { useId } from "react";

export function BrandMark({ className = "h-8 w-8" }: { className?: string }) {
  const id = useId();
  return (
    <svg className={className} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#1e40af" />
          <stop offset="0.55" stopColor="#3b5bdb" />
          <stop offset="1" stopColor="#4f46e5" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill={`url(#${id})`} />
      <g stroke="#ffffff" strokeLinecap="round" strokeWidth="2.1" fill="none">
        <line x1="10" y1="24" x2="10" y2="8" />
        <line x1="10" y1="8" x2="22" y2="24" />
        <line x1="22" y1="24" x2="22" y2="8" />
      </g>
      <g fill="#ffffff">
        <circle cx="10" cy="8" r="2.7" />
        <circle cx="22" cy="24" r="2.7" />
        <circle cx="10" cy="24" r="2" />
        <circle cx="22" cy="8" r="2" />
        <circle cx="16" cy="16" r="1.7" />
      </g>
    </svg>
  );
}
