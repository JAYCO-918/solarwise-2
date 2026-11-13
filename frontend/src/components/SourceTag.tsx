import { Bot, Cpu } from "lucide-react";

import { cx } from "../lib/cx";

/**
 * Who produced a piece of content: the deterministic engine, or a language model.
 * The two never look alike - an operator must be able to tell an engineering result from an interpretation at a glance.
 */
export function SourceTag({ source, children, className }: {
  source: "engine" | "ai";
  children?: string;
  className?: string;
}) {
  const ai = source === "ai";
  const Icon = ai ? Bot : Cpu;
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs font-medium leading-5",
        ai ? "border-indigo-300 bg-indigo-50 text-indigo-900" : "border-ink-300 bg-white text-ink-700",
        className,
      )}
    >
      <Icon className="size-3.5" aria-hidden />
      {children ?? (ai ? "AI interpretation" : "Engine")}
    </span>
  );
}
