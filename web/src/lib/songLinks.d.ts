import type { Song } from "./types";

export function songSearchQuery(song: Song): string;
export function spotifyUrl(song: Song): string;
export function appleMusicUrl(song: Song): string;
export function youtubeUrl(song: Song): string;
export function primarySongUrl(song: Song): string;
export function songLabel(song: Song): string;
