import { useId } from "react";
import type { ReactNode, ButtonHTMLAttributes } from "react";
import type { Status } from "../lib/types";

export function cx(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

type ButtonVariant = "primary" | "ghost" | "danger";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-accent text-on-accent hover:bg-accent-strong",
  ghost: "border border-line bg-transparent text-ink-dim hover:text-ink hover:bg-elevated",
  danger: "border border-bad/40 bg-transparent text-bad hover:bg-bad/10",
};

export function Button({ variant = "primary", className, ...props }: ButtonProps) {
  return (
    <button
      className={cx(
        "inline-flex h-10 items-center justify-center gap-2 rounded-[var(--radius-control)] px-4 text-sm font-medium",
        "transition-[background,color,transform] duration-150 active:translate-y-px",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60",
        "disabled:pointer-events-none disabled:opacity-40",
        VARIANTS[variant],
        className,
      )}
      {...props}
    />
  );
}

const STATUS_COLOR: Record<Status, string> = {
  done: "text-ok",
  downloading: "text-active",
  resolving: "text-active",
  pending: "text-ink-faint",
  failed: "text-bad",
  expired: "text-ink-faint",
  skipped: "text-ink-faint",
  ignored: "text-ink-faint",
};

const STATUS_LABEL: Partial<Record<Status, string>> = { done: "ready", expired: "unavailable" };

export function StatusBadge({ status }: { status: Status }) {
  return (
    <span className={cx("inline-flex items-center gap-1.5 text-xs font-medium", STATUS_COLOR[status])}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

export function Stat({ label, value, hint }: { label: string; value: string | number; hint: string }) {
  return <div className="rounded-[var(--radius-control)] border border-line bg-elevated px-3 py-3"><p className="text-xs text-ink-faint">{label}</p><p className="mt-1 truncate text-lg font-semibold text-ink">{value}</p><p className="mt-0.5 truncate text-xs text-ink-dim">{hint}</p></div>;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("animate-pulse rounded-[var(--radius-control)] bg-elevated", className)} />;
}

export function HelpLabel({ children, help }: { children: ReactNode; help: string }) {
  const id = useId();
  return <span className="group/help relative inline-flex w-fit items-center gap-1" tabIndex={0} aria-describedby={id}>
    <span className="border-b border-dotted border-ink-faint/60">{children}</span>
    <span aria-hidden="true" className="text-[10px] text-ink-faint">?</span>
    <span id={id} role="tooltip" className="pointer-events-none invisible absolute bottom-full left-0 z-50 mb-2 w-64 rounded-[var(--radius-control)] border border-line bg-elevated px-3 py-2 text-left text-xs font-normal leading-relaxed text-ink opacity-0 shadow-xl transition group-hover/help:visible group-hover/help:opacity-100 group-focus/help:visible group-focus/help:opacity-100">{help}</span>
  </span>;
}

export function EmptyState({ icon, title, hint }: { icon?: ReactNode; title: string; hint?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-24 text-center">
      {icon && <div className="text-ink-faint">{icon}</div>}
      <p className="text-lg font-medium text-ink">{title}</p>
      {hint && <p className="max-w-sm text-sm text-ink-dim">{hint}</p>}
    </div>
  );
}
