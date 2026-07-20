import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowClockwise,
  FileArrowUp,
  MagnifyingGlass,
  Microphone,
  Pause,
  Play,
  Scan,
  Stop,
  TextT,
} from "@phosphor-icons/react";
import { api } from "../lib/api";
import type {
  AnalysisSourceCoverage,
  LensResult,
  LensStatus,
  PipelineSettings,
  ProgressEvent,
  RunStatus,
} from "../lib/types";
import { Button, EmptyState, Skeleton, cx } from "../components/ui";
import { formatMediaTime } from "../lib/format";
import {
  analysisCompletionMessage,
  analysisCoverageLabel,
  analysisProgressLabel,
  automaticAnalysisPhases,
  lensSnippetParts,
  lensSourceLabel,
} from "../lib/lensPresentation.js";

function ResultRow({ result }: { result: LensResult }) {
  const title = result.item.caption?.trim()
    || (result.item.author ? `@${result.item.author}` : `Favorite #${result.item.id}`);
  return (
    <li className="grid gap-3 border-b border-line py-4 sm:grid-cols-[5rem_minmax(0,1fr)_auto] sm:items-center">
      {result.item.thumbnail_url ? (
        <img src={result.item.thumbnail_url} alt="" className="h-24 w-20 rounded-[var(--radius-control)] bg-elevated object-cover" />
      ) : (
        <span aria-hidden className="flex h-24 w-20 items-center justify-center rounded-[var(--radius-control)] bg-elevated text-ink-faint"><Scan size={22} /></span>
      )}
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold text-ink">{title}</p>
        <p className="mt-1 text-sm leading-relaxed text-ink-dim">
          {lensSnippetParts(result.snippet).map((part, index) => part.highlight
            ? <mark key={index} className="rounded bg-accent/20 px-0.5 text-ink">{part.text}</mark>
            : <span key={index}>{part.text}</span>)}
        </p>
        <p className="mt-2 flex flex-wrap items-center gap-2 text-xs text-ink-faint">
          <span>{lensSourceLabel(result.source)}</span>
          <span>·</span>
          <span>{formatMediaTime(result.start_s)}</span>
          {result.item.author && <><span>·</span><span>@{result.item.author}</span></>}
        </p>
      </div>
      <Link to={result.feed_url} className="inline-flex h-9 items-center justify-center gap-1.5 rounded-[var(--radius-control)] bg-accent px-3 text-sm font-medium text-on-accent transition hover:bg-accent-strong">
        <Play size={14} weight="fill" /> Jump to match
      </Link>
    </li>
  );
}

type AnalysisAction = "analyze" | "pause" | "continue" | "stop";

function CoverageCard({ label, icon, coverage, eligible }: {
  label: string;
  icon: React.ReactNode;
  coverage: AnalysisSourceCoverage;
  eligible: number;
}) {
  return (
    <div className="rounded-[var(--radius-control)] border border-line bg-elevated p-3">
      <div className="flex items-center gap-2 text-xs font-semibold text-ink">{icon}{label}</div>
      <p className="mt-2 text-sm text-ink">{analysisCoverageLabel(coverage, eligible)}</p>
      <p className="mt-1 text-xs text-ink-faint">{coverage.generated} generated here · {coverage.manual} manually imported</p>
    </div>
  );
}

