import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { readCaptionPreference } from "../lib/lensPresentation.js";
import { readPlaybackVolume } from "../lib/playbackVolume.js";

type Playback = {
  muted: boolean;
  setMuted: (muted: boolean) => void;
  toggleMuted: () => void;
  volume: number;
  setVolume: (volume: number) => void;
  autoLevel: boolean;
  toggleAutoLevel: () => void;
  autoGain: number;
  setAutoGain: (gain: number) => void;
  paused: boolean;
  togglePaused: () => void;
  setPaused: (paused: boolean) => void;
  captionsEnabled: boolean;
  toggleCaptions: () => void;
};

const PlaybackContext = createContext<Playback | null>(null);

/** Owns mute state for one visible Favorite playback session. */
export function PlaybackSession({ children, initiallyMuted = false }: { children: ReactNode; initiallyMuted?: boolean }) {
  const [muted, setMuted] = useState(initiallyMuted);
  const [volume, setVolumeState] = useState(() => readPlaybackVolume(localStorage.getItem("playback-volume")));
  const [autoLevel, setAutoLevel] = useState(() => localStorage.getItem("playback-auto-level") !== "false");
  const [autoGain, setAutoGain] = useState(1);
  const [paused, setPaused] = useState(false);
  const [captionsEnabled, setCaptionsEnabled] = useState(
    () => readCaptionPreference(localStorage.getItem("playback-captions")),
  );
  const setVolume = (next: number) => setVolumeState(Math.max(0, Math.min(1, next)));

  useEffect(() => localStorage.setItem("playback-volume", String(volume)), [volume]);
  useEffect(() => localStorage.setItem("playback-auto-level", String(autoLevel)), [autoLevel]);
  useEffect(() => localStorage.setItem("playback-captions", String(captionsEnabled)), [captionsEnabled]);
  useEffect(() => { if (!autoLevel) setAutoGain(1); }, [autoLevel]);

  return (
    <PlaybackContext.Provider value={{ muted, setMuted, toggleMuted: () => setMuted((value) => !value), volume, setVolume, autoLevel, toggleAutoLevel: () => setAutoLevel((value) => !value), autoGain, setAutoGain, paused, togglePaused: () => setPaused((value) => !value), setPaused, captionsEnabled, toggleCaptions: () => setCaptionsEnabled((value) => !value) }}>
      {children}
    </PlaybackContext.Provider>
  );
}

export function usePlayback() {
  const playback = useContext(PlaybackContext);
  if (!playback) throw new Error("usePlayback must be used within PlaybackSession");
  return playback;
}
