import { useState } from "react";
import type { GalleryPresetFilters } from "./types";
import { applyPreset as applyPresetFilters, emptyFilters, filtersFromUrl } from "./galleryFilters";
import type { GalleryFilterKey, GalleryFiltersState } from "./galleryFilters";

/** One shuffle per Random selection; the seed keeps cursor pages repeat-free. */
function newShuffleSeed() {
  return Math.floor(Math.random() * 2_147_483_647);
}

/** The Gallery filter panel as one state object. All policy (URL mapping, page
    queries, presets, chips) lives in the pure functions in galleryFilters.ts —
    this hook only holds the state and reshuffles the Random-order seed. */
export function useGalleryFilters(initialParams: URLSearchParams) {
  const [state, setState] = useState<GalleryFiltersState>(() => filtersFromUrl(initialParams));
  const [randomSeed, setRandomSeed] = useState(newShuffleSeed);

  function set<K extends GalleryFilterKey>(key: K, value: GalleryFiltersState[K]) {
    if (key === "order" && (value as unknown) === "random") setRandomSeed(newShuffleSeed());
    setState((current) => {
      const next = { ...current };
      next[key] = value;
      return next;
    });
  }

  function clearField<K extends GalleryFilterKey>(key: K) {
    setState((current) => {
      const next = { ...current };
      next[key] = emptyFilters()[key];
      return next;
    });
  }

  function clear() {
    setState(emptyFilters());
  }

  function applyPreset(preset: GalleryPresetFilters) {
    const next = applyPresetFilters(preset);
    if (next.order === "random") setRandomSeed(newShuffleSeed());
    setState(next);
  }

  return { state, randomSeed, set, clearField, clear, applyPreset };
}
