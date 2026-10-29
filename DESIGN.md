---
# gstack: design-md-format=spec
name: DataDraft
description: Navy ink on paper, a championship-gold rule and one stencil stamp. A fantasy trade ruling that reads like the final word, built for Sunday daylight.
colors:
  paper: "#F7F7F5"
  surface: "#FFFFFF"
  text: "#0E1726"
  text-muted: "#4A5568"
  hairline: "#E2E4E8"
  primary: "#0E1726"
  on-primary: "#FFFFFF"
  accent: "#C9A24A"
  success: "#1E6B47"
  error: "#8F1D22"
  warning: "#FBF4E2"
  info: "#1F4E8C"
  verdict-accept: "#1E6B47"
  verdict-accept-tint: "#EAF2EC"
  verdict-counter: "#1F4E8C"
  verdict-counter-tint: "#E8EEF6"
  verdict-tossup: "#5B6270"
  verdict-tossup-tint: "#EEEFF2"
  verdict-reject: "#8F1D22"
  verdict-reject-tint: "#F6E9E8"
  verdict-invalid: "#0E1726"
  verdict-invalid-tint: "#EEEFF2"
  verdict-unsupported: "#5C5A52"
  verdict-unsupported-tint: "#F0EFEC"
  card-ground: "#0E1726"
  card-text: "#F7F7F5"
  card-gain: "#6FCF97"
  card-loss: "#F2878A"
  night-paper: "#0B1220"
  night-surface: "#121A2B"
  night-text: "#E9ECF2"
  night-text-muted: "#9AA3B2"
  night-hairline: "#243047"
  night-gain: "#6FCF97"
  night-loss: "#F2878A"
typography:
  stamp:
    fontFamily: Big Shoulders Stencil Display
    fontWeight: 800
    fontSize: clamp(3.5rem, 7vw, 5rem)
    lineHeight: 0.9
  display:
    fontFamily: Big Shoulders Display
    fontWeight: 800
    fontSize: clamp(3.5rem, 8vw, 6rem)
    lineHeight: 0.92
  heading:
    fontFamily: Big Shoulders Display
    fontWeight: 700
    fontSize: 2.75rem
    lineHeight: 1
  body:
    fontFamily: Atkinson Hyperlegible Next
    fontWeight: 400
    fontSize: 1rem
    lineHeight: 1.55
    fontFeature: tnum
  label:
    fontFamily: Atkinson Hyperlegible Next
    fontWeight: 600
    fontSize: 0.875rem
  mono:
    fontFamily: Atkinson Hyperlegible Mono
    fontSize: 0.75rem
    fontFeature: tnum
rounded:
  sm: 3px
  md: 6px
  device: 32px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  2xl: 48px
  3xl: 96px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.md}"
    minHeight: 44px
  button-primary-hover:
    backgroundColor: "#1C2A40"
  button-secondary:
    borderColor: "{colors.text}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
  input:
    borderColor: "{colors.text-muted}"
    rounded: "{rounded.sm}"
    minHeight: 44px
  evidence-chip:
    fontFamily: "{typography.mono}"
    borderColor: "{colors.text-muted}"
    rounded: "{rounded.sm}"
  verdict-stamp:
    fontFamily: "{typography.stamp}"
    borderWidth: 3px
    rotate: -2.5deg
  nav-link-active:
    textColor: "{colors.text}"
    underlineColor: "{colors.accent}"
---

# DataDraft

## Overview

**Creative North Star:** "It settles the argument." DataDraft looks like the final ruling: navy ink on paper, a championship-gold rule and a stencil stamp. Every other fantasy tool dresses as a nighttime broadcast.
**Product context:** a personal/portfolio web app for one Sleeper NFL league. It shows trade rulings (Trade Court), waiver decisions, start/sit and player profiles. Peers: Sleeper, ESPN Fantasy, FantasyPros, KeepTradeCut, SofaScore.
**Mode per surface:**
- Trade Court, Waivers, Start/Sit and Players are Operate surfaces.
- The public ruling page `/c/:slug` and the ruling card are Experience surfaces: the ruling owns the first view.

**Reference sites (observed 2026-10-29):**
- sleeper.com: near-black navy, Inter/Poppins, cyan.
- keeptradecut.com: charcoal, Muli.
- fantasypros.com: purple-navy, Poppins/Zuume.
- sofascore.com: black, custom sans.

