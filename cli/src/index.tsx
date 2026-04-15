/**
 * src/index.tsx
 *
 * Dev entry point — re-exports the bin entry so `bun run dev` works
 * (`package.json` dev script: "bun run src/index.tsx").
 *
 * The canonical CLI entry for compiled binaries is bin/openvegas.ts.
 */

import '../bin/openvegas.js';
