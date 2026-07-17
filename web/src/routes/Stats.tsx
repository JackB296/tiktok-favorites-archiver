import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ChartBar, HardDrives, MusicNotes, SpeakerSlash, User, Warning } from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { Stats as StatsPayload } from "../lib/types";
import { EmptyState, Skeleton, Stat } from "../components/ui";
import { ChartCard } from "../components/charts/common";
import { AreaChart } from "../components/charts/AreaChart";
import { ColumnChart } from "../components/charts/ColumnChart";
import { Heatmap } from "../components/charts/Heatmap";
import { Donut } from "../components/charts/Donut";
import {
  compactCount, formatCount, formatSeconds, formatWatchLength,
  heatmapGrid, monthLabel, monthlySeries,
} from "../lib/statsPresentation";
import { formatSize } from "../lib/format";

function RankedList({ rows }: {
  rows: Array<{ key: string; label: React.ReactNode; count: number; href?: string }>;
}) {
  const max = rows.length ? rows[0].count : 0;
  return (
    <ol className="space-y-1">
      {rows.map((row, i) => (
        <li key={row.key}>
          <RankedRow rank={i + 1} row={row} max={max} />
        </li>
      ))}
    </ol>
  );
}

/** One ranked row: rank, name, count — the row itself carries a quiet
 * proportional bar so magnitude reads without a separate chart. */
function RankedRow({ rank, row, max }: {
  rank: number;
  row: { label: React.ReactNode; count: number; href?: string };
  max: number;
}) {
  const body = (
    <div className="relative flex items-center gap-2 overflow-hidden rounded-[var(--radius-control)] px-2 py-1.5">
      <div
        aria-hidden
        className="absolute inset-y-0 left-0 rounded-[var(--radius-control)] bg-[var(--chart-mark)] opacity-10"
        style={{ width: `${max ? (row.count / max) * 100 : 0}%` }}
      />
      <span className="tabular w-5 shrink-0 text-right text-xs text-ink-faint">{rank}</span>
      <span className="min-w-0 flex-1 truncate text-sm text-ink">{row.label}</span>
      <span className="tabular shrink-0 text-sm text-ink-dim">{formatCount(row.count)}</span>
    </div>
  );
  return row.href ? (
    <Link to={row.href} className="block transition hover:bg-elevated">{body}</Link>
  ) : (
    <div>{body}</div>
  );
}

