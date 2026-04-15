/**
 * useExitTrap.ts
 *
 * Intercepts Ctrl+C via Ink's useInput hook. Mounts once at the App root.
 *
 * BEHAVIOR
 * ────────
 *   First Ctrl+C:  flips ui.isExiting = true → mounts <ExitModal>
 *   Second Ctrl+C: calls Ink's exit() for a clean unmount → process exits
 *   'y' / 'Y':     same as second Ctrl+C (explicit confirm)
 *   Enter / Esc:   flips ui.isExiting = false → dismisses modal, resumes session
 *
 * REQUIREMENT
 * ───────────
 *   The Ink render call in bin/openvegas.ts must set:
 *     render(<App />, { exitOnCtrlC: false })
 *   Without this, Ink exits on the first Ctrl+C before this hook fires.
 */

import { useInput, useApp } from 'ink';
import { useStore } from '../store';

export function useExitTrap(): void {
  const isExiting = useStore((s) => s.ui.isExiting);
  const setExiting = useStore((s) => s.ui.setExiting);
  const { exit } = useApp();

  useInput((input, key) => {
    // Ctrl+C always handled here (exitOnCtrlC: false must be set on render)
    if (key.ctrl && input === 'c') {
      if (isExiting) {
        exit();           // second Ctrl+C → clean Ink unmount
      } else {
        setExiting(true); // first Ctrl+C → show modal
      }
      return;
    }

    // Keys only matter while the exit modal is open
    if (!isExiting) return;

    if (input.toLowerCase() === 'y') {
      exit();             // explicit confirm → exit
    } else if (key.return || key.escape) {
      setExiting(false);  // dismiss modal, resume session
    }
  });
}
