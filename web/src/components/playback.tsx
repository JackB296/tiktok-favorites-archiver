import { createContext, useContext, useState } from "react";
import type { ReactNode } from "react";

type Playback = {
  muted: boolean;
  toggleMuted: () => void;
  paused: boolean;
  togglePaused: () => void;
  setPaused: (paused: boolean) => void;
};

const PlaybackContext = createContext<Playback | null>(null);

/** Owns mute state for one visible Favorite playback session. */
export function PlaybackSession({ children, initiallyMuted }: { children: ReactNode; initiallyMuted: boolean }) {
  const [muted, setMuted] = useState(initiallyMuted);
  const [paused, setPaused] = useState(false);
  return (
    <PlaybackContext.Provider value={{ muted, toggleMuted: () => setMuted((value) => !value), paused, togglePaused: () => setPaused((value) => !value), setPaused }}>
      {children}
    </PlaybackContext.Provider>
  );
}

export function usePlayback() {
  const playback = useContext(PlaybackContext);
  if (!playback) throw new Error("usePlayback must be used within PlaybackSession");
  return playback;
}