export function Stats() {
  const [stats, setStats] = useState<StatsPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.stats().then(setStats).catch((e) => setError(e.message));
  }, []);

  const growth = useMemo(() => monthlySeries(stats?.growth.monthly ?? []), [stats]);
  const heat = useMemo(() => heatmapGrid(stats?.watcher.heatmap ?? []), [stats]);

  if (error) {
    return <div className="mx-auto max-w-5xl px-4 py-8"><p role="alert" className="rounded-[var(--radius-control)] border border-bad/40 bg-bad/10 p-3 text-sm text-bad">Could not load stats: {error}</p></div>;
  }
  if (!stats) {
    return (
      <div className="h-full overflow-y-auto">
        <div className="mx-auto max-w-5xl space-y-4 px-4 py-8">
          <Skeleton className="h-24" />
          <div className="grid gap-4 md:grid-cols-2"><Skeleton className="h-56" /><Skeleton className="h-56" /></div>
        </div>
      </div>
    );
  }

  const { hero, watcher, top, health } = stats;
  if (hero.total === 0) {
    return (
      <div className="flex h-full items-center justify-center">
        <EmptyState
          icon={<ChartBar size={40} />}
          title="Nothing to chart yet"
          hint={<>Upload your TikTok export in the <Link to="/sync" className="text-ink underline underline-offset-2">Sync</Link> tab. Once favorites are in the archive, this tab shows how you actually watch.</>}
        />
      </div>
    );
  }

  const monthTitle = (i: number) => monthLabel(growth.months[i] ?? "");
  const histogram = watcher.duration_histogram;
  const silentPct = watcher.silent.of_indexed ? (watcher.silent.count / watcher.silent.of_indexed) * 100 : 0;

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-8">
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-ink">Stats</h1>
          <p className="mt-0.5 text-sm text-ink-dim">Your archive, measured: how it grew, what you favorite, and how healthy it is.</p>
        </div>

        {/* Hero: one lead figure, then the tiles. */}
        <div className="mb-8 flex flex-wrap items-end gap-x-10 gap-y-4">
          <div>
            <p className="text-xs text-ink-faint">Favorites archived</p>
            <p className="text-5xl font-semibold text-ink">{formatCount(hero.total)}</p>
          </div>
          <div className="grid flex-1 grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat label="Videos / slideshows" value={`${compactCount(hero.videos)} / ${compactCount(hero.slideshows)}`} hint="what kind you save" />
            <Stat label="Total watch-length" value={formatWatchLength(hero.watch_seconds)} hint="across indexed videos" />
            <Stat label="On disk" value={hero.disk_bytes > 0 ? formatSize(hero.disk_bytes) : "0 MB"} hint="indexed media" />
            <Stat label="Archived" value={`${hero.archived_pct}%`} hint={`${formatCount(hero.archived)} downloaded`} />
          </div>
        </div>

        <div className="space-y-8">
          {/* Growth */}
          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-faint">Growth</h2>
            <div className="grid gap-4 lg:grid-cols-2">
              <ChartCard
                title="Archive over time"
                caption="Cumulative favorites by the month you saved them."
                note={hero.undated ? `${formatCount(hero.undated)} favorites have no saved date and aren't in the time charts.` : undefined}
              >
                <AreaChart labels={growth.months.map(monthLabel)} values={growth.cumulative} tipTitle={monthTitle} />
              </ChartCard>
              <ChartCard title="Favorites per month" caption="How many you saved in each month.">
                <ColumnChart labels={growth.months.map(monthLabel)} values={growth.counts} tipTitle={monthTitle} />
              </ChartCard>
            </div>
          </section>

          {/* You as a watcher */}
          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-faint">You as a watcher</h2>
            <div className="grid gap-4 lg:grid-cols-2">
              <ChartCard title="When you favorite" caption="Saves by day of week and hour — your scrolling fingerprint.">
                <Heatmap grid={heat.grid} max={heat.max} />
              </ChartCard>
              <ChartCard
                title="How long they run"
                caption="Duration of your favorites."
                note={watcher.median_duration_s != null ? `Median: ${formatSeconds(watcher.median_duration_s)}.` : undefined}
              >
                <ColumnChart labels={histogram.map((b) => b.label)} values={histogram.map((b) => b.count)} />
              </ChartCard>
            </div>
            {watcher.silent.count > 0 && (
              <p className="mt-3 flex items-center gap-1.5 text-xs text-ink-dim">
                <SpeakerSlash size={14} className="text-warn" />
                {formatCount(watcher.silent.count)} of {formatCount(watcher.silent.of_indexed)} indexed videos ({silentPct.toFixed(1)}%) are confirmed silent.
              </p>
            )}
          </section>

          {/* Top lists. The Gallery/Music links are approximate navigation:
              the Gallery matches authors by substring and hashtags by FTS
              prefix, so a landed result count can differ from the stat here. */}
          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-faint">Top of your archive</h2>
            <div className="grid gap-4 lg:grid-cols-3">
              <ChartCard title="Creators" caption="Whose posts you favorite most. Click to open in Gallery.">
                {top.authors.length ? (
                  <RankedList rows={top.authors.map((a) => ({
                    key: a.author,
                    label: <span className="inline-flex items-center gap-1.5"><User size={13} className="shrink-0 text-ink-faint" />@{a.author}</span>,
                    count: a.count,
                    // Authors are stored without the "@" (oEmbed author_name),
                    // so the include term must be the bare name to match.
                    href: `/gallery?include=${encodeURIComponent(a.author)}`,
                  }))} />
                ) : (
                  <p className="py-6 text-center text-xs text-ink-faint">No creator names yet — run search metadata in Sync.</p>
                )}
              </ChartCard>
              <ChartCard title="Songs" caption="The sounds your favorites share. Click to open Music.">
                {top.songs.length ? (
                  <RankedList rows={top.songs.map((s) => ({
                    key: `song-${s.id}`,
                    label: <span className="inline-flex items-center gap-1.5"><MusicNotes size={13} className="shrink-0 text-ink-faint" />{s.artist ? `${s.title} · ${s.artist}` : s.title}</span>,
                    count: s.count,
                    href: "/music",
                  }))} />
                ) : (
                  <p className="py-6 text-center text-xs text-ink-faint">No identified songs yet — enable song identification in Sync.</p>
                )}
              </ChartCard>
              <ChartCard title="Hashtags" caption="What the captions say. Click to search the Gallery.">
                {top.hashtags.length ? (
                  <RankedList rows={top.hashtags.map((h) => ({
                    key: h.tag,
                    label: h.tag,
                    count: h.count,
                    href: `/gallery?search=${encodeURIComponent(h.tag)}`,
                  }))} />
                ) : (
                  <p className="py-6 text-center text-xs text-ink-faint">No captions yet — run search metadata in Sync.</p>
                )}
              </ChartCard>
            </div>
          </section>

          {/* Health */}
          <section className="pb-8">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-faint">Archive health</h2>
            <div className="grid gap-4 lg:grid-cols-2">
              <ChartCard
                title="Lifecycle"
                caption="Every favorite by its current state."
                note={[
                  health.offloaded ? `${formatCount(health.offloaded)} offloaded (archived externally).` : null,
                  health.missing ? `${formatCount(health.missing)} finished favorites are missing their file — see Recovery in Gallery.` : null,
                  hero.unindexed ? `${formatCount(hero.unindexed)} downloaded favorites aren't indexed yet, so size and duration totals exclude them.` : null,
                ].filter(Boolean).join(" ") || undefined}
              >
                <Donut statuses={health.statuses} />
              </ChartCard>
              <ChartCard title="Failure reasons" caption="What the failed downloads reported last.">
                {health.errors.length ? (
                  <RankedList rows={health.errors.map((e) => ({
                    key: e.error,
                    label: <span className="inline-flex items-center gap-1.5"><Warning size={13} className="shrink-0 text-warn" />{e.error}</span>,
                    count: e.count,
                  }))} />
                ) : (
                  <p className="flex items-center justify-center gap-1.5 py-6 text-xs text-ink-faint"><HardDrives size={14} /> No failed downloads. Clean archive.</p>
                )}
              </ChartCard>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
