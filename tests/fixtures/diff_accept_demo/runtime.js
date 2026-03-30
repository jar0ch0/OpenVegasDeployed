export function formatRuntime(seconds) {
  const s = Number(seconds || 0);
  const mins = Math.floor(s / 60);
  const rem = Math.floor(s % 60);
  return `${mins}m ${rem}s`;
}

export function formatCredits(v) {
  const n = Number(v || 0);
  return `${n.toFixed(2)} $V`;
}

