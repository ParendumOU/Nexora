"use client";
import { X, ArrowRight, MapPin } from "lucide-react";
import { cn } from "@/lib/utils";

interface Step {
  title: string;
  description: string;
}

interface TourBannerProps {
  label: string;
  steps: readonly Step[];
  currentStep: number;
  isActive: boolean;
  isLast: boolean;
  onGoTo: (step: number) => void;
  onNext: () => void;
  onDismiss: () => void;
  lastLabel?: string;
}

export function TourBanner({ label, steps, currentStep, isActive, isLast, onGoTo, onNext, onDismiss, lastLabel = "Finish" }: TourBannerProps) {
  if (!isActive) return null;

  const step = steps[currentStep];
  const total = steps.length;

  return (
    <div className="fixed bottom-6 right-6 z-50 w-80 bg-card border border-border rounded-2xl shadow-xl overflow-hidden animate-in slide-in-from-bottom-4 duration-300">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-muted/30">
        <div className="flex items-center gap-2">
          <MapPin className="w-3.5 h-3.5 text-primary" />
          <span className="text-xs font-semibold text-foreground">{label}</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground">{currentStep + 1} / {total}</span>
          <button onClick={onDismiss} className="text-muted-foreground hover:text-foreground transition-colors" aria-label="Dismiss tour">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Step dots */}
      <div className="flex gap-1.5 px-4 pt-3 flex-wrap">
        {steps.map((_, i) => (
          <button
            key={i}
            onClick={() => onGoTo(i)}
            className={cn(
              "h-1.5 rounded-full transition-all",
              i === currentStep ? "bg-primary w-6" : i < currentStep ? "bg-primary/40 w-1.5" : "bg-muted-foreground/20 w-1.5"
            )}
            aria-label={`Go to step ${i + 1}`}
          />
        ))}
      </div>

      {/* Content */}
      <div className="px-4 py-3">
        <p className="text-sm font-semibold text-foreground mb-1">{step.title}</p>
        <p className="text-xs text-muted-foreground leading-relaxed">{step.description}</p>
      </div>

      {/* Actions */}
      <div className="flex items-center justify-between px-4 pb-4">
        <button onClick={onDismiss} className="text-xs text-muted-foreground hover:text-foreground transition-colors">
          Skip tour
        </button>
        <button
          onClick={onNext}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-primary-foreground text-xs font-medium hover:bg-primary/90 transition-colors"
        >
          {isLast ? lastLabel : "Next"}
          <ArrowRight className="w-3 h-3" />
        </button>
      </div>
    </div>
  );
}
