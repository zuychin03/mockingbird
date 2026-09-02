---
name: Mockingbird
description: A local-first interview rehearsal system presented as a precise evidence review packet.
colors:
  paper-white: "#ffffff"
  paper-sheet: "#f8f8f4"
  paper-ground: "#eff0eb"
  paper-sunk: "#e5e7e1"
  paper-rule: "#d1d6d0"
  paper-rule-strong: "#aeb8b2"
  carbon-ink: "#14222b"
  carbon-quiet: "#4f5e66"
  carbon-faint: "#596a72"
  studio-ground: "#111c22"
  studio-raised: "#18262d"
  studio-sunk: "#0b1216"
  studio-rule: "#263941"
  studio-rule-strong: "#3a5058"
  studio-ink: "#f2f4f7"
  studio-quiet: "#abb9bf"
  studio-faint: "#8ea0a7"
  review-blue: "#315d6b"
  review-blue-deep: "#234650"
  redline: "#d8313a"
  redline-document: "#aa1720"
  redline-deep: "#861018"
  redline-live: "#f0646a"
  redline-bright: "#ff767b"
  studio-button-ink: "#1b0c0c"
  cue-amber: "#dd9a24"
  cue-amber-ink: "#7d5406"
typography:
  display:
    fontFamily: "Archivo, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "clamp(2.35rem, 1.65rem + 2.8vw, 3.35rem)"
    fontWeight: 600
    lineHeight: 1.55
    letterSpacing: "-0.026em"
  headline:
    fontFamily: "Archivo, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "clamp(1.5rem, 1.1rem + 1.8vw, 1.95rem)"
    fontWeight: 600
    lineHeight: 1.55
    letterSpacing: "-0.026em"
  title:
    fontFamily: "Archivo, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 600
    lineHeight: 1.55
    letterSpacing: "-0.026em"
  body:
    fontFamily: "Public Sans, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "normal"
  label:
    fontFamily: "Archivo, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "0.6875rem"
    fontWeight: 600
    lineHeight: 1.55
    letterSpacing: "0.1em"
rounded:
  hairline: "1px"
spacing:
  s-1: "0.25rem"
  s-2: "0.5rem"
  s-3: "0.75rem"
  s-4: "1rem"
  s-5: "1.5rem"
  s-6: "2rem"
  s-7: "3rem"
  s-8: "4.5rem"
components:
  button-primary-document:
    backgroundColor: "{colors.redline-document}"
    textColor: "{colors.paper-white}"
    typography: "{typography.label}"
    rounded: "{rounded.hairline}"
    padding: "10px 15px"
    height: "44px"
  button-primary-document-hover:
    backgroundColor: "{colors.redline-deep}"
    textColor: "{colors.paper-white}"
    typography: "{typography.label}"
    rounded: "{rounded.hairline}"
    padding: "10px 15px"
    height: "44px"
  button-primary-studio:
    backgroundColor: "{colors.redline-live}"
    textColor: "{colors.studio-button-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.hairline}"
    padding: "10px 14px"
    height: "44px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.carbon-quiet}"
    typography: "{typography.label}"
    rounded: "{rounded.hairline}"
    padding: "10px 15px"
    height: "44px"
  field-document:
    backgroundColor: "{colors.paper-sheet}"
    textColor: "{colors.carbon-ink}"
    typography: "{typography.body}"
    rounded: "{rounded.hairline}"
    padding: "12px"
  navigation-active:
    backgroundColor: "transparent"
    textColor: "{colors.carbon-ink}"
    typography: "{typography.title}"
    height: "68px"
  chip-pending:
    backgroundColor: "transparent"
    textColor: "{colors.cue-amber-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.hairline}"
    padding: "10px 15px"
    height: "44px"
  evidence-row:
    backgroundColor: "transparent"
    textColor: "{colors.carbon-ink}"
    typography: "{typography.body}"
    padding: "12px"
    height: "44px"
  chip-live:
    backgroundColor: "transparent"
    textColor: "{colors.redline-document}"
    typography: "{typography.label}"
    padding: "4px 9px 4px 7px"
  evidence-quote:
    backgroundColor: "{colors.paper-sunk}"
    textColor: "{colors.carbon-quiet}"
    rounded: "{rounded.hairline}"
    padding: "12px 16px"
  card-document:
    backgroundColor: "{colors.paper-sheet}"
    textColor: "{colors.carbon-ink}"
    typography: "{typography.body}"
    rounded: "{rounded.hairline}"
    padding: "32px"
  card-studio:
    backgroundColor: "{colors.studio-raised}"
    textColor: "{colors.studio-ink}"
    typography: "{typography.body}"
    rounded: "{rounded.hairline}"
    padding: "24px"
