export interface ContainedBox {
  width: number;
  height: number;
  marginX: number;
  marginY: number;
}

export function containedMediaBox(
  containerWidth: number,
  containerHeight: number,
  mediaWidth: number,
  mediaHeight: number,
): ContainedBox;
