import { useEffect, useId, useRef } from "react";
import type { ReactNode, ButtonHTMLAttributes, RefObject } from "react";
import type { Status } from "../lib/types";

export function cx(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

type ButtonVariant = "primary" | "ghost" | "danger";
type ButtonSize = "md" | "sm" | "xs";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-accent text-on-accent hover:bg-accent-strong",
  ghost: "border border-line bg-transparent text-ink-dim hover:text-ink hover:bg-elevated",
  danger: "border border-bad/40 bg-transparent text-bad hover:bg-bad/10",
};

const SIZES: Record<ButtonSize, string> = {
  md: "h-10 gap-2 px-4 text-sm",
  sm: "h-9 gap-1.5 px-3 text-sm",
  xs: "h-8 gap-1.5 px-2.5 text-xs",
};

export function Button({ variant = "primary", size = "md", className, ...props }: ButtonProps) {
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center rounded-[var(--radius-control)] font-medium",
        "transition-[background,color,transform] duration-150 active:translate-y-px",
        "disabled:pointer-events-none disabled:opacity-40",
        SIZES[size],
        VARIANTS[variant],
        className,
      )}
      {...props}
    />
  );
}

/** Keeps Tab / Shift+Tab cycling inside an open dialog instead of escaping to the page behind it. */
export function useDialogFocusTrap(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const focusables = node.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (!focusables.length) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    node.addEventListener("keydown", onKeyDown);
    return () => node.removeEventListener("keydown", onKeyDown);
  }, [ref]);
}

/** Shared modal scaffold: dimmed overlay, dialog semantics, focus trap, Escape
    to close, and initial focus. Callers render their own panel as children. */
export function Dialog({ role = "dialog", labelledBy, describedBy, onClose, closeDisabled = false, initialFocusRef, className, children }: {
  role?: "dialog" | "alertdialog";
  labelledBy: string;
  describedBy?: string;
  onClose: () => void;
  /** Ignore Escape (e.g. while a mutation is in flight). */
  closeDisabled?: boolean;
  /** Focused once when the dialog mounts. */
  initialFocusRef?: RefObject<HTMLElement | null>;
  /** Overlay extras — the backdrop tint differs between dialogs. */
  className?: string;
  children: ReactNode;
}) {
  const overlayRef = useRef<HTMLDivElement>(null);
  useDialogFocusTrap(overlayRef);
  useEffect(() => {
    initialFocusRef?.current?.focus();
    // Initial focus happens once on mount, not on later re-renders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !closeDisabled) onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, closeDisabled]);
  return (
    <div ref={overlayRef} role={role} aria-modal="true" aria-labelledby={labelledBy} aria-describedby={describedBy} className={cx("fixed inset-0 z-50 flex items-center justify-center p-4", className)}>
      {children}
    </div>
  );
}

export function ConfirmDialog({ title = "Please confirm", message, confirmLabel, busy = false, onConfirm, onCancel }: {
  title?: string;
  message: string;
  confirmLabel: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const titleId = useId();
  const messageId = useId();
  return (
    <Dialog role="alertdialog" labelledBy={titleId} describedBy={messageId} onClose={onCancel} closeDisabled={busy} className="bg-black/70">
      <div className="w-full max-w-sm rounded-[var(--radius-media)] border border-line bg-surface p-5 shadow-2xl">
        <h2 id={titleId} className="text-base font-semibold text-ink">{title}</h2>
        <p id={messageId} className="mt-2 text-sm leading-relaxed text-ink-dim">{message}</p>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onCancel} disabled={busy}>Cancel</Button>
          <Button size="sm" onClick={onConfirm} disabled={busy} autoFocus>{busy ? "Working…" : confirmLabel}</Button>
        </div>
      </div>
    </Dialog>
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
    <span id={id} role="tooltip" className="pointer-events-none invisible absolute bottom-full left-0 z-50 mb-2 w-64 rounded-[var(--radius-control)] border border-line bg-elevated px-3 py-2 text-left text-xs font-normal leading-relaxed text-ink opacity-0 shadow-xl transition group-hover/help:visible group-hover/help:opacity-100 group-hover/help:delay-700 group-focus/help:visible group-focus/help:opacity-100 group-focus/help:delay-0">{help}</span>
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
