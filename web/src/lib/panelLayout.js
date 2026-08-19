/** Gesture rules for the Feed's post details panel.
 *
 * Kept as plain JS (like viewerFeed.js) so the behavior suites can import it
 * directly under node without a build step.
 */

/** Width of the details panel, in CSS pixels. */
export const PANEL_WIDTH = 400;

/**
 * Whether a wheel gesture belongs to a region that owns its own scrolling.
 *
 * The Viewer swallows every vertical wheel to drive one-post-per-gesture
 * snapping. The comment list opts out completely: reaching the end of a
 * conversation should stop, not fling you into the next video. `chain` runs
 * from the event target outwards, stopping before the feed container.
 */
export function ownsWheel(chain) {
  return (chain ?? []).some((box) => box && box.ownsWheel);
}
