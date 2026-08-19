import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Binoculars, BookmarkSimple, ChartBar, ChatCircleDots, Database,
  Eye, HardDrives, Heart, MusicNotes, ShareNetwork, SpeakerSlash, User, Warning,
} from "@phosphor-icons/react";
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
  coveragePercent, heatmapGrid, monthLabel, monthlySeries,
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

function CoverageList({ total, rows }: {
  total: number;
  rows: Array<{ label: string; count: number; hint: string }>;
}) {
  return (
    <div className="space-y-3">
      {rows.map((row) => {
        const percentage = coveragePercent(row.count, total);
        return (
          <div key={row.label}>
            <div className="mb-1 flex items-baseline justify-between gap-3 text-xs">
              <span className="font-medium text-ink">{row.label}</span>
              <span className="tabular shrink-0 text-ink-dim">{formatCount(row.count)} · {percentage.toFixed(0)}%</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-elevated" aria-label={`${row.label}: ${percentage.toFixed(0)}%`}>
              <div className="h-full rounded-full bg-[var(--chart-mark)]" style={{ width: `${percentage}%` }} />
            </div>
            <p className="mt-1 text-[11px] text-ink-faint">{row.hint}</p>
          </div>
        );
      })}
    </div>
  );
}

function PeakPostList({ posts }: { posts: StatsPayload["reach"]["peak_posts"] }) {
  return (
    <ol className="space-y-1">
      {posts.map((post, index) => (
        <li key={post.id}>
          <Link
            to={`/?item=${post.id}`}
            className="grid grid-cols-[1.25rem_minmax(0,1fr)_auto] items-center gap-2 rounded-[var(--radius-control)] px-2 py-2 transition hover:bg-elevated"
            title="Play this post from your local archive"
          >
            <span className="tabular text-right text-xs text-ink-faint">{index + 1}</span>
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium text-ink">{post.caption}</span>
              <span className="block truncate text-[11px] text-ink-faint">
                {post.creator ? `@${post.creator} · ` : ""}{compactCount(post.likes)} likes · {compactCount(post.comments)} comments
              </span>
            </span>
            <span className="tabular text-right">
              <span className="block text-sm font-semibold text-ink">{compactCount(post.views)}</span>
              <span className="block text-[10px] uppercase tracking-wide text-ink-faint">views</span>
            </span>
          </Link>
        </li>
      ))}
    </ol>
  );
}