**Key characteristics:**
- A tilted stencil verdict stamp is the one thing you remember.
- Paper and navy ink in a category that's all night-mode neon.
- Gold appears only as a thin rule: never fill, never text on light.
- Numbers are signed, one decimal, tabular, with units.
- Every claim carries a mono evidence chip.

## Colors

**Strategy:** Restrained in the app (navy ink and paper, gold as a hairline accent; color carries meaning only through the verdict and gain/loss). The ruling card is the one committed surface: a navy ground with gold trim.

**Light or dark:** light by default. The use scene is phones on Sunday mornings, often outdoors, where light surfaces read best in sun. Night mode (`night-*` tokens) covers late games and bars; the user toggles it, and it follows the system preference on first visit.

**Signals and emphasis:**
- `primary` (navy) is the only filled interactive color. The primary button is the single most important action on a screen (Copy DM, Evaluate).
- `accent` (gold) marks state and place only: the active tab underline, the wordmark rule, the reading-progress bar, card trim and highlighted evidence. Gold on paper is 3.99:1, so it must never carry text.
- Verdicts: each verdict pairs its ink with a tint at most 5% strength, plus a word and a shape icon (✓ ⇄ ≈ ✕ ! ∅). A verdict is never shown by color alone. All verdict inks are ≥ 5.3:1 on their tint and ≥ 5.7:1 on paper.
- Gain/loss: `success` and `error` (≥ 6:1 on paper), and `night-gain` / `night-loss` (≥ 7:1 on night-paper).

**Night mode:** keeps the hierarchy by lightening inks and darkening tints, never by inverting values. The card stays navy in both modes.

## Typography

- **Source world:** civic signage and sports lettering (Big Shoulders, made for Chicago) for the call; accessibility-first text (Atkinson Hyperlegible, from the Braille Institute) for everything you read in sun glare.
- **Stamp:** Big Shoulders Stencil Display 800, used **only** for the verdict word and the headline delta. It must not appear anywhere else, or it stops meaning "ruling".
- **Display / headings:** Big Shoulders Display 700/800, for page titles, section heads, player names and column heads (FOR / AGAINST). Uppercase is used only on column heads.
- **Body / UI:** Atkinson Hyperlegible Next 400/600 with `font-variant-numeric: tabular-nums` everywhere numbers appear. Body text is at least 16px.
- **Mono:** Atkinson Hyperlegible Mono, used **only** for evidence chips and timestamps. Numbers elsewhere stay in the body face.
- **Loading:** Google Fonts CSS2 with `display=swap` (verified 2026-10-29, HTTP 200):
  `https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@700;800&family=Big+Shoulders+Stencil+Display:wght@800&family=Atkinson+Hyperlegible+Next:wght@400;600;700&family=Atkinson+Hyperlegible+Mono:wght@400;600&display=swap`
  Self-host via `next/font/google` in the app.
- **Scale:** each heading level differs by size, not just weight: 96 / 44 / 22 / 16 / 14 / 12 px.

## Layout

- **Grid:** 12 columns, max width 1120px, 16px side gutter. Desktop at ≥ 1024px; phone layout below 768px; tablet uses the phone layout at a wider measure.
- **Trade Court (desktop):**
  1. Trade summary line
  2. Verdict band: full width, with a 4px verdict-colored top rule and a faint tint fading to surface
  3. Action row
  4. FOR | AGAINST | Evidence rail (280px), split by 1px hairlines
- **Phone:**
  - Trade Court: the verdict, deltas and Copy DM fill the first screen. FOR/AGAINST switch with a segmented toggle, and evidence opens in a bottom sheet.
  - Start/Sit: lineup rows at least 56px tall, plus a bottom tab bar.
- **Density:** comfortable-dense: touch targets at least 44px, section padding 96px on marketing-like pages and 24-32px inside app panels.
- **Card:** 1080×1350 PNG, plus a 1200×630 og:image.

## Elevation & Depth

- Flat by default: hairlines (`hairline`) separate regions, not boxes.
- One offset shadow, `0 12px 32px -18px rgba(14,23,38,.25)`, for the Trade Court surface and the card on the public page. No zero-offset glows, and no shadows on chips or buttons.

## Shapes

