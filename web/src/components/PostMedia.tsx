import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { Archive, CaretLeft, CaretRight, LinkBreak, Pause, Play } from "@phosphor-icons/react";
import type { Item } from "../lib/types";
import { feedMediaKind } from "../lib/feedItems";
import { cx } from "./ui";
import { usePlayback } from "./playback";
import { normalizationGain } from "../lib/playbackVolume.js";
import { formatMediaTime } from "../lib/mediaPresentation.js";
import { containedMediaBox } from "../lib/mediaLayout.js";

/** Track an element's rendered size so overlays can align to letterboxed media. */
function useElementSize() {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setSize({ width: el.clientWidth, height: el.clientHeight });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, size] as const;
}

/**
 * Renders a post's media, letterboxed on black (matching the Plex/slideshow look):
 * Videos autoplay while `active`; slideshows use manual prev/next with continuous
 * audio. Nothing plays unless `active`.
 */
export function PostMedia({ item, active, preload = false }: { item: Item; active: boolean; preload?: boolean }) {
  if (!active && !preload) return <MediaPlaceholder />;
  switch (feedMediaKind(item)) {
    case "video": return <VideoMedia src={item.video_url!} active={active} preload={preload} />;
    case "slideshow": return <SlideMedia images={item.images} audio={item.audio} active={active} />;
    case "offloaded": return <OffloadedExternally />;
    case "expired": return <UnavailableOriginal />;
    default: return <div className="flex h-full w-full items-center justify-center text-sm text-ink-faint">no media yet</div>;
  }
}

function UnavailableOriginal() {
  return <div className="flex h-full w-full flex-col items-center justify-center gap-3 bg-black px-8 text-center text-white/60"><LinkBreak size={36} weight="light" /><div><p className="text-sm font-medium text-white/80">Original post unavailable</p><p className="mt-1 max-w-xs text-xs leading-relaxed">TikTok no longer serves this link. Its place in your archive is preserved and Sync will not keep retrying it.</p></div></div>;
}

function OffloadedExternally() {
  return <div className="flex h-full w-full flex-col items-center justify-center gap-3 bg-black px-8 text-center text-white/60"><Archive size={36} weight="light" /><div><p className="text-sm font-medium text-white/80">Archived on external storage</p><p className="mt-1 max-w-xs text-xs leading-relaxed">This favorite is stored outside this archive, so it can't play here. Its place in your feed is preserved.</p></div></div>;
}

function MediaPlaceholder() {
  return <div aria-hidden="true" className="h-full w-full bg-black" />;
}

