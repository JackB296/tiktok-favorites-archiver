import { useState } from "react";

export interface DryRunPending<T> {
  payload: T;
  /** How many records the dry run said the action would change. */
  matched: number;
}

export interface DryRunConfirmConfig<T> {
  /** Dry-run the action; resolves to how many records it would change. */
  preview: (payload: T) => Promise<number>;
  /** Run the action for real; resolves to the status message to show. */
  apply: (payload: T) => Promise<string>;
  /** Shown when the dry run matches nothing. */
  emptyMessage: string;
  /** Shown when the user dismisses the confirmation; omit to stay quiet. */
  cancelMessage?: string;
}

/** The preview → ConfirmDialog → apply machine shared by bulk mark actions:
    dry-run for a count, hold it as `pending` while the user confirms, then
    apply — one busy flag and one status message across both steps. */
export function useDryRunConfirm<T>(config: DryRunConfirmConfig<T>) {
  const [pending, setPending] = useState<DryRunPending<T> | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function request(payload: T) {
    if (busy) return;
    setBusy(true);
    setMessage(null);
    try {
      const matched = await config.preview(payload);
      if (!matched) {
        setMessage(config.emptyMessage);
        return;
      }
      setPending({ payload, matched });
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!pending || busy) return;
    setBusy(true);
    try {
      setMessage(await config.apply(pending.payload));
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setPending(null);
      setBusy(false);
    }
  }

  function cancel() {
    if (busy) return; // the apply is in flight — Escape must not report "cancelled"
    setPending(null);
    if (config.cancelMessage !== undefined) setMessage(config.cancelMessage);
  }

  return { pending, busy, message, setMessage, request, confirm, cancel };
}
