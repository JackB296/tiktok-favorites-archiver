import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { MusicNotes, Play, SpotifyLogo, YoutubeLogo, BookmarkSimple, Trash, X } from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { SongSummary, SongPlaylist } from "../lib/types";
import { Button, EmptyState, Skeleton, cx } from "../components/ui";
import { spotifyUrl, appleMusicUrl, youtubeUrl } from "../lib/songLinks.js";

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
  const [playlists, setPlaylists] = useState<SongPlaylist[]>([]);
  const [activePlaylistId, setActivePlaylistId] = useState<number | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [playlistName, setPlaylistName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshPlaylists = () => api.songPlaylists().then(setPlaylists).catch(() => {});

  useEffect(() => {
    api.songs().then((r) => setSongs(r.songs)).catch(() => setSongs([]));
    refreshPlaylists();
  }, []);

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
    const name = playlistName.trim();
    if (!name || !selected.size || saving) return;
    setSaving(true);
    setError(null);
    try {
      await api.createSongPlaylist(name, [...selected]);
      setPlaylistName("");
      setSelected(new Set());
      await refreshPlaylists();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not save the playlist.");
    } finally {
      setSaving(false);
    }
  }

  async function deletePlaylist(id: number) {
    await api.deleteSongPlaylist(id).catch(() => {});
    if (activePlaylistId === id) setActivePlaylistId(null);
    refreshPlaylists();
  }

  function playSong(song: SongSummary) {
    if (song.item_ids.length) navigate(`/?queue=${song.item_ids.join(",")}`);
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-4 py-8">
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-ink">Music</h1>
          <p className="mt-0.5 text-sm text-ink-dim">Songs identified across your favorites. Open one in Spotify, YouTube, or Apple Music, play the favorites that use it, or gather songs into a playlist.</p>
        </div>

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
    </div>
  );
}
