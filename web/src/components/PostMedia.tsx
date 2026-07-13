import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { Archive, CaretLeft, CaretRight, LinkBreak, Play } from "@phosphor-icons/react";
import type { Item } from "../lib/types";
import { feedMediaKind } from "../lib/feedItems";
import { cx } from "./ui";
import { usePlayback } from "./playback";
import { normalizationGain } from "../lib/playbackVolume.js";

/**
 * Renders a post's media, letterboxed on black (matching the Plex/slideshow look):
 * videos autoplay while `active`; slideshows auto-advance (2.5s) with their audio,
 * plus manual prev/next. Nothing plays unless `active`.
 */
export function PostMedia({ item, active, transitioning = false, preload = false }: { item: Item; active: boolean; transitioning?: boolean; preload?: boolean }) {
  const { muted, setMuted, volume, autoLevel, setAutoGain, paused, togglePaused } = usePlayback();
  if (!active && !transitioning && !preload) return <MediaPlaceholder />;
  switch (feedMediaKind(item)) {
    case "video": return <VideoMedia src={item.video_url!} active={active} transitioning={transitioning} muted={muted} onAutoplayFallback={() => setMuted(true)} volume={volume} autoLevel={autoLevel} onAutoGain={setAutoGain} paused={paused} onTogglePaused={togglePaused} preload={preload} />;
    case "slideshow": return <SlideMedia images={item.images} audio={item.audio} active={active} muted={muted} volume={volume} autoLevel={autoLevel} onAutoGain={setAutoGain} paused={paused} onTogglePaused={togglePaused} />;
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

function VideoMedia({ src, active, transitioning, muted, onAutoplayFallback, volume, autoLevel, onAutoGain, paused, onTogglePaused, preload }: { src: string; active: boolean; transitioning: boolean; muted: boolean; onAutoplayFallback: () => void; volume: number; autoLevel: boolean; onAutoGain: (gain: number) => void; paused: boolean; onTogglePaused: () => void; preload: boolean }) {
  const ref = useRef<HTMLVideoElement>(null);
  const [autoplayBlocked, setAutoplayBlocked] = useState(false);
  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    let alive = true;
    if ((active || transitioning) && !paused) {
      v.play().then(() => alive && active && setAutoplayBlocked(false)).catch(() => alive && active && setAutoplayBlocked(true));
    } else {
      v.pause();
      setAutoplayBlocked(false);
    }
    return () => { alive = false; };
  }, [active, paused, transitioning]);
  useEffect(() => {
    if (ref.current) ref.current.muted = muted || transitioning;
  }, [muted, transitioning]);
  useMediaVolume(ref, active, volume, autoLevel, onAutoGain);
  const playWithSound = async () => {
    const media = ref.current;
    if (!media) return;
    void sharedAudioContext?.resume().catch(() => {});
    try {
      await media.play();
      setAutoplayBlocked(false);
    } catch {
      if (muted) return;
      onAutoplayFallback();
      media.muted = true;
      await media.play().then(() => setAutoplayBlocked(false)).catch(() => {});
    }
  };
  return <>
    <video ref={ref} src={src} preload={active || preload ? "auto" : "none"} loop playsInline muted onClick={active ? onTogglePaused : undefined} aria-label={active ? paused ? "Resume video" : "Pause video" : undefined} title={active ? paused ? "Click to resume" : "Click to pause" : undefined} className="max-h-full max-w-full cursor-pointer object-contain" />
    {active && autoplayBlocked && <button type="button" onClick={() => void playWithSound()} className="absolute left-1/2 top-1/2 z-10 flex -translate-x-1/2 -translate-y-1/2 items-center gap-2 rounded-full bg-black/65 px-4 py-2 text-sm font-medium text-white backdrop-blur-sm"><Play size={16} weight="fill" /> {muted ? "Play video" : "Play with sound"}</button>}
    {active && paused && <div aria-hidden="true" className="pointer-events-none absolute left-1/2 top-1/2 z-10 flex -translate-x-1/2 -translate-y-1/2 items-center gap-2 rounded-full bg-black/60 px-4 py-2 text-sm font-medium text-white backdrop-blur-sm"><Play size={16} weight="fill" /> Paused</div>}
  </>;
}

const SLIDE_MS = 2500;

function SlideMedia({
  images,
  audio,
  active,
  muted,
  volume,
  autoLevel,
  onAutoGain,
  paused,
  onTogglePaused,
}: {
  images: string[];
  audio: string | null;
  active: boolean;
  muted: boolean;
  volume: number;
  autoLevel: boolean;
  onAutoGain: (gain: number) => void;
  paused: boolean;
  onTogglePaused: () => void;
}) {
  const [idx, setIdx] = useState(0);
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    if (!active || paused || images.length < 2) return;
    const t = window.setInterval(() => setIdx((i) => (i + 1) % images.length), SLIDE_MS);
    return () => window.clearInterval(t);
  }, [active, images.length, paused]);

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
  useMediaVolume(audioRef, active, volume, autoLevel, onAutoGain);

  const go = (delta: number) => setIdx((i) => (i + delta + images.length) % images.length);

  return (
    <div className="relative flex h-full w-full items-center justify-center" onClick={active ? onTogglePaused : undefined} role={active ? "button" : undefined} aria-label={active ? paused ? "Resume slideshow" : "Pause slideshow" : undefined}>
      <img src={images[idx]} alt="" className="max-h-full max-w-full object-contain" />
      {audio && <audio ref={audioRef} src={audio} loop />}
      {images.length > 1 && (
        <>
          <SlideNav side="left" onClick={() => go(-1)} />
          <SlideNav side="right" onClick={() => go(1)} />
          <div className="absolute bottom-4 left-1/2 flex -translate-x-1/2 gap-1.5">
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
    void graph.context.resume().catch(() => {});
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

function SlideNav({ side, onClick }: { side: "left" | "right"; onClick: () => void }) {
  const Icon = side === "left" ? CaretLeft : CaretRight;
  return (
    <button
      onClick={(event) => { event.stopPropagation(); onClick(); }}
      aria-label={side === "left" ? "Previous image" : "Next image"}
      className={cx(
        "absolute top-1/2 -translate-y-1/2 rounded-full bg-black/40 p-2 text-white backdrop-blur-sm",
        "transition hover:bg-black/60 active:translate-y-[calc(-50%+1px)]",
        side === "left" ? "left-3" : "right-3",
      )}
    >
      <Icon size={20} weight="bold" />
    </button>
  );
}
