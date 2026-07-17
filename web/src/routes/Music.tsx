import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowSquareOut, CaretDown, CloudArrowUp, MusicNotes, Play, SpotifyLogo, YoutubeLogo, BookmarkSimple, Trash, X } from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { SongSummary, SongPlaylist, SpotifyStatus, SpotifyPushReport } from "../lib/types";
import { Button, Dialog, EmptyState, Skeleton, cx } from "../components/ui";
import { spotifyUrl, appleMusicUrl, youtubeUrl } from "../lib/songLinks.js";
import { useSavedList } from "../lib/useSavedList";

function StreamLinks({ song }: { song: SongSummary }) {
  const link = "inline-flex items-center gap-1 rounded-full border border-line px-2 py-1 text-xs text-ink-dim transition hover:border-ink-faint hover:text-ink";
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <a href={spotifyUrl(song)} target="_blank" rel="noreferrer" className={link}><SpotifyLogo size={14} /> Spotify</a>
      <a href={youtubeUrl(song)} target="_blank" rel="noreferrer" className={link}><YoutubeLogo size={14} /> YouTube</a>
      <a href={appleMusicUrl(song)} target="_blank" rel="noreferrer" className={link}><MusicNotes size={14} /> Apple</a>
    </div>
  );
}

export function Music() {
  const navigate = useNavigate();
  const [songs, setSongs] = useState<SongSummary[] | null>(null);
  const {
    items: playlists, name: playlistName, setName: setPlaylistName,
    message: error, setMessage: setError, save: savePlaylistEntry, remove: removePlaylist,
  } = useSavedList<SongPlaylist>({
    load: api.songPlaylists,
    create: (name) => api.createSongPlaylist(name, [...selected]),
    remove: (id) => api.deleteSongPlaylist(id), // failures surface via the hook's message
  });
  const [activePlaylistId, setActivePlaylistId] = useState<number | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [saving, setSaving] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const [spotify, setSpotify] = useState<SpotifyStatus | null>(null);
  const [clientIdInput, setClientIdInput] = useState("");
  const [spotifyMsg, setSpotifyMsg] = useState<string | null>(null);
  const [spotifyBusy, setSpotifyBusy] = useState(false);
  const [pushingId, setPushingId] = useState<number | null>(null);
  const [pushReport, setPushReport] = useState<SpotifyPushReport | null>(null);

  useEffect(() => {
    api.songs().then((r) => setSongs(r.songs)).catch(() => setSongs([]));
    api.spotifyStatus().then((s) => { setSpotify(s); setClientIdInput(s.client_id ?? ""); }).catch(() => {});
  }, []);

  // The OAuth callback bounces back here with a result in the query string.
  useEffect(() => {
    const connected = searchParams.get("spotify") === "connected";
    const error = searchParams.get("spotify_error");
    if (!connected && !error) return;
    setSpotifyMsg(connected ? "Spotify connected." : `Spotify connection failed: ${error}`);
    api.spotifyStatus().then(setSpotify).catch(() => {});
    setSearchParams({}, { replace: true });
  }, [searchParams, setSearchParams]);

  const activePlaylist = playlists.find((p) => p.id === activePlaylistId) ?? null;
  const visibleSongs = useMemo(() => {
    if (!songs) return [];
    if (!activePlaylist) return songs;
    const ids = new Set(activePlaylist.song_ids);
    return songs.filter((s) => ids.has(s.id));
  }, [songs, activePlaylist]);

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  async function savePlaylist() {
    if (!playlistName.trim() || !selected.size || saving) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await savePlaylistEntry();
      if (saved) setSelected(new Set());
    } finally {
      setSaving(false);
    }
  }

  async function deletePlaylist(id: number) {
    const removed = await removePlaylist(id);
    // A failed delete keeps the playlist, so don't jump the filter to "All songs".
    if (removed && activePlaylistId === id) setActivePlaylistId(null);
  }

  function playSong(song: SongSummary) {
    if (song.item_ids.length) navigate(`/?queue=${song.item_ids.join(",")}`);
  }

  async function connectSpotify() {
    if (!clientIdInput.trim() || spotifyBusy) return;
    setSpotifyBusy(true);
    setSpotifyMsg(null);
    try {
      const { authorize_url } = await api.spotifyConnect(clientIdInput.trim());
      window.location.assign(authorize_url); // Spotify redirects back to /music
    } catch (err) {
      setSpotifyMsg(`Connect failed: ${(err as Error).message}`);
      setSpotifyBusy(false);
    }
  }

  async function disconnectSpotify() {
    setSpotifyBusy(true);
    try {
      await api.spotifyDisconnect();
      setSpotify(await api.spotifyStatus());
      setSpotifyMsg("Disconnected — the stored tokens were deleted.");
    } catch (err) {
      setSpotifyMsg((err as Error).message);
    } finally {
      setSpotifyBusy(false);
    }
  }

  async function pushPlaylist(playlist: SongPlaylist) {
    if (pushingId !== null) return;
    setPushingId(playlist.id);
    setSpotifyMsg(null);
    try {
      setPushReport(await api.pushSongPlaylist(playlist.id));
    } catch (err) {
      setSpotifyMsg(`Push failed: ${(err as Error).message}`);
    } finally {
      setPushingId(null);
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-4 py-8">
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-ink">Music</h1>
          <p className="mt-0.5 text-sm text-ink-dim">Songs identified across your favorites. Open one in Spotify, YouTube, or Apple Music, play the favorites that use it, or gather songs into a playlist.</p>
        </div>

        {spotify && (
          <SpotifyPanel
            status={spotify}
            clientId={clientIdInput}
            setClientId={setClientIdInput}
            busy={spotifyBusy}
            message={spotifyMsg}
            onConnect={() => void connectSpotify()}
            onDisconnect={() => void disconnectSpotify()}
          />
        )}

        {songs === null ? (
          <div className="space-y-2">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-16 rounded-[var(--radius-media)]" />)}</div>
        ) : songs.length === 0 ? (
          <EmptyState
            icon={<MusicNotes size={40} />}
            title="No songs identified yet"
            hint={<>Turn on song identification in the <Link to="/sync" className="text-ink underline underline-offset-2">Sync</Link> tab and run it. Identified songs show up here.</>}
          />
        ) : (
          <>
            {playlists.length > 0 && (
              <div className="mb-5 flex flex-wrap items-center gap-2">
                <button onClick={() => setActivePlaylistId(null)} className={cx("rounded-full border px-3 py-1 text-xs font-medium transition", activePlaylistId === null ? "border-accent bg-accent text-on-accent" : "border-line text-ink-dim hover:text-ink")}>All songs</button>
                {playlists.map((p) => (
                  <span key={p.id} className={cx("inline-flex items-center gap-1 rounded-full border pl-3 text-xs font-medium transition", activePlaylistId === p.id ? "border-accent bg-accent text-on-accent" : "border-line text-ink-dim")}>
                    <button onClick={() => setActivePlaylistId(p.id)} className="py-1 hover:opacity-80">{p.name} · {p.song_ids.length}</button>
                    {spotify?.connected && (
                      <button onClick={() => void pushPlaylist(p)} disabled={pushingId !== null} aria-label={`Push ${p.name} to Spotify`} title="Push to Spotify" className="rounded-full p-1 transition hover:text-ok disabled:opacity-50">
                        {pushingId === p.id ? <span className="tabular text-[10px]">…</span> : <CloudArrowUp size={12} />}
                      </button>
                    )}
                    <button onClick={() => void deletePlaylist(p.id)} aria-label={`Delete playlist ${p.name}`} title="Delete playlist" className="rounded-full p-1 hover:text-bad"><Trash size={12} /></button>
                  </span>
                ))}
              </div>
            )}

            {selected.size > 0 && (
              <div className="mb-4 flex flex-wrap items-center gap-2 rounded-[var(--radius-control)] border border-line bg-surface px-3 py-2.5">
                <span className="text-sm text-ink-dim">{selected.size} selected</span>
                <input value={playlistName} onChange={(e) => setPlaylistName(e.target.value)} maxLength={80} placeholder="Playlist name…" className="h-8 flex-1 rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink placeholder:text-ink-faint" />
                <Button size="sm" onClick={() => void savePlaylist()} disabled={saving || !playlistName.trim()}><BookmarkSimple size={14} /> {saving ? "Saving…" : "Save playlist"}</Button>
                <Button variant="ghost" size="sm" onClick={() => setSelected(new Set())}><X size={14} /> Clear</Button>
              </div>
            )}
            {error && <p role="alert" className="mb-4 rounded-[var(--radius-control)] border border-bad/40 bg-bad/10 p-3 text-sm text-bad">{error}</p>}

            {activePlaylist && visibleSongs.length === 0 && <p className="py-10 text-center text-sm text-ink-faint">This playlist's songs are no longer in the archive.</p>}

            <ul className="divide-y divide-line rounded-[var(--radius-media)] border border-line bg-surface">
              {visibleSongs.map((song) => (
                <li key={song.id} className="flex items-center gap-3 px-3 py-3">
                  <input type="checkbox" checked={selected.has(song.id)} onChange={() => toggle(song.id)} aria-label={`Select ${song.title}`} className="shrink-0" />
                  {song.art_url
                    ? <img src={song.art_url} alt="" className="h-12 w-12 shrink-0 rounded-[var(--radius-control)] object-cover" />
                    : <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[var(--radius-control)] bg-elevated text-ink-faint"><MusicNotes size={20} /></span>}
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-ink">{song.title}</p>
                    <p className="truncate text-xs text-ink-dim">{song.artist || "Unknown artist"}{song.album ? ` · ${song.album}` : ""}</p>
                    <div className="mt-1.5"><StreamLinks song={song} /></div>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1.5">
                    <button onClick={() => playSong(song)} title="Play the favorites that use this song" className="inline-flex items-center gap-1 rounded-full border border-line px-2.5 py-1 text-xs font-medium text-ink-dim transition hover:border-ink-faint hover:text-ink"><Play size={12} weight="fill" /> {song.uses} {song.uses === 1 ? "favorite" : "favorites"}</button>
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

      {pushReport && <PushReportDialog report={pushReport} onClose={() => setPushReport(null)} />}
    </div>
  );
}

function SpotifyPanel({ status, clientId, setClientId, busy, message, onConnect, onDisconnect }: {
  status: SpotifyStatus;
  clientId: string;
  setClientId: (value: string) => void;
  busy: boolean;
  message: string | null;
  onConnect: () => void;
  onDisconnect: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <details open={open} onToggle={(e) => setOpen(e.currentTarget.open)} className="group mb-5 rounded-[var(--radius-media)] border border-line bg-surface">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3">
        <span className="flex items-center gap-2 text-sm font-semibold text-ink">
          <SpotifyLogo size={18} className="text-ok" />
          Spotify
          {status.connected
            ? <span className="ml-1 inline-flex items-center gap-1 text-xs font-normal text-ok">Connected{status.account_name ? ` · ${status.account_name}` : ""}</span>
            : <span className="ml-1 text-xs font-normal text-ink-faint">Not connected</span>}
        </span>
        <CaretDown size={16} className="shrink-0 text-ink-faint transition group-open:rotate-180" />
      </summary>
      <div className="space-y-3 border-t border-line px-4 py-4 text-sm text-ink-dim">
        {status.connected ? (
          <>
            <p>Push any saved playlist to your Spotify account with the <CloudArrowUp size={14} className="inline" /> button on its chip. Pushed playlists are private, and pushing again updates the same playlist instead of making a new one.</p>
            <Button variant="ghost" size="sm" disabled={busy} onClick={onDisconnect}>Disconnect</Button>
          </>
        ) : (
          <>
            <p>Turn saved playlists into real Spotify playlists. This needs a free Spotify app you create once — nothing is sent to Spotify until you connect and press push.</p>
            <ol className="ml-4 list-decimal space-y-1 text-xs">
              <li>Open the <a href="https://developer.spotify.com/dashboard" target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-ink underline underline-offset-2">Spotify developer dashboard <ArrowSquareOut size={11} /></a> and create an app.</li>
              <li>Add this exact Redirect URI to the app: <code className="rounded bg-elevated px-1 text-ink">{status.redirect_uri}</code></li>
              <li>Copy the app's Client ID and paste it below.</li>
            </ol>
            <div className="flex flex-wrap items-center gap-2">
              <input value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="Spotify Client ID" className="h-8 flex-1 rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink placeholder:text-ink-faint" />
              <Button size="sm" disabled={busy || !clientId.trim()} onClick={onConnect}><SpotifyLogo size={14} /> Connect</Button>
            </div>
          </>
        )}
        {message && <p role="status" className="text-xs text-ink-dim">{message}</p>}
      </div>
    </details>
  );
}

function PushReportDialog({ report, onClose }: { report: SpotifyPushReport; onClose: () => void }) {
  return (
    <Dialog labelledBy="push-report-title" onClose={onClose} className="bg-black/70">
      <div className="w-full max-w-md rounded-[var(--radius-media)] border border-white/15 bg-surface p-5 text-ink shadow-2xl">
        <h2 id="push-report-title" className="text-base font-semibold text-ink">
          {report.created ? "Playlist created on Spotify" : "Playlist updated on Spotify"}
        </h2>
        <p className="mt-1 text-sm text-ink-dim">
          {report.pushed} track{report.pushed === 1 ? "" : "s"} in “{report.playlist}”.
          {report.unmatched.length > 0 && ` ${report.unmatched.length} couldn't be matched.`}
        </p>
        <a href={report.url} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1 text-sm text-ink underline underline-offset-2">
          Open in Spotify <ArrowSquareOut size={13} />
        </a>
        {report.unmatched.length > 0 && (
          <div className="mt-4">
            <p className="text-xs font-medium text-ink-dim">Not added — no confident Spotify match:</p>
            <ul className="mt-1.5 max-h-40 overflow-y-auto rounded-[var(--radius-control)] border border-line bg-elevated p-2 text-xs text-ink-dim">
              {report.unmatched.map((song, i) => (
                <li key={i} className="truncate py-0.5">{song.artist ? `${song.title} · ${song.artist}` : song.title}</li>
              ))}
            </ul>
          </div>
        )}
        <div className="mt-5 flex justify-end">
          <Button size="sm" onClick={onClose}>Done</Button>
        </div>
      </div>
    </Dialog>
  );
}
