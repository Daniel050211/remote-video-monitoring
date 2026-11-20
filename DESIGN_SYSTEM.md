# Design system — Remote Video Monitoring

Use this file as the design guide for future pages, sections, and
components so the interface stays visually consistent.

## 1. Surface profile

Hybrid of **Redesign** and **Dashboard / product UI** for a local camera
control room (ui-ux-kit §B2, with §B3 state and action rules where they
help). Single-page Flask app; English copy; must work offline on a
trusted LAN.

**Design read:** a control-room monitoring surface for a course
demonstration audience, restrained chromatic ink/slate with one
steel-teal accent, system UI type, CSS-only motion, built in Flask and
vanilla HTML/CSS/JS.

## 2. Concept

This interface is a local camera control room that keeps the live video
feed as the one loud idea, with stream health and controls kept quiet
around it.

Signature moments:

1. The live MJPEG frame is the focal point: largest element, darkest
   stage, not another card.
2. Live operational state (connection, motion, faces, recording) is
   glanceable as compact labeled rows, not a grid of equal pills.
3. Save snapshot is the everyday primary action (steel-teal). Start
   recording is the destructive action (separate fill, separate
   placement).

Category-reflex check: the obvious “security dashboard” palette (near
black, neon red/green, CRT scanlines) was rejected. Ink/slate is tinted
toward the teal accent; semantic red/green are used only for real state
and are always paired with text.

## 3. Color tokens

Three-tier tokens live in `static/style.css` (`:root`). Components use
semantic or component tokens, not raw primitives.

### Primitives

| Token | Hex |
|---|---|
| `--ink-950` | `#0c1012` |
| `--ink-900` | `#141c1f` |
| `--ink-850` | `#1b2529` |
| `--ink-800` | `#223033` |
| `--ink-700` | `#2c3c41` |
| `--ink-600` | `#3d5257` |
| `--ink-400` | `#8f999d` |
| `--ink-100` | `#e6eef0` |
| `--ink-on-accent` | `#0e1a1a` |
| `--ink-on-danger` | `#140c0c` |
| `--ink-on-warn` | `#1a1408` |
| `--teal-500` | `#3d9a97` |
| `--teal-400` | `#46a8a5` |
| `--teal-600` | `#348885` |
| `--ok-500` | `#3cba8a` |
| `--warn-500` | `#d9a441` |
| `--error-400` | `#e88980` |
| `--error-600` | `#c85a54` |
| `--alert-error-bg` / `--alert-error-text` | `#3a1e1c` / `#f3d0ce` |
| `--alert-notice-bg` / `--alert-notice-text` | `#3a2f14` / `#f3e3b0` |

The video stage uses `--ink-950`, a near-black monitor bezel. This is a
deliberate stage color, not the page background, and is not a generic
`#000` / OLED-luxury default.

### Semantic and component roles (60/30/10)

- **60% dominant:** `--bg` (`#141c1f`) page ink.
- **30% secondary:** `--surface` / `--surface-raised` for the log well
  and quiet grouping; `--border` as token dividers in metric lists.
- **10% accent:** `--accent` steel-teal for Save snapshot, focus rings,
  and range/checkbox accents.

Semantic `--ok`, `--warn`, and `--error` are only for real operational
state (connection, motion hit, recording, alerts). Color is never the
only cue; every state keeps a text label.

Computed WCAG contrast (sRGB relative luminance, this pass):

| Pair | Ratio | Floor |
|---|---|---|
| Body `#e6eef0` on page / surface / raised | 14.69 / 13.29 / 11.60 | AA 4.5 |
| Muted `#8f999d` on page / surface / raised | 5.93 / 5.37 / 4.69 | AA 4.5 |
| Accent button `#3d9a97` on `#0e1a1a` | 5.31 | AA 4.5 |
| Focus ring `#3d9a97` on page | 5.16 | UI 3.0 |
| OK `#3cba8a` on page / raised | 7.06 / 5.58 | AA 4.5 |
| Error text `#e88980` on page / surface / raised | 6.85 / 6.19 / 5.41 | AA 4.5 |
| Danger button `#c85a54` / hover `#d26660` / active `#c45a54` on `#140c0c` | 4.64 / 5.34 / 4.54 | AA 4.5 |
| Secondary `#3d5257` on `#e6eef0` | 7.02 | AA 4.5 |
| Warn badge `#d9a441` on `#1a1408` | 8.14 | AA 4.5 |
| Alert error / notice text on their fills | 10.65 / 10.29 | AA 4.5 |