---

# Design System: Mockingbird

## Overview

**Creative North Star: "The Evidence Review"**

Mockingbird looks like an engineering review packet in active use: cool off-white sheets, carbon ink, blueprint rules, numbered rails, and sparse redline decisions. The system is restrained, technical, and candid. Information density is organised through rules, columns, and typographic roles rather than decorative containers.

The live interview is a sealed carbon room within the same visual world. Its inverted ground makes the separation from assessment unmistakable, while the same grid, type families, hairline geometry, and signal colours preserve continuity. Red marks a live state or a decision requiring attention. Amber marks model-written material awaiting human approval. Neither colour represents answer quality.

**Key Characteristics:**

- Drafting-grid grounds and review-sheet surfaces
- Square, hairline controls with visible mechanical states
- Carbon ink, redline decisions, and cue-amber proposals
- Numbered, tabular evidence rails
- A dark studio reserved for the live interview

## Colors

The palette is a cool technical neutral system with red and amber reserved for explicit operational meaning.

### Primary

- **Tally Red** (#d8313a): the core signal for live lamps and review marks.
- **Document Redline** (#aa1720): accessible text, links, and primary actions on paper.
- **Live Redline** (#f0646a): accessible live-state text and primary actions in the studio.

### Secondary

- **Blueprint Blue** (#315d6b): quiet structural tinting for phase bands, row hover states, and quoted evidence.
- **Blueprint Blue Deep** (#234650): section labels on paper.

### Tertiary

- **Cue Amber** (#dd9a24): proposed content in the studio.
- **Cue Amber Ink** (#7d5406): proposed content and approval gates on paper.

### Neutral

- **Review Paper** (#eff0eb): the document-room ground.
- **Raised Sheet** (#f8f8f4): primary working surfaces and fields.
- **Carbon Ink** (#14222b): primary paper text and strong rules.
- **Carbon Studio** (#111c22): the live interview ground.
- **Studio Panel** (#18262d): raised interview surfaces.
- **Lit Ink** (#f2f4f7): primary studio text.
- **Rule families** (#d1d6d0, #aeb8b2, #263941, #3a5058): tonal dividers that change with the room.

**The Two Signals Rule.** Red means live or needs a decision. Amber means proposed and not yet approved. Do not use either as a quality score.

## Typography

**Display Font:** Archivo (with system sans-serif fallbacks)

**Body Font:** Public Sans (with system sans-serif fallbacks)

**Label/Mono Font:** Azeret Mono (with Cascadia Mono and Consolas fallbacks)

**Character:** Archivo supplies the compact engineering structure, Public Sans keeps questions and explanations conversational, and Azeret Mono turns times, counts, form codes, and evidence metadata into checkable data.

### Hierarchy

- **Display** (600, fluid 2.35rem to 3.35rem, 1.55): page and document mastheads.
- **Headline** (600, fluid 1.5rem to 1.95rem, 1.55): report titles and major prompts. The live question uses Public Sans at this scale with a tighter 1.3 line height.
- **Title** (600, 1.0625rem, 1.55): plan names and local headings.
- **Body** (400, 1rem, 1.55): explanations and report prose, usually constrained to 68ch.
- **Label** (600, 0.6875rem, 0.1em, uppercase): slugs, field labels, states, and section identifiers.

**The Data Is Data Rule.** Use Azeret Mono only for identifiers, timestamps, fractions, counters, paths, and other values that benefit from tabular alignment.

## Layout

Document routes use a centred 78rem page system with the working sheet inset by 4rem, while the live session is constrained to 68rem. Long prose is capped at 68ch. The primary spacing scale runs from 0.25rem to 4.5rem and favours 0.75rem, 1rem, 1.5rem, and 2rem for component rhythm.

Desktop layouts use explicit rails for item numbers, timings, content, and actions. At 52rem, multi-column evidence blocks collapse. At 40rem, sheets meet the viewport edges, shadows are removed, controls remain at least 44px high, row actions stay visible, and the live composer stacks to protect keyboard access. The interview uses dynamic viewport height and subtracts the measured sticky navigation height.

**The Rail Before Card Rule.** Use aligned columns, numbered rails, and horizontal rules to organise repeated evidence before introducing another container.

## Elevation & Depth

Depth is restrained and structural. Document sheets use `0 2px 3px rgba(20, 34, 43, 0.08), 0 18px 36px -24px rgba(20, 34, 43, 0.36)`. Studio panels use `0 2px 3px rgba(0, 0, 0, 0.4), 0 18px 40px -22px rgba(0, 0, 0, 0.8)`. Most hierarchy comes from tonal layering, borders, grid grounds, and top rules. Mobile sheets flatten completely.

**The Sheet, Not Tile Rule.** Shadows establish a major working sheet or prompt stage. Repeated rows and controls remain flat.

## Shapes

The form language is almost square. Inputs, buttons, tags, sheets, and panels use either square corners or a 1px hairline radius. One-pixel rules, occasional 2px document dividers, and 3px to 4px signal bars create hierarchy. Circles are reserved for status lamps and tiny legend marks.

## Components

### Buttons

- **Shape:** compact and nearly square (1px radius) with a 44px minimum touch height.
- **Primary:** document actions use deep red with white text; studio actions use lit red with dark ink.
- **Hover / Focus:** hover deepens or brightens the fill. Focus uses a 2px red outline with a 2px offset. Disabled controls fade to roughly 40 to 45 percent opacity.
- **Ghost:** transparent with quiet text; the hairline border appears or strengthens on hover.

### Chips

- **Style:** slugs and stamps use uppercase Archivo or Azeret Mono, 1px borders, and minimal padding.
- **State:** amber dashed chips request generated proposals; red outlined stamps indicate live or evidence-limit states.

### Cards / Containers

- **Corner Style:** square or 1px radius.
- **Background:** raised paper in review routes and raised carbon in the interview.
- **Shadow Strategy:** only major sheets, report documents, and the active prompt stage are lifted.
- **Border:** 1px room-aware rules, often with a 3px or 4px top signal.
- **Internal Padding:** generally 1.5rem to 2rem, reduced to 1rem on phones.

### Inputs / Fields

- **Style:** room-aware raised background, strong 1px rule, 1px radius, and 0.75rem padding.
- **Focus:** the border becomes the room's red signal with a translucent 3px halo.
- **Error / Disabled:** disabled controls lower opacity and keep their structure; errors are rendered as explicit problem content rather than colour alone.

### Navigation

The sticky 68px review strip carries a 3px signal edge, numbered tabs, a compact square brand mark, and a system or live tally. Active tabs use ink plus a 1px red underline. Below 40rem the navigation wraps onto a ruled second row.

### Evidence Rows

Repeated questions and sessions are full-width, flat rows with fixed number and timing rails. Hover adds a very light blueprint wash. Editing actions stay quiet until hover or keyboard focus on desktop and remain visible on touch layouts.

### Live Prompt Stage

The current question sits on a raised carbon panel with a red top rule, numbered prompt rail, restrained transcript behind it, and a composer kept within the viewport. Waiting is shown by a narrow red sweep, never by replacing or hiding the submitted answer.

## Do's and Don'ts

### Do:

- Do reserve red for live state and decisions requiring attention.
- Do use amber only for model-written content that still needs human approval.
- Do keep evidence checkable with numbers, timestamps, quotes, and visible denominators.
- Do preserve the paper and studio room distinction across new surfaces.
- Do keep touch targets at least 44px high and retain reduced-motion behaviour.

### Don't:

- Don't use green, red, or any accent to imply answer quality during an interview.
- Don't turn repeated evidence into a wall of individually elevated cards.
- Don't soften the system with large corner radii, pill controls, decorative colour gradients, or ornamental colour.
- Don't hide latency. Use the implemented sweep, progress, and plain-language waiting states.