function VideoMedia({ src, active, preload }: { src: string; active: boolean; preload: boolean }) {
  const { muted, setMuted, volume, autoLevel, setAutoGain, paused, togglePaused } = usePlayback();
  const ref = useRef<HTMLVideoElement>(null);
  const [autoplayBlocked, setAutoplayBlocked] = useState(false);
  const [ready, setReady] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [boxRef, boxSize] = useElementSize();
  const [mediaSize, setMediaSize] = useState({ w: 0, h: 0 });
  const media = containedMediaBox(boxSize.width, boxSize.height, mediaSize.w, mediaSize.h);

  useEffect(() => {
    setReady(false);
    setWaiting(false);
    setLoadError(false);
    setCurrentTime(0);
    setDuration(0);
  }, [src]);

  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    let alive = true;
    v.muted = muted;
    if (active && !paused) {
      v.play().then(() => alive && active && setAutoplayBlocked(false)).catch(() => alive && active && setAutoplayBlocked(true));
    } else {
      v.pause();
      setAutoplayBlocked(false);
    }
    return () => { alive = false; };
  }, [active, muted, paused, src]);
  useEffect(() => {
    if (ref.current) ref.current.muted = muted;
  }, [muted]);
  useMediaVolume(ref, active, volume, autoLevel, setAutoGain);
  const playWithSound = async () => {
    const media = ref.current;
    if (!media) return;
    void sharedAudioContext?.resume().catch(() => {});
    try {
      await media.play();
      setAutoplayBlocked(false);
    } catch {
      if (muted) return;
      setMuted(true);
      media.muted = true;
      await media.play().then(() => setAutoplayBlocked(false)).catch(() => {});
    }
  };

  const seek = (next: number) => {
    const media = ref.current;
    if (!media || !Number.isFinite(next)) return;
    media.currentTime = Math.max(0, Math.min(duration || 0, next));
    setCurrentTime(media.currentTime);
  };

  return <div ref={boxRef} className="group relative flex h-full w-full items-center justify-center bg-black" aria-busy={active && (!ready || waiting)}>
    <video
      ref={ref}
      src={src}
      preload={active || preload ? "auto" : "none"}
      loop
      playsInline
      muted
      onClick={active ? togglePaused : undefined}
      onCanPlay={() => { setReady(true); setWaiting(false); setLoadError(false); }}
      onPlaying={() => { setReady(true); setWaiting(false); }}
      onWaiting={() => active && setWaiting(true)}
      onLoadedMetadata={(event) => { setDuration(Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : 0); setMediaSize({ w: event.currentTarget.videoWidth, h: event.currentTarget.videoHeight }); }}
      onDurationChange={(event) => setDuration(Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : 0)}
      onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
      onError={() => { setLoadError(true); setWaiting(false); }}
      aria-label={active ? paused ? "Resume video" : "Pause video" : undefined}
      title={active ? paused ? "Click to resume" : "Click to pause" : undefined}
      className={cx("h-full w-full object-contain transition-opacity duration-200", active && !ready ? "opacity-0" : "opacity-100", active && "cursor-pointer")}
    />
    {active && !loadError && (!ready || waiting) && <MediaLoading />}
    {active && loadError && <div role="alert" className="absolute left-1/2 top-1/2 z-10 -translate-x-1/2 -translate-y-1/2 rounded-[var(--radius-control)] border border-white/15 bg-black/70 px-4 py-3 text-sm text-white/80">Video could not be loaded.</div>}
    {active && autoplayBlocked && <button type="button" onClick={() => void playWithSound()} className="absolute left-1/2 top-1/2 z-20 flex -translate-x-1/2 -translate-y-1/2 items-center gap-2 rounded-full bg-black/70 px-4 py-2 text-sm font-medium text-white backdrop-blur-sm"><Play size={16} weight="fill" /> {muted ? "Play video" : "Play with sound"}</button>}
    {active && ready && <div style={{ width: media.width ? `${Math.max(0, media.width - 24)}px` : undefined }} className="pointer-events-none absolute bottom-3 left-1/2 z-30 flex -translate-x-1/2 translate-y-2 items-center gap-2 rounded-[var(--radius-control)] border border-white/10 bg-black/70 px-2.5 py-2 text-white opacity-0 shadow-lg backdrop-blur-md transition group-hover:translate-y-0 group-hover:opacity-100 group-focus-within:translate-y-0 group-focus-within:opacity-100">
      <button type="button" onClick={togglePaused} aria-label={paused ? "Play video" : "Pause video"} className="pointer-events-auto rounded-md p-1.5 hover:bg-white/15">{paused ? <Play size={16} weight="fill" /> : <Pause size={16} weight="fill" />}</button>
      <span className="tabular w-10 text-right text-[11px] text-white/75">{formatMediaTime(currentTime)}</span>
      <input type="range" min="0" max={Math.max(duration, 0.01)} step="0.1" value={Math.min(currentTime, Math.max(duration, 0.01))} onChange={(event) => seek(Number(event.target.value))} aria-label="Video progress" className="pointer-events-auto h-1 min-w-0 flex-1 cursor-pointer accent-white" />
      <span className="tabular w-10 text-[11px] text-white/75">{formatMediaTime(duration)}</span>
    </div>}
  </div>;
}

function MediaLoading() {
  return <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center bg-black" role="status" aria-label="Loading video">
    <div className="relative h-[86%] max-h-[52rem] w-[min(90%,30rem)] rounded-[var(--radius-media)] border border-white/15 bg-white/[0.035]">
      <span className="absolute left-1/2 top-1/2 h-8 w-8 -translate-x-1/2 -translate-y-1/2 animate-spin rounded-full border-2 border-white/20 border-t-white/80" />
    </div>
  </div>;
}