Single dark theme only. No light-mode inversion in this product.

## 4. Typography

Personality: dense, technical, utilitarian control room.

Intentional system stack (offline LAN demo; no Google Fonts, no CDN):

`"Segoe UI", system-ui, sans-serif`

Scale (use only these steps):

| Token | Size | Use |
|---|---|---|
| `--text-label` | 0.8125rem (13px) | Metric labels only |
| `--text-body` | 1rem (16px) | Body, hints, buttons, footer, values |
| `--text-section` | 1.125rem (18px) | Section headings |
| `--text-title` | 1.5rem (24px) | Page title (`h1`) |

Deliberate typographic detail: `font-variant-numeric: tabular-nums` on
metrics, times, counts, and IDs such as `#fps` and `#face-count`.
Headings are normal case. Do not use tiny uppercase mono labels,
`//` separators, or `[BRACKET]` chrome.

## 5. Spacing, radius, motion

Spacing scale: 4, 8, 12, 16, 24, 32, 48, 64 (`--space-1` … `--space-8`).

Radius: `--radius-sm` 4px (controls, badge, stage), `--radius-md` 8px
(reserved). Do not apply one large radius and a matching soft shadow to
every block.

Motion tokens: `--duration-instant` 80ms, `--duration-fast` 150ms,
`--duration-base` 220ms; `--ease-standard`, `--ease-enter`,
`--ease-exit`. Animate only `transform` and `opacity`. Honor
`prefers-reduced-motion` (transitions and animations off).

## 6. Layout

Content width: `min(1200px, 100%)`. Desktop (≥1080px): live `#stream` in
a dark stage with a 280px side rail for primary actions and glanceable
live state. From 720px, Stream / Activity clusters and the detection
panels sit in two columns. Below that, a single column: video, actions
(≥44px touch targets), compact status, then panels. No horizontal
overflow. Essential feedback does not depend on hover.

`#source-badge` lives in the header, not over the frame. The long
technical footer stays accurate inside a `<details>` disclosure.

## 7. States

Style all of these (already toggled by `static/app.js`):

- Connection: `ok` / `bad`
- Motion: `motion-on` / `motion-hit` / `motion-off`
- Faces: `faces-on` / `faces-hit` / `faces-off`
- Recording: `recording-on` / `recording-idle` / `recording-error`
- Result copy: `ok` / `bad`
- `#alert` `alert-error` / `alert-notice` (must stay obvious)
- Buttons: default, hover, `:focus-visible`, active, disabled
- Motion log: default rows and `.empty`
- `#snapshot-preview` and `#recording-error`: `.hidden` when unused

Skip-to-content, semantic landmarks (`header`, `main`, labelled
sections), visible `:focus-visible` rings, and existing `aria-live`
regions are required.

## 8. What not to do (anti-slop)

- No purple/indigo gradients, neon palettes, glass glow, aurora
  backgrounds, or dark + gold “luxury”
- No emoji as chrome; no Inter / Space Grotesk / JetBrains Mono via CDN
- No card around every metric; no 14 equal-weight pills
- No side-stripe accents, gradient text, or decorative grids
- No invented stats or hype copy
- Do not change API behavior, element IDs that JS binds to, or
  detection logic in order to style the page
- Borders are token dividers and control outlines, not a substitute
  for the dark video stage as the primary hierarchy

## 9. Overlay and favicon notes

On synthetic frames, the burned-in red `SYNTHETIC SOURCE` banner stays
at the top of the image. The `Faces: N` badge is drawn immediately below
that banner (top-left when no banner is present). MOTION stays
top-right; the timestamp stays bottom-right.

Favicon: `static/favicon.svg` and `static/favicon.ico`, also served at
`/favicon.ico`. Local files only.

## 10. Attribution

Design direction follows these agent skills (not copied wholesale into
this repo):

- [Polished UI Skills](https://github.com/iamaanahmad/polished-ui-skills)
  — workflow, tokens, anti-patterns, pre-ship gate
- [UI/UX Kit](https://github.com/arham777/ui-ux-kit)
  — routing, concept, dashboard surface rules, countable anti-slop gate