function AnalysisPanel({ status, runStatus, pipeline, progress, busy, savingAutomatic, onAction, onAutomaticChange }: {
  status: LensStatus | null;
  runStatus: RunStatus | null;
  pipeline: PipelineSettings | null;
  progress: ProgressEvent | null;
  busy: boolean;
  savingAutomatic: boolean;
  onAction: (action: AnalysisAction) => void;
  onAutomaticChange: (enabled: boolean) => void;
}) {
  const active = !!runStatus?.running && runStatus.phase === "analyze";
  const paused = active && runStatus.state === "paused";
  const anotherRunActive = !!runStatus?.running && !active;
  const automatic = pipeline?.phases.includes("analyze") ?? true;
  const speechReady = status?.tools.speech.available ?? false;
  const ocrReady = status?.tools.ocr.available ?? false;
  const eligible = status?.coverage.eligible ?? 0;

  return (
    <section aria-labelledby="local-analysis-heading" className="mb-4 rounded-[var(--radius-media)] border border-line bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 id="local-analysis-heading" className="text-sm font-semibold text-ink">Local analysis</h2>
          <p className="mt-1 max-w-2xl text-sm text-ink-dim">Create searchable speech and screen text from media stored on this machine. Offloaded and unavailable favorites are skipped.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {active ? (
            <>
              <Button variant="ghost" size="sm" disabled={busy} onClick={() => onAction(paused ? "continue" : "pause")}>
                {paused ? <Play size={15} weight="fill" /> : <Pause size={15} weight="fill" />}{paused ? "Continue" : "Pause"}
              </Button>
              <Button variant="danger" size="sm" disabled={busy} onClick={() => onAction("stop")}><Stop size={15} weight="fill" /> Stop</Button>
            </>
          ) : (
            <Button
              size="sm"
              disabled={busy || anotherRunActive || (!speechReady && !ocrReady)}
              onClick={() => onAction("analyze")}
            >
              <ArrowClockwise size={15} /> Analyze missing
            </Button>
          )}
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <CoverageCard label="Speech" icon={<Microphone size={15} />} coverage={status?.coverage.transcript ?? { complete: 0, manual: 0, generated: 0, pending: 0, failed: 0 }} eligible={eligible} />
        <CoverageCard label="Screen text" icon={<TextT size={15} />} coverage={status?.coverage.ocr ?? { complete: 0, manual: 0, generated: 0, pending: 0, failed: 0 }} eligible={eligible} />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
        <span className={cx(speechReady ? "text-ok" : "text-bad")}>Speech model: {speechReady ? "ready" : "unavailable"}</span>
        <span className={cx(ocrReady ? "text-ok" : "text-bad")}>OCR: {ocrReady ? "ready" : "unavailable"}</span>
        {anotherRunActive && <span className="text-ink-dim">Archive is busy with {runStatus?.phase ?? "another run"}.</span>}
      </div>
      {!speechReady && status?.tools.speech.error && <p className="mt-1 text-xs text-ink-faint">Speech: {status.tools.speech.error}</p>}
      {!ocrReady && status?.tools.ocr.error && <p className="mt-1 text-xs text-ink-faint">OCR: {status.tools.ocr.error}</p>}

      {active && (
        <div className="mt-4" aria-live="polite">
          <progress className="h-1.5 w-full accent-accent" value={progress?.completed ?? 0} max={Math.max(progress?.total ?? 0, 1)} />
          <p className="mt-1 text-xs text-ink-dim">{progress?.event === "analysis" ? analysisProgressLabel(progress) : paused ? "Analysis paused" : "Preparing local analysis…"}</p>
        </div>
      )}

      <label className="mt-4 flex cursor-pointer items-start gap-3 border-t border-line pt-4 text-sm text-ink">
        <input
          type="checkbox"
          className="mt-0.5"
          checked={automatic}
          disabled={!pipeline || savingAutomatic}
          onChange={(event) => onAutomaticChange(event.target.checked)}
        />
        <span>
          <span className="font-medium">Analyze automatically after Sync</span>
          <span className="mt-0.5 block text-xs leading-relaxed text-ink-dim">Enabled by default. Only missing speech or screen text is generated, and manually imported sources are left untouched.</span>
        </span>
      </label>
    </section>
  );
}

