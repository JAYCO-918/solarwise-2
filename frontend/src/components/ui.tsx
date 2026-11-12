import { AlertTriangle, Info, Loader2, RotateCw } from "lucide-react";
import { useId } from "react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import { Link } from "react-router";

import type { ApiError } from "../api/client";
import { cx } from "../lib/cx";

// ----------------------------------------------------------------------------- buttons

type Variant = "primary" | "secondary" | "ghost" | "danger";

const BUTTON_BASE =
  "inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors " +
  "disabled:cursor-not-allowed disabled:opacity-50 whitespace-nowrap";

const BUTTON_VARIANT: Record<Variant, string> = {
  primary: "bg-ink-900 text-white hover:bg-ink-800",
  secondary: "border border-ink-300 bg-white text-ink-900 hover:bg-ink-50",
  ghost: "text-ink-700 hover:bg-ink-100",
  danger: "border border-rose-300 bg-white text-rose-800 hover:bg-rose-50",
};

const BUTTON_SIZE = { sm: "px-2.5 py-1.5 text-sm", md: "px-3.5 py-2 text-sm", lg: "px-5 py-2.5 text-base" };

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: keyof typeof BUTTON_SIZE;
  busy?: boolean;
}

export function Button({ variant = "secondary", size = "md", busy = false, className, children, disabled, ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      {...rest}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={cx(BUTTON_BASE, BUTTON_VARIANT[variant], BUTTON_SIZE[size], className)}
    >
      {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function LinkButton({
  to, variant = "secondary", size = "md", className, children,
}: { to: string; variant?: Variant; size?: keyof typeof BUTTON_SIZE; className?: string; children: ReactNode }) {
  return (
    <Link to={to} className={cx(BUTTON_BASE, BUTTON_VARIANT[variant], BUTTON_SIZE[size], className)}>
      {children}
    </Link>
  );
}

// ----------------------------------------------------------------------------- layout blocks

export function Card({ children, className, as: Tag = "section", ...rest }: {
  children: ReactNode; className?: string; as?: "section" | "div" | "article"; id?: string; "aria-labelledby"?: string;
}) {
  return (
    <Tag {...rest} className={cx("rounded-lg border border-ink-200 bg-white", className)}>
      {children}
    </Tag>
  );
}

export function CardHeader({ title, description, actions, id }: {
  title: ReactNode; description?: ReactNode; actions?: ReactNode; id?: string;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-ink-100 px-5 py-4">
      <div className="min-w-0">
        <h2 id={id} className="text-base font-semibold text-ink-900">{title}</h2>
        {description && <p className="mt-1 max-w-3xl text-sm text-ink-600">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function PageHeader({ title, eyebrow, description, actions }: {
  title: ReactNode; eyebrow?: ReactNode; description?: ReactNode; actions?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1 text-sm text-ink-500">{eyebrow}</div>}
        <h1 className="text-2xl font-semibold tracking-tight text-ink-950">{title}</h1>
        {description && <p className="mt-2 max-w-3xl text-ink-600">{description}</p>}
      </div>
      {actions && <div className="no-print flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Badge({ children, className, title }: { children: ReactNode; className?: string; title?: string }) {
  return (
    <span
      title={title}
      className={cx("inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs font-medium leading-5", className)}
    >
      {children}
    </span>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-medium uppercase tracking-wide text-ink-500">{label}</dt>
      <dd className="tabular mt-1 text-xl font-semibold text-ink-950">{value}</dd>
      {hint && <dd className="mt-0.5 text-xs text-ink-500">{hint}</dd>}
    </div>
  );
}

export function DefinitionList({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-[minmax(10rem,14rem)_1fr]">
      {items.map(([term, definition]) => (
        <div key={term} className="contents">
          <dt className="text-ink-500">{term}</dt>
          <dd className="min-w-0 break-words text-ink-900">{definition}</dd>
        </div>
      ))}
    </dl>
  );
}

// ----------------------------------------------------------------------------- states

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 px-5 py-8 text-sm text-ink-500">
      <Loader2 className="size-4 animate-spin" aria-hidden />
      {label}…
    </div>
  );
}

export function ErrorNote({ error, onRetry }: { error: ApiError | Error; onRetry?: () => void }) {
  const code = "code" in error ? error.code : null;
  return (
    <div role="alert" className="flex items-start gap-3 rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="break-words">{error.message}</p>
        {code && <p className="mt-0.5 font-mono text-xs text-rose-700">{code}</p>}
      </div>
      {onRetry && (
        <Button size="sm" onClick={onRetry}>
          <RotateCw className="size-3.5" aria-hidden /> Retry
        </Button>
      )}
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="px-5 py-10 text-center">
      <p className="font-medium text-ink-900">{title}</p>
      {children && <div className="mx-auto mt-1 max-w-xl text-sm text-ink-600">{children}</div>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

type NoticeTone = "info" | "warning" | "danger" | "simulated" | "neutral";

const NOTICE_TONE: Record<NoticeTone, string> = {
  info: "border-sky-200 bg-sky-50 text-sky-950",
  warning: "border-amber-300 bg-amber-50 text-amber-950",
  danger: "border-rose-300 bg-rose-50 text-rose-950",
  simulated: "border-violet-300 bg-violet-50 text-violet-950 simulated-stripes",
  neutral: "border-ink-200 bg-ink-50 text-ink-800",
};

export function Notice({ tone = "info", title, children, className }: {
  tone?: NoticeTone; title?: ReactNode; children?: ReactNode; className?: string;
}) {
  const Icon = tone === "warning" || tone === "danger" ? AlertTriangle : Info;
  return (
    <div
      role={tone === "danger" ? "alert" : undefined}
      className={cx("flex items-start gap-3 rounded-md border px-4 py-3 text-sm", NOTICE_TONE[tone], className)}
    >
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={cx(title ? "mt-0.5" : "", "break-words")}>{children}</div>}
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------- form controls

const CONTROL =
  "block w-full rounded-md border border-ink-300 bg-white px-3 py-2 text-sm text-ink-900 placeholder:text-ink-400 " +
  "disabled:bg-ink-50 disabled:text-ink-500 aria-[invalid=true]:border-rose-500";

export function Field({ label, hint, error, optional, children, className }: {
  label: string; hint?: ReactNode; error?: string | null; optional?: boolean;
  children: (props: { id: string; "aria-describedby"?: string; "aria-invalid"?: boolean }) => ReactNode;
  className?: string;
}) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ") || undefined;
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-ink-800">
        {label}
        {optional && <span className="ml-1 font-normal text-ink-500">(optional)</span>}
      </label>
      {children({ id, "aria-describedby": describedBy, "aria-invalid": error ? true : undefined })}
      {hint && <p id={hintId} className="mt-1 text-xs text-ink-500">{hint}</p>}
      {error && <p id={errorId} className="mt-1 text-xs font-medium text-rose-700">{error}</p>}
    </div>
  );
}

export function TextInput({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input type="text" {...rest} className={cx(CONTROL, className)} />;
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select {...rest} className={cx(CONTROL, "pr-8", className)}>
      {children}
    </select>
  );
}

export function Textarea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea rows={3} {...rest} className={cx(CONTROL, className)} />;
}

export function Checkbox({ label, hint, ...rest }: InputHTMLAttributes<HTMLInputElement> & { label: ReactNode; hint?: ReactNode }) {
  const id = useId();
  return (
    <div className="flex items-start gap-2">
      <input id={id} type="checkbox" {...rest} className="mt-1 size-4 rounded border-ink-300 text-ink-900" />
      <div>
        <label htmlFor={id} className="text-sm text-ink-900">{label}</label>
        {hint && <p className="text-xs text-ink-500">{hint}</p>}
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------- tables

export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return (
    // `relative`: visually hidden labels inside the table are absolutely positioned; without a positioned ancestor they
    // escape the scrolling box and make the whole page scroll sideways on a narrow screen.
    <div className="relative overflow-x-auto">
      <table className={cx("w-full border-collapse text-left text-sm", className)}>{children}</table>
    </div>
  );
}

export function Th({ children, className, numeric }: { children?: ReactNode; className?: string; numeric?: boolean }) {
  return (
    <th scope="col" className={cx("border-b border-ink-200 px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-ink-500", numeric && "text-right", className)}>
      {children}
    </th>
  );
}

export function Td({ children, className, numeric }: { children?: ReactNode; className?: string; numeric?: boolean }) {
  return (
    <td className={cx("border-b border-ink-100 px-4 py-2.5 align-top", numeric && "tabular text-right", className)}>
      {children}
    </td>
  );
}

// ----------------------------------------------------------------------------- tabs

export interface TabItem {
  key: string;
  label: ReactNode;
}

export function Tabs({ items, active, onChange, label }: {
  items: TabItem[]; active: string; onChange: (key: string) => void; label: string;
}) {
  return (
    <div role="tablist" aria-label={label} className="no-print relative flex gap-1 overflow-x-auto border-b border-ink-200">
      {items.map((item) => {
        const selected = item.key === active;
        return (
          <button
            key={item.key}
            role="tab"
            type="button"
            id={`tab-${item.key}`}
            aria-selected={selected}
            aria-controls={`panel-${item.key}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(item.key)}
            onKeyDown={(event) => {
              if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
              const index = items.findIndex((i) => i.key === active);
              const next = items[(index + (event.key === "ArrowRight" ? 1 : items.length - 1)) % items.length];
              if (next) {
                onChange(next.key);
                document.getElementById(`tab-${next.key}`)?.focus();
              }
            }}
            className={cx(
              "-mb-px whitespace-nowrap border-b-2 px-3.5 py-2.5 text-sm font-medium",
              selected ? "border-ink-900 text-ink-950" : "border-transparent text-ink-500 hover:text-ink-800",
            )}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel({ tab, active, children }: { tab: string; active: string; children: ReactNode }) {
  if (tab !== active) return null;
  return (
    <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="pt-6">
      {children}
    </div>
  );
}