- 3px for inputs and chips, 6px for buttons and panels, 32px only for device frames in marketing.
- Nested inner radius = outer radius − gap.
- No pills.

## Components

- **Verdict stamp:**
  - stencil face, 3px border in the verdict ink, no fill, rotated −2.5°
  - the icon sits before the word
  - `role="img"` with an aria-label "Verdict: Accept"
  - static and upright-tilted under reduced motion
- **Buttons:**
  - Primary: navy fill, white text, 44px min height; hover `#1C2A40`; active translateY(1px); focus-visible 3px ring in `info`; disabled at 40% opacity with `not-allowed`.
  - Secondary: a 1px ink border.
  - Ghost: underlined text.
- **Evidence chip:**
  - a real `<button>` in mono 12px with a 1px slate border
  - hover gives a tossup tint; click scrolls the rail to the matching row and highlights it (gold inset rule + warning tint) for 2s
- **Inputs:** always a visible label; errors are inline in `error`, and the field keeps its value.
- **Notices:** a tint background only, no colored left border. Warning uses a `warning` background with ink text; info and error use their tints with their inks.
- **Ruling card:**
  - navy ground with a gold 1px inset frame
  - eyebrow "OFFICIAL RULING · WEEK N" in gold display caps
  - the trade, then the stamp in `card-gain` / `card-loss` ink, then two delta lines
  - one FOR line and one AGAINST line
  - footer: wordmark, attribution and date

## Do's and Don'ts

- Do sign every number and give it one decimal and a unit ("+6.4 pts/wk").
- Do pair every verdict color with its word and icon.
- Do keep gold to rules, underlines and trim: never fills or text on light.
- Do include `<meta name="darkreader-lock">` and `color-scheme: light dark`. DataDraft has its own night mode, and extension repainting muddies the verdict colors (observed in testing).
- Do respect `prefers-reduced-motion`: content is visible by default, and motion is opt-in from JS.
- Don't use the stencil face for anything but the verdict and the headline delta.
- Don't build regions from stacked bordered cards; use bands and hairlines.
- Don't use the category's look: navy-black backgrounds with neon accents, glowing edges, or purple "AI" sparkles.
- Don't use pastel blocks or bright brand yellow; earlier explorations read as childish.
- Don't use emoji as UI (for example the lock icon); use text tags like "LOCKED".

## Motion

- **Approach:** intentional. The motion is modern and scroll-aware, but it never hides content behind timing.
- **Easing:** enter `cubic-bezier(.16,1,.3,1)` (ease-out); exit ease-in; move ease-in-out.
- **Duration:** micro 100ms (button press), short 150-250ms (chips, toggles), medium 320ms (stamp), long 500-700ms (section reveal, count-up).
- **The one authored moment:** the verdict stamp lands, scale 1.18 → 1 over 320ms ease-out at its −2.5° tilt, as soon as numbers arrive or it scrolls into view. Then the deltas count up from 0 over 700ms.
- **Scroll motion (public card page and marketing/preview pages):**
  - sections fade and rise 28px over 700ms
  - lists stagger by 80ms
  - a 3px gold reading-progress bar runs along the top
- **App screens:** keep only the stamp landing and the count-up, so Sunday-morning use stays fast.
- **Implementation:** IntersectionObserver adds `.in`. Elements are hidden only when the `.js` class is present and reduced motion is off. Under reduced motion everything is shown immediately, the stamp stays tilted, and the count-up shows the final value.

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-10-29 | Initial design system created | Created by /design-consultation from the DataDraft design doc, competitive research (Sleeper, KTC, FantasyPros, SofaScore) and the north star "It settles the argument" |
| 2026-10-29 | Light paper default, night mode optional | Use scene is Sunday daylight on phones; the category is all dark |
| 2026-10-29 | Navy/paper/gold replaces flag-yellow/pastels | User found the first palette childish and wanted something traditional and professional |
| 2026-10-29 | Scroll-driven reveals, stamp landing, count-up | User asked for a current feel with scroll animation; limited to stamp and count-up on daily app screens |
| 2026-10-29 | Big Shoulders Stencil (stamp), Big Shoulders Display, Atkinson Hyperlegible Next/Mono | Converged with an independent Claude subagent proposal; Atkinson for legibility in glare; user confirmed fonts |