export function Lens() {
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("");
  const [status, setStatus] = useState<LensStatus | null>(null);
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null);
  const [pipeline, setPipeline] = useState<PipelineSettings | null>(null);
  const [analysisProgress, setAnalysisProgress] = useState<ProgressEvent | null>(null);
  const [results, setResults] = useState<LensResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [savingAutomatic, setSavingAutomatic] = useState(false);
  const [analysisMessage, setAnalysisMessage] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const refreshRun = () => {
      void api.status().then(setRunStatus).catch(() => {});
    };
    const refreshCoverage = () => {
      void api.lensStatus().then(setStatus).catch(() => {});
    };
    void Promise.all([
      api.lensStatus().then(setStatus),
      api.status().then(setRunStatus),
      api.pipelineSettings().then(setPipeline),
    ]).catch((error) => setAnalysisMessage(`Could not load local analysis: ${(error as Error).message}`));
    const poll = window.setInterval(refreshRun, 2000);
    const off = api.events((event) => {
      if (event.event === "analysis") setAnalysisProgress(event);
      if (event.event === "complete") {
        setAnalysisMessage((current) => analysisCompletionMessage(current, event));
        refreshRun();
        refreshCoverage();
      }
    });
    return () => {
      window.clearInterval(poll);
      off();
    };
  }, []);

  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      setSearching(false);
      return;
    }
    let alive = true;
    setSearching(true);
    const timer = window.setTimeout(() => {
      api.lensSearch(query, source)
        .then((response) => {
          if (!alive) return;
          setResults(response.results);
          setStatus((current) => current ? { ...current, items: response.items, segments: response.segments } : current);
          setMessage(null);
        })
        .catch((error) => { if (alive) { setResults([]); setMessage((error as Error).message); } })
        .finally(() => { if (alive) setSearching(false); });
    }, 180);
    return () => { alive = false; window.clearTimeout(timer); };
  }, [query, source]);

  async function importAnalysis(file: File) {
    setMessage("Importing local analysis…");
    try {
      const imported = await api.importLens(file);
      const success = `Imported ${imported.segments} segment${imported.segments === 1 ? "" : "s"} for ${imported.items} favorite${imported.items === 1 ? "" : "s"}.`;
      try {
        setStatus(await api.lensStatus());
        if (query.trim()) {
          const response = await api.lensSearch(query, source);
          setResults(response.results);
        }
        setMessage(success);
      } catch (error) {
        setMessage(`${success} Totals could not refresh: ${(error as Error).message}`);
      }
    } catch (error) {
      setMessage(`Import failed: ${(error as Error).message}`);
    }
  }

  async function runAnalysisAction(action: AnalysisAction) {
    setActionBusy(true);
    setAnalysisMessage(null);
    if (action === "analyze") setAnalysisProgress(null);
    try {
      const result = await api.syncAction(action);
      if (result.started === false) {
        setAnalysisMessage("Another Archive run is already active.");
      } else if (action === "stop") {
        setAnalysisMessage("Stopping after the current local file…");
      }
      setRunStatus(await api.status());
    } catch (error) {
      setAnalysisMessage((error as Error).message);
    } finally {
      setActionBusy(false);
    }
  }

  async function setAutomaticAnalysis(enabled: boolean) {
    if (!pipeline) return;
    setSavingAutomatic(true);
    setAnalysisMessage(null);
    try {
      setPipeline(await api.updatePipelineSettings(automaticAnalysisPhases(pipeline.phases, enabled)));
      setAnalysisMessage(enabled ? "Local analysis will run after Sync." : "Automatic local analysis is off.");
    } catch (error) {
      setAnalysisMessage((error as Error).message);
    } finally {
      setSavingAutomatic(false);
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-8">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">Search inside the media</p>
            <h1 className="mt-1 text-2xl font-semibold text-ink">Local Lens</h1>
            <p className="mt-1 max-w-2xl text-sm text-ink-dim">Search timestamped speech and on-screen text generated privately on your own machine.</p>
          </div>
          <div className="text-right text-xs text-ink-faint">
            <p className="tabular text-lg font-semibold text-ink">{status?.segments ?? 0}</p>
            <p>segments across {status?.items ?? 0} favorites</p>
          </div>
        </div>

        <AnalysisPanel
          status={status}
          runStatus={runStatus}
          pipeline={pipeline}
          progress={analysisProgress}
          busy={actionBusy}
          savingAutomatic={savingAutomatic}
          onAction={(action) => void runAnalysisAction(action)}
          onAutomaticChange={(enabled) => void setAutomaticAnalysis(enabled)}
        />
        {analysisMessage && <p className="mb-4 text-sm text-ink-dim" role="status">{analysisMessage}</p>}

        <section className="rounded-[var(--radius-media)] border border-line bg-surface p-5">
          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_10rem] md:items-end">
            <label className="text-xs text-ink-dim">What do you remember?
              <span className="relative mt-1 block">
                <MagnifyingGlass size={16} className="pointer-events-none absolute left-3 top-3 text-ink-faint" />
                <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="crispy potatoes with parmesan" className="h-10 w-full rounded-[var(--radius-control)] border border-line bg-elevated pl-9 pr-3 text-sm text-ink placeholder:text-ink-faint" />
              </span>
            </label>
            <label className="text-xs text-ink-dim">Evidence
              <select value={source} onChange={(event) => setSource(event.target.value)} className="mt-1 h-10 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm text-ink">
                <option value="">Speech + screen text</option>
                <option value="transcript">Speech only</option>
                <option value="ocr">Screen text only</option>
              </select>
            </label>
          </div>
          <details className="mt-4 border-t border-line pt-4 text-xs text-ink-dim">
            <summary className="cursor-pointer font-medium text-ink">Manual import</summary>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <p className="max-w-xl leading-relaxed">Import transcript or OCR JSON from another local tool. Imported sources take priority and are never overwritten by automatic analysis.</p>
              <Button variant="ghost" size="sm" onClick={() => fileRef.current?.click()}><FileArrowUp size={15} /> Choose JSON</Button>
              <input ref={fileRef} type="file" accept="application/json,.json" hidden onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (file) void importAnalysis(file);
              }} />
            </div>
            <pre className="mt-3 overflow-x-auto rounded-[var(--radius-control)] bg-elevated p-3">{`{"items":[{"item_id":1,"segments":[{"source":"transcript","text":"...","start_s":4.2,"end_s":8.5}]}]}`}</pre>
          </details>
          {message && <p className="mt-3 text-sm text-ink-dim" role="status">{message}</p>}
        </section>

        <section className="mt-6">
          {searching ? (
            <div className="space-y-2">{[1, 2, 3].map((value) => <Skeleton key={value} className="h-28" />)}</div>
          ) : query.trim() && results.length ? (
            <ol>{results.map((result) => <ResultRow key={result.id} result={result} />)}</ol>
          ) : query.trim() ? (
            <EmptyState icon={<MagnifyingGlass size={36} />} title="No matching words found" hint="Try fewer terms, switch the evidence filter, or analyze any missing local media." />
          ) : status?.segments ? (
            <EmptyState icon={<Scan size={38} />} title="Search what was said or shown" hint="Results include the matching evidence and jump directly to its timestamp." />
          ) : (
            <EmptyState icon={<Scan size={38} />} title="No searchable analysis yet" hint="Choose Analyze missing above, or let it run automatically after your next Sync. Media never leaves this machine." />
          )}
        </section>
      </div>
    </div>
  );
}
