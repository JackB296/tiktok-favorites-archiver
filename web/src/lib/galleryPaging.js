export function shouldLoadMore(scrollTop, clientHeight, scrollHeight, threshold = 1_200) {
  if (clientHeight <= 0 || scrollHeight <= 0) return false;
  return scrollHeight - (scrollTop + clientHeight) <= threshold;
}
