import type { Item, StoryChapter } from "./types";

export function readStoryQueue(value: string | null | undefined): number[];
export function moveStoryChapter(chapters: StoryChapter[], from: number, direction: -1 | 1): StoryChapter[];
export function storyDuration(chapters: StoryChapter[], items: Item[]): number;