function SlideMedia({ images, audio, active }: { images: string[]; audio: string | null; active: boolean }) {
  const { muted, volume, autoLevel, setAutoGain, paused, togglePaused } = usePlayback();
  const [idx, setIdx] = useState(0);
  const audioRef = useRef<HTMLAudioElement>(null);
  const [boxRef, boxSize] = useElementSize();
  const [imgSize, setImgSize] = useState({ w: 0, h: 0 });
  const media = containedMediaBox(boxSize.width, boxSize.height, imgSize.w, imgSize.h);
  const edgeOffset = media.marginX + 8;

  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;
    a.muted = muted;
    if (active && !paused) a.play().catch(() => {});
    else {
      a.pause();
      a.currentTime = 0;
    }
  }, [active, muted, paused]);
  useMediaVolume(audioRef, active, volume, autoLevel, setAutoGain);

  // Left/right arrow keys flip images while this slideshow is the active post.
  useEffect(() => {
    if (!active || images.length <= 1) return;
    const onNav = (event: Event) => {
      const delta = (event as CustomEvent<{ delta: number }>).detail?.delta ?? 0;
      if (delta) setIdx((i) => (i + delta + images.length) % images.length);
    };
    window.addEventListener("viewer-slide-nav", onNav);
    return () => window.removeEventListener("viewer-slide-nav", onNav);
  }, [active, images.length]);

  const go = (delta: number) => setIdx((i) => (i + delta + images.length) % images.length);

  return (
    <div ref={boxRef} className="relative flex h-full w-full items-center justify-center">
      <img src={images[idx]} alt={`Slide ${idx + 1} of ${images.length}`} onLoad={(event) => setImgSize({ w: event.currentTarget.naturalWidth, h: event.currentTarget.naturalHeight })} className="h-full w-full object-contain" />
      {active && <button type="button" onClick={togglePaused} aria-label={paused ? "Resume slideshow audio" : "Pause slideshow audio"} className="absolute inset-0 z-[1] cursor-pointer"><span className="sr-only">{paused ? "Resume slideshow audio" : "Pause slideshow audio"}</span></button>}
      {audio && <audio ref={audioRef} src={audio} loop />}
      {images.length > 1 && (
        <>
          <SlideNav side="left" onClick={() => go(-1)} offset={edgeOffset} />
          <SlideNav side="right" onClick={() => go(1)} offset={edgeOffset} />
          <div className="pointer-events-none absolute bottom-4 left-1/2 z-10 flex -translate-x-1/2 gap-1.5">
            {images.map((_, i) => (
              <span
                key={i}
                className={cx(
                  "h-1.5 rounded-full transition-all duration-200",
                  i === idx ? "w-4 bg-white" : "w-1.5 bg-white/40",
                )}
              />
            ))}
          </div>
        </>
      )}
      {active && paused && <div aria-hidden="true" className="pointer-events-none absolute left-1/2 top-1/2 z-10 flex -translate-x-1/2 -translate-y-1/2 items-center gap-2 rounded-full bg-black/60 px-4 py-2 text-sm font-medium text-white backdrop-blur-sm"><Play size={16} weight="fill" /> Paused</div>}
    </div>
  );
}

type AudioGraph = {
  context: AudioContext;
  source: MediaElementAudioSourceNode;
  analyser: AnalyserNode;
  compressor: DynamicsCompressorNode;
  gain: GainNode;
  connected: boolean;
};

let sharedAudioContext: AudioContext | null = null;
let audioResumeArmed = false;

function armAudioContextResume(context: AudioContext) {
  if (audioResumeArmed || context.state === "running") return;
  audioResumeArmed = true;
  const resume = () => {
    void context.resume().then(() => {
      if (context.state !== "running") return;
      window.removeEventListener("pointerdown", resume);
      window.removeEventListener("keydown", resume);
      audioResumeArmed = false;
    }).catch(() => {});
  };
  window.addEventListener("pointerdown", resume);
  window.addEventListener("keydown", resume);
}

function connectGraph(graph: AudioGraph) {
  if (graph.connected) return;
  graph.source.connect(graph.analyser);
  graph.analyser.connect(graph.compressor);
  graph.compressor.connect(graph.gain);
  graph.gain.connect(graph.context.destination);
  graph.connected = true;
}

