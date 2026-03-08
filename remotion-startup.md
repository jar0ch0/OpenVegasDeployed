# Remotion Startup

```bash
cd /Users/stephenekwedike/Desktop/OpenVegas/my-video
npm i
npm run dev
```

Then open Remotion Studio (usually http://localhost:3000) and select OpenVegasHorseRace.

## OpenVegas Dark/Cryptic Style Contract (Required)

Use this for all Remotion scenes, still exports, and landing assets so video + site feel like one system.

### Visual Language

1. Palette:
   - `#000000` (primary background)
   - `#1A1A1A` (grid/borders/dividers)
   - `#4A4A4A` and `#8A8A8A` (secondary metadata text)
   - `#5CB8E4` (single accent for highlights/telemetry/wins)
2. Typography:
   - Sans for headlines: modern, clean, low-weight.
   - Mono for metadata: uppercase labels, tracking, terminal/system tone.
3. Contrast rules:
   - Keep 80-90% of frames in black/grey.
   - Reserve cyan for high-signal moments: odds shift, overtake, finish, CTA.
4. Composition:
   - Use grid lines, card frames, and thin borders.
   - Prefer asymmetric layout blocks and terminal-style meta strips.
5. Motion:
   - Slow push-ins and lateral tracking for tension.
   - Quick accent flashes only on meaningful events (lead change, payout event).

Render video:

```bash
npx remotion render OpenVegasHorseRace out/openvegas-horse.mp4
```

Render still images (for landing page):

```bash
npx remotion still OpenVegasHorseRace out/horse-hero-1.png --frame=90
npx remotion still OpenVegasHorseRace out/horse-hero-2.png --frame=220
npx remotion still OpenVegasHorseRace out/horse-hero-3.png --frame=360
```

## Content Tone (Cryptic + Infra-Forward)

Use terse, systems-style copy. Avoid playful casino copy or generic startup slogans.

1. Good copy pattern:
   - `DIRECTORY: OPENVEGAS_RACECORE_V2`
   - `SESSION MODE: WAGERED_COMPUTE`
   - `TRACK TELEMETRY: ACTIVE`
   - `ODDS DRIFT: +12.4%`
2. CTA pattern:
   - `DEPLOY RISK`
   - `ROUTE COMPUTE`
   - `WAGER TOKENS`
3. Avoid:
   - Emoji, excessive punctuation, bright gradients, meme copy.
   - Purple/neon rainbow palettes that break the brand system.

## Common Remotion Commands

```bash
# list compositions
npx remotion compositions

# render at 1080p explicitly
npx remotion render OpenVegasHorseRace out/openvegas-horse-1080p.mp4 --width=1920 --height=1080

# render a short preview cut
npx remotion render OpenVegasHorseRace out/openvegas-preview.mp4 --frames=0-180

# render a single hero still
npx remotion still OpenVegasHorseRace out/hero-frame.png --frame=300
```

## Shot Presets Aligned To Landing Aesthetic

1. `Cold Open (0-2.5s)`:
   - Black frame, subtle scanline/noise.
   - Mono labels fade in: `NODE_ALPHA`, `RACE_INIT`, `POOL_LOCKED`.
2. `Track Reveal (2.5-6s)`:
   - Wide shot with grid overlays and lane markers in dark grey.
   - Cyan only on active horse indicator + speed trace.
3. `Hero Close-Up (6-10s)`:
   - Extreme close on one horse profile (head-first direction only).
   - Add low-amplitude camera sway + brief neigh SFX.
4. `Overtake Event (10-13s)`:
   - Side tracking shot, compressed depth, velocity streaks.
   - Flash compact telemetry panel: `LEAD_CHANGE DETECTED`.
5. `Finish + End Card (13-16s)`:
   - Freeze on winner lane crossing.
   - End card with sparse copy + cyan CTA.

## How To Direct Video Enhancements

When requesting enhancements, provide direction in this format:

1. Goal: what the scene should make the viewer feel.
2. Shot list: exact moments/time ranges for each camera move.
3. Motion: zoom/pan/shake intensity and speed.
4. Audio: what SFX/music/voiceover should happen and when.
5. Branding: what logo/tagline/CTA text must appear.

Use this template:

```text
Goal: High-stakes, cinematic race energy with premium infra vibe.
Shot 1 (0-3s): Wide track reveal, slow push-in.
Shot 2 (3-6s): Extreme close-up on Thunder Byte eye + mane motion.
Shot 3 (6-10s): Side tracking shot while overtaking happens.
Shot 4 (10-13s): Finish-line impact + speed lines + glow.
Shot 5 (13-16s): End card with OpenVegas logo + CTA.
Audio: Add horse neigh at 3.2s and 10.8s, crowd swell at 9s, low cinematic bass throughout.
Branding: Use OpenVegas aqua accent, monospace labels, "Wagered Compute" tagline.
```

## Directing Prompt Add-On (Use This Every Time)

Append this block to any future Remotion request so outputs stay on-brand:

```text
Style lock:
- Keep black/grey/cyan system (#000, #1A1A1A, #4A4A4A, #8A8A8A, #5CB8E4).
- Use cryptic mono metadata labels and sparse uppercase UI copy.
- Keep scenes minimal, high-contrast, and infrastructure-coded.
- No colorful casino neon style; no playful cartoon framing.
```

## Notes For Cinematic Horse Close-Ups + Neighing

1. Add close-up camera keyframes around one horse (`interpolate` on scale/translate).
2. Add layered depth (foreground blur + background parallax).
3. Add an audio file (horse neigh) in `my-video/public/` and trigger via Remotion `<Audio />` with `startFrom` and `volume` automation.
4. Cut between wide and close shots to avoid static motion.
5. Export both: cinematic MP4 + stills for landing page hero blocks.

## If You Want More From Me Next

Ask for one of these directly:

1. "Implement cinematic camera system with keyframed zooms."
2. "Add horse neigh + race ambience audio sync."
3. "Create a 30s marketing cut with intro, race, and end card."
4. "Create 6 landing-page stills with named shot presets."

## Asset Export Targets For Landing Page

Use these compositions/stills so the landing page sections match the same art direction:

1. Hero still: horse profile close-up + telemetry overlay.
2. Card still A: wide track with lane grid + odds strip.
3. Card still B: overtaking frame with cyan lead marker.
4. Card still C: finish-line freeze with result banner.
5. Footer ambient loop: slow parallax track background (5-8s, no hard cuts).
