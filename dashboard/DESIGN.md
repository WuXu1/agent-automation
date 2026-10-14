# Design

This file records the look and how it is applied. Mode: **Operate** (the owner checks state and
fixes a memory), with one **Experience** surface: the Second Brain constellation.

## World

A night observatory. The constellation is the sky; every other view is an instrument panel in the same dome (the sky stays
behind every view, dimmed to 30 % and paused). The grid overlay is the dome's own coordinate grid (declination circles
every 20°, meridians every 30°) drawn in the 3D scene, so it turns with the sky instead of sitting flat on the page.

## Colour (one meaning each, never decoration)

| Token | Value | Means |
|---|---|---|
| `--color-void` | `#05070a` | page background |
| `--color-deck` | `#0a0b10` | rail, top bar, second neutral layer |
| `--color-glass` | `rgb(14 17 26 / 0.66)` + 16px blur | panels that sit over the sky |
| `--color-line` | `rgb(148 163 184 / 0.12)` | 1px borders (the only elevation on panels) |
| `--color-ink` / `-dim` / `-faint` | `#e7eaf3` / `#a3abbd` / `#7c8599` | text: 16.8:1, 8.8:1, 5.4:1 on the void (5.1:1 on glass) |
| `--color-memory` | `#00f0ff` cyan | memory nodes, search, heartbeat |
| `--color-agent` | `#d946ef` violet | agent telemetry, the chief's arcs, high priority |
| `--color-ok` | `#10b981` emerald | healthy, done, money fine |
| `--color-runway` | `#f59e0b` amber | credit runway, rate limits, warnings |
| `--color-alarm` | `#ef4444` red | errors, disk threshold, hard caps |

Clusters in the constellation are tints of cyan shifted in hue (never the semantic colours), so violet still means "agent" there.
Agent Studio's departments are violet shifted in hue for the same reason (the specialists' lane is `#c084fc`); a
department's lines and busy cards carry its tint, amber still means waiting.

## Type

Geist (UI, 13/14/16/20/28 px, ratio about 1.2) and JetBrains Mono for numbers, ids, timestamps and coordinates only, with
`tabular-nums`. Self-hosted via Fontsource, no Google request.

## Shape and depth

Panels: radius 14px, 1px `--color-line` border, glass fill, no shadow. Drawers and the palette: one soft offset shadow, no border
glow. Pills only for small status chips.

## Motion

Durations 150–250 ms, `--ease-out: cubic-bezier(0.23, 1, 0.32, 1)`, drawers `cubic-bezier(0.32, 0.72, 0, 1)` at 320 ms. The one
authored moment: selecting a memory flies the camera to it (spring) while the inspector slides in. The sky is never still: memories are stars that breathe on their own clocks, each theme sits in a faint dust cloud that turns slowly about its
centre, and a bead of light now and then runs along a link, all in shaders. In Agent Studio a line runs (dashes flowing towards
whoever does the work) only while two agents share an open card, and a spark crosses the chart once per new hand-off. Healthy daemons breathe
(opacity, 3 s). The ⌘K palette opens with no animation (opened many times a day). `prefers-reduced-motion`: no camera flights, no
auto-rotate, no breathing; fades stay.

## Sound

Off by default, a toggle in the top bar. Short WebAudio clicks synthesized on the fly (no audio files).