function ReachMetric({ icon, label, value, hint }: {
  icon: React.ReactNode;
  label: string;
  value: number;
  hint: string;
}) {
  return (
    <div className="rounded-[var(--radius-control)] border border-line bg-elevated px-3 py-3">
      <div className="flex items-center gap-1.5 text-xs text-ink-faint">{icon}{label}</div>
      <p className="mt-1 text-xl font-semibold text-ink" title={formatCount(value)}>{compactCount(value)}</p>
      <p className="mt-0.5 truncate text-xs text-ink-dim">{hint}</p>
    </div>
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

  const {
    hero, watcher, reach, discovery_lag: discoveryLag, quality,
    conversation, monitoring, top, health,
  } = stats;
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
  const conversationChanges = conversation.changes.added + conversation.changes.removed + conversation.changes.changed;

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-8">
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-ink">Stats</h1>
          <p className="mt-0.5 text-sm text-ink-dim">Your archive, measured: how it grew, what you favorite, and how healthy it is.</p>
        </div>

        {/* Hero: one lead figure, then the tiles. */}
        <div className="mb-8 grid gap-4 md:grid-cols-[auto_minmax(0,1fr)] md:items-end md:gap-x-10">
          <div>
            <p className="text-xs text-ink-faint">Favorites archived</p>
            <p className="text-5xl font-semibold text-ink">{formatCount(hero.total)}</p>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
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

          {/* Source counters are captured during profile/sidecar discovery.
              The endpoint returns totals plus only five posts, so this stays
              constant-size even when the archive contains millions of rows. */}
          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-faint">Out in the world</h2>
            <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-5">
              <ReachMetric icon={<Eye size={14} />} label="Views" value={reach.views} hint="combined reach" />
              <ReachMetric icon={<Heart size={14} />} label="Likes" value={reach.likes} hint="public reactions" />
              <ReachMetric icon={<ChatCircleDots size={14} />} label="Comments" value={reach.comments} hint="reported by TikTok" />
              <ReachMetric icon={<ShareNetwork size={14} />} label="Reposts" value={reach.reposts} hint="shared onward" />
              <ReachMetric icon={<BookmarkSimple size={14} />} label="Saves" value={reach.saves} hint="saved by others" />
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <ChartCard
                title="Biggest posts"
                caption="The five most-viewed posts in your archive. Click one to play the local copy."
                note={reach.covered ? `Source counters are available for ${formatCount(reach.covered)} of ${formatCount(hero.total)} favorites.` : undefined}
              >
                {reach.peak_posts.length ? <PeakPostList posts={reach.peak_posts} /> : (
                  <p className="py-6 text-center text-xs text-ink-faint">No source counters yet — run Media sidecars or import a creator profile.</p>
                )}
              </ChartCard>
              <ChartCard
                title="How early you found them"
                caption="Time between a post going live and you favoriting it."
                note={discoveryLag.covered ? `Based on ${formatCount(discoveryLag.covered)} favorites with both dates.` : undefined}
              >
                {discoveryLag.buckets.length ? (
                  <ColumnChart labels={discoveryLag.buckets.map((b) => b.label)} values={discoveryLag.buckets.map((b) => b.count)} />
                ) : (
                  <p className="py-6 text-center text-xs text-ink-faint">Upload dates will appear here as source metadata is collected.</p>
                )}
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
              <ChartCard title="Songs" caption="The sounds your favorites share. Click to browse matching videos.">
                {top.songs.length ? (
                  <RankedList rows={top.songs.map((s) => ({
                    key: `song-${s.id}`,
                    label: <span className="inline-flex items-center gap-1.5"><MusicNotes size={13} className="shrink-0 text-ink-faint" />{s.artist ? `${s.title} · ${s.artist}` : s.title}</span>,
                    count: s.count,
                    href: `/gallery?song=${s.id}`,
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

          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-faint">Offline depth</h2>
            <div className="grid gap-4 lg:grid-cols-3">
              <ChartCard title="Archived resolution" caption="The actual local video files, grouped by their shorter edge.">
                {quality.resolution.length ? (
                  <ColumnChart labels={quality.resolution.map((b) => b.label)} values={quality.resolution.map((b) => b.count)} />
                ) : (
                  <p className="flex items-center justify-center gap-1.5 py-6 text-xs text-ink-faint"><Database size={14} /> Index media to see local quality.</p>
                )}
              </ChartCard>
              <ChartCard
                title="Download engines"
                caption="Which downloader produced the archived copy."
                note="Older files predate downloader tracking and remain labeled legacy / unknown."
              >
                <ColumnChart labels={quality.downloads.map((b) => b.label)} values={quality.downloads.map((b) => b.count)} />
              </ChartCard>
              <ChartCard title="What works without TikTok" caption="Local sidecars and embedded data that travel with the archive.">
                <CoverageList
                  total={quality.offline.total}
                  rows={[
                    { label: "Source details", count: quality.offline.source_metadata, hint: "captions, dates, creator and engagement" },
                    { label: "Saved comments", count: quality.offline.comments, hint: "a local snapshot, including zero-comment posts" },
                    { label: "Local thumbnails", count: quality.offline.thumbnails, hint: "browseable when the original is gone" },
                    { label: "Portable media tags", count: quality.offline.portable_metadata, hint: "metadata embedded into local files" },
                    { label: "Identified songs", count: quality.offline.songs, hint: "browseable by sound" },
                  ]}
                />
              </ChartCard>
            </div>
          </section>

          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-faint">Living archive</h2>
            <div className="grid gap-4 lg:grid-cols-2">
              <ChartCard
                title="Conversation time machine"
                caption="Comment snapshots saved locally, including what changed between refreshes."
                note={conversation.snapshots ? "Counts come from snapshot summaries; Stats never loads the comment text." : undefined}
              >
                {conversation.snapshots ? (
                  <>
                    <div className="grid grid-cols-3 gap-2">
                      <Stat label="Posts captured" value={formatCount(conversation.posts)} hint="with local history" />
                      <Stat label="Snapshots" value={formatCount(conversation.snapshots)} hint="points in time" />
                      <Stat label="Comments saved" value={formatCount(conversation.saved_comments)} hint="in latest copies" />
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2 text-xs">
                      <span className="rounded-full bg-ok/10 px-2 py-1 text-ok">+{formatCount(conversation.changes.added)} appeared</span>
                      <span className="rounded-full bg-warn/10 px-2 py-1 text-warn">−{formatCount(conversation.changes.removed)} disappeared</span>
                      <span className="rounded-full bg-elevated px-2 py-1 text-ink-dim">{formatCount(conversation.changes.changed)} edited</span>
                    </div>
                    {!conversationChanges && <p className="mt-2 text-xs text-ink-faint">No changes between snapshots yet.</p>}
                  </>
                ) : (
                  <p className="flex items-center justify-center gap-1.5 py-6 text-xs text-ink-faint"><ChatCircleDots size={14} /> Comment history appears after Media sidecars runs.</p>
                )}
              </ChartCard>
              <ChartCard
                title="Creator radar"
                caption="Profiles the archive checks automatically for newly published videos."
                note={monitoring.profiles ? `${formatCount(monitoring.checked)} profiles have completed at least one check.` : undefined}
              >
                {monitoring.profiles ? (
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    <Stat label="Watching" value={formatCount(monitoring.active)} hint={`of ${formatCount(monitoring.profiles)} profiles`} />
                    <Stat label="Found last sweep" value={formatCount(monitoring.found_last_check)} hint="new local posts" />
                    <Stat label="Checked" value={formatCount(monitoring.checked)} hint="at least once" />
                    <Stat label="Errors" value={formatCount(monitoring.errors)} hint="latest checks" />
                  </div>
                ) : (
                  <p className="flex items-center justify-center gap-1.5 py-6 text-xs text-ink-faint"><Binoculars size={14} /> Add a monitored creator in <Link to="/sync" className="text-ink underline underline-offset-2">Sync</Link>.</p>
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
