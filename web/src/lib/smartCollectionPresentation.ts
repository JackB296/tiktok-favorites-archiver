export function smartCollectionConfirmation(action: "offload" | "ignore", count: number): string {
  const verb = action === "offload" ? "Mark" : "Ignore";
  return `${verb} ${count} current favorite${count === 1 ? "" : "s"}? Membership will be checked again when applied.`;
}

