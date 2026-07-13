/** Where an `object-contain` media element actually renders inside its box, plus
    the empty letterbox margins around it. Lets overlays (seek bar, slideshow
    arrows) align to the visible media instead of the full container. Returns the
    whole container box when any dimension is unknown (nothing to letterbox yet). */
export function containedMediaBox(containerWidth, containerHeight, mediaWidth, mediaHeight) {
  const cw = Number(containerWidth) || 0;
  const ch = Number(containerHeight) || 0;
  const mw = Number(mediaWidth) || 0;
  const mh = Number(mediaHeight) || 0;
  if (cw <= 0 || ch <= 0 || mw <= 0 || mh <= 0) {
    return { width: cw, height: ch, marginX: 0, marginY: 0 };
  }
  const scale = Math.min(cw / mw, ch / mh);
  const width = mw * scale;
  const height = mh * scale;
  return { width, height, marginX: (cw - width) / 2, marginY: (ch - height) / 2 };
}
