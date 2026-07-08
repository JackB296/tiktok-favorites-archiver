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
};

export function StatusBadge({ status }: { status: Status }) {
  return (
    <span className={cx("inline-flex items-center gap-1.5 text-xs font-medium", STATUS_COLOR[status])}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
      {status}
    </span>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("animate-pulse rounded-[var(--radius-control)] bg-elevated", className)} />;
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