/** Level each playing item's signal toward a stable loudness while preserving the user's volume. */
function useMediaVolume(ref: RefObject<HTMLMediaElement>, active: boolean, volume: number, autoLevel: boolean, onAutoGain: (gain: number) => void) {
  const graphRef = useRef<AudioGraph | null>(null);

  useEffect(() => () => {
    const graph = graphRef.current;
    if (!graph?.connected) return;
    graph.source.disconnect();
    graph.analyser.disconnect();
    graph.compressor.disconnect();
    graph.gain.disconnect();
    graph.connected = false;
  }, []);

  useEffect(() => {
    const media = ref.current;
    if (!media) {
      if (active) onAutoGain(1);
      return;
    }
    const existing = graphRef.current;
    if (!active || (!autoLevel && !existing)) {
      media.volume = volume;
      return;
    }

    let graph = existing;
    if (!graph) {
      const AudioContextConstructor = window.AudioContext ?? (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!AudioContextConstructor) {
        media.volume = volume;
        return;
      }
      try {
        sharedAudioContext ??= new AudioContextConstructor();
        armAudioContextResume(sharedAudioContext);
        const source = sharedAudioContext.createMediaElementSource(media);
        const analyser = sharedAudioContext.createAnalyser();
        const compressor = sharedAudioContext.createDynamicsCompressor();
        const gain = sharedAudioContext.createGain();
        analyser.fftSize = 2048;
        graph = { context: sharedAudioContext, source, analyser, compressor, gain, connected: false };
        graphRef.current = graph;
      } catch {
        media.volume = volume;
        return;
      }
    }

    connectGraph(graph);
    media.volume = 1;
    graph.gain.gain.setTargetAtTime(volume, graph.context.currentTime, 0.08);
    if (!autoLevel) {
      graph.compressor.threshold.setValueAtTime(0, graph.context.currentTime);
      graph.compressor.knee.setValueAtTime(0, graph.context.currentTime);
      graph.compressor.ratio.setValueAtTime(1, graph.context.currentTime);
      onAutoGain(1);
      return;
    }

    graph.compressor.threshold.setValueAtTime(-24, graph.context.currentTime);
    graph.compressor.knee.setValueAtTime(18, graph.context.currentTime);
    graph.compressor.ratio.setValueAtTime(6, graph.context.currentTime);
    graph.compressor.attack.setValueAtTime(0.005, graph.context.currentTime);
    graph.compressor.release.setValueAtTime(0.32, graph.context.currentTime);

    const samples = new Float32Array(graph.analyser.fftSize);
    let smoothedRms = 0;
    let smoothedGain = 1;
    let reportedGain = 1;
    const timer = window.setInterval(() => {
      graph.analyser.getFloatTimeDomainData(samples);
      let sum = 0;
      for (const sample of samples) sum += sample * sample;
      const rms = Math.sqrt(sum / samples.length);
      if (rms < 0.008) return;
      smoothedRms = smoothedRms ? smoothedRms * 0.75 + rms * 0.25 : rms;
      const desiredGain = normalizationGain(smoothedRms);
      smoothedGain += (desiredGain - smoothedGain) * 0.3;
      graph.gain.gain.setTargetAtTime(volume * smoothedGain, graph.context.currentTime, 0.22);
      if (Math.abs(smoothedGain - reportedGain) >= 0.04) {
        reportedGain = smoothedGain;
        onAutoGain(Number(smoothedGain.toFixed(2)));
      }
    }, 160);
    return () => window.clearInterval(timer);
  }, [active, autoLevel, onAutoGain, ref, volume]);
}

function SlideNav({ side, onClick, offset }: { side: "left" | "right"; onClick: () => void; offset: number }) {
  const Icon = side === "left" ? CaretLeft : CaretRight;
  return (
    <button
      onClick={(event) => { event.stopPropagation(); onClick(); }}
      aria-label={side === "left" ? "Previous image" : "Next image"}
      style={{ [side]: `${offset}px` }}
      className={cx(
        "absolute top-1/2 z-10 -translate-y-1/2 rounded-full bg-black/40 p-2 text-white backdrop-blur-sm",
        "transition hover:bg-black/60 active:translate-y-[calc(-50%+1px)]",
      )}
    >
      <Icon size={20} weight="bold" />
    </button>
  );
}
