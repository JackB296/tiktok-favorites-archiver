import { useEffect, useState } from "react";
import { removeById, sortedInsert } from "./savedList";

export interface SavedListMessages {
  /** Shown when the initial load fails; omit to fail silently. */
  loadError?: string;
  /** Shown after a successful save; omit to clear any prior message instead. */
  saved?: string;
  /** Shown after a successful delete; omit to leave the message untouched. */
  deleted?: string;
}

export interface SavedListConfig<T extends { id: number; name: string }> {
  load: () => Promise<T[]>;
  /** Create the entry on the server; the caller closes over any extra payload
      (preset filters, term lists, item id arrays, …). Receives the trimmed name. */
  create: (name: string) => Promise<T>;
  remove: (id: number) => Promise<unknown>;
  messages?: SavedListMessages;
}

/** The saved-list state machine previously copy-pasted four times: a named
    server-side list with load-on-mount, create-with-sorted-insert,
    delete-with-filter-out, and a status/error message. */
export function useSavedList<T extends { id: number; name: string }>(config: SavedListConfig<T>) {
  const [items, setItems] = useState<T[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [name, setName] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    config.load().then((loaded) => {
      if (alive) setItems(loaded);
    }).catch(() => {
      if (alive && config.messages?.loadError) setMessage(config.messages.loadError);
    });
    return () => { alive = false; };
    // Load once on mount, like every hand-rolled copy did — `config` is
    // captured at first render, so `load` must be a stable reference.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Returns the created entry, or null when skipped or failed. */
  async function save(): Promise<T | null> {
    const trimmed = name.trim();
    if (!trimmed) return null;
    try {
      const saved = await config.create(trimmed);
      setItems((current) => sortedInsert(current, saved));
      setSelectedId(String(saved.id));
      setName("");
      setMessage(config.messages?.saved ?? null);
      return saved;
    } catch (error) {
      setMessage((error as Error).message);
      return null;
    }
  }

  /** Deletes `id`, or the selected entry when omitted. Resolves to whether the
      delete went through, so callers can skip their own follow-up on failure. */
  async function remove(id?: number): Promise<boolean> {
    const target = id ?? Number(selectedId);
    if (!target) return false;
    try {
      await config.remove(target);
      setItems((current) => removeById(current, target));
      setSelectedId("");
      if (config.messages?.deleted !== undefined) setMessage(config.messages.deleted);
      return true;
    } catch (error) {
      setMessage((error as Error).message);
      return false;
    }
  }

  return { items, selectedId, setSelectedId, name, setName, message, setMessage, save, remove };
}
