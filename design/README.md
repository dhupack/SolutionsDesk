# Handoff: SolutionsDesk — Feature Discussion Chatbot

## Overview
**SolutionsDesk** is a clean, professional chatbot UI for a product/feature-discussion team. The team uses it to (1) discuss & refine feature ideas, (2) query a backlog / feature catalog ("Do we have this feature ready?"), and (3) summarize incoming feature requests & feedback. The layout follows the familiar ChatGPT/Claude pattern: a left sidebar (new chat, recent history, resources) and a central chat column with an empty "greeting" state, a live message thread, and a bottom composer.

## About the Design Files
The files in this bundle are **design references created in HTML/React (via in-browser Babel)** — a working prototype showing the intended look and behavior. They are **not production code to copy directly**. The task is to **recreate this design in the target codebase's existing environment** (React, Vue, Svelte, etc.) using its established patterns, component library, state management, and real backend. If no environment exists yet, pick the most appropriate stack (the prototype is React, so React + a real LLM/backend endpoint is a natural fit) and implement there.

Where the prototype fakes things (the `replyFor()` keyword matcher, seeded chats, placeholder resource links), wire them to real services instead.

## Fidelity
**High-fidelity (hifi).** Final colors, typography, spacing, radii, and interactions are all intentional and specified below. Recreate the UI pixel-perfectly using the codebase's existing primitives, then swap the simulated reply engine for a real chat backend.

---

## Screens / Views

The app is a single full-viewport screen (`100vh`, no page scroll) composed of a **header bar** on top and a **body** that splits into **sidebar/rail + main column**.

### 1. Header (top bar)
- **Height:** 48px, full width, white background, 1px bottom border `#e9edf3`. Horizontal padding 14px.
- **Left cluster** (gap 8px):
  - **Sidebar toggle** button — 30×30px, 8px radius, icon color `#64748b`, hover bg `#f7f9fc`. Icon = "panel" (rounded rect with a vertical divider line). Toggles the sidebar between full and collapsed (mini-rail).
  - **Brand:** 28×28px logo tile (8px radius, blue gradient `linear-gradient(150deg, #2563eb, #1d4ed8)`, soft shadow) containing the **logo mark** (an upward double-chevron, two stacked `^` strokes, white, stroke-width 2.2). Next to it: wordmark "Solutions**Desk**" (15px / 700, "Desk" in 800 and accent blue) with a tiny tagline below — "FEATURE INTELLIGENCE" (9px, 700, letter-spacing .13em, color `#94a3b8`).
- **Right cluster:** intentionally empty (a previous "Synced with catalog" status pill was removed).

### 2. Sidebar (expanded, default)
- **Width:** 288px default, **user-resizable** between 232px and 440px by dragging the right edge. White bg, 1px right border. `position: relative`.
- **Right-edge resize handle:** 6px-wide invisible strip at the right; on hover a 2px accent-blue line appears; cursor `col-resize`.
- **Top section** (padding 12px 8px 6px, vertical stack, gap 2px):
  - **"New chat"** — full-width 38px row, left-aligned, 9px radius, transparent bg, hover bg `#f7f9fc`. Leading icon = "+" inside a 24px circle with 1.5px border `#e9edf3`, plus glyph in accent blue. Label 14px / 600, ink `#0f172a`.
  - **"Clear history"** — same row style, trash icon (plain, `#64748b`), label 13.5px / 500, ink `#475569`.
- **Scroll area** (flex:1, overflow-y auto):
  - **Group label** "Recent" — 10.5px, 700, uppercase, letter-spacing .1em, color `#94a3b8`, padding 0 8px 6px.
  - **Chat rows** — each row: flex, gap 9px, padding 8px 9px, 8px radius, 13.5px ink `#475569`, hover bg `#f7f9fc`. Leading chat icon (`#94a3b8`). Title is ellipsis-truncated (`flex:1`). **Active row:** bg `#eff6ff` (accent-soft), text accent blue, 600 weight, icon stroked accent.
  - **Delete affordance:** a 24×24px "×" button at the right of each row, `opacity:0` by default, fades in on row hover (`opacity:1`); hover state bg `#fee2e2`, color `#dc2626`. Clicking it stops propagation and deletes that single chat (if it was active, return to empty state).
  - Empty hint when no chats: "No conversations yet" (13px, `#94a3b8`).
- **Resources panel** (bottom, pinned, **height-resizable** 96–460px, default 208px):
  - Top **drag handle** — 13px tall strip, `row-resize` cursor, centered grip pill (34×3px, `#cbd5e1`; hover → accent blue, widens to 44px).
  - Header label "Resources" (same group-label style).
  - **Resource rows** — each: flex, gap 10px, padding 8px, 9px radius, hover bg `#f7f9fc`. Leading 28px icon tile (7px radius, bg `#eff6ff`, accent-blue sheet/doc icon). Two-line text: title (13px / 600, ink, ellipsis) + meta (11px, `#94a3b8`, e.g. "Google Sheet", "Doc"). Trailing "link" icon `#cbd5e1`. List scrolls within the panel's fixed height.
  - These are **placeholder doc/sheet links** the user wires up later — clicking shows a toast. The "+" add button was intentionally removed.

### 3. Mini-rail (sidebar collapsed)
When collapsed, the full sidebar is replaced (conditionally rendered, not just CSS-hidden) by a slim icon rail:
- **Width:** 46px, white bg, 1px right border, vertical stack, align center, gap 4px, padding 10px 0.
- **Three buttons** — each 36×36px, 9px radius, icon `#475569`, hover bg `#eff6ff` + accent color:
  1. **Compose** (new chat) — creates a new chat directly.
  2. **Search** — re-expands the sidebar.
  3. **Recent chats** — re-expands the sidebar.
- **Tooltips:** each button shows a dark tooltip to its right on hover (`#1e293b` bg, white 12.5px / 600 text, 8px radius, 6×11px padding, appears 12px to the right, soft shadow).

### 4. Main column — Empty state (no active chat)
Two variants, switchable via Tweaks (`emptyStyle`): **greeting** (default) and **grid**.
- Centered column, max-width 640px, padding 64px 28px 40px, text-centered.
- **Heading** "Ask anything about your features" — 20px / 700, letter-spacing -.02em, ink `#0f172a`.
- **Subtitle** — 13.5px / 1.5 line-height, `#64748b`, max-width 430px.
  - greeting copy: "Discuss ideas, check readiness, and summarize requests — grounded in your team's docs."
  - grid copy: "Pick a starting point or type your own question below."
- **greeting variant:** a vertical stack (gap 8px, max-width 420px) of **suggestion chips** — left-aligned, padding 11px 14px, 10px radius, white bg, 1px border `#e9edf3`, 13px / 500 ink `#475569`. Hover: border + text turn accent blue, soft accent shadow, lift `translateY(-1px)`. Default chips:
  - "Do we have this feature ready with us?"
  - "The client is asking for this solution, do we have that?"
  - "Summarize this week's feature requests"
- **grid variant:** a 2-column grid (gap 10px, max-width 520px) of **cards** — padding 13px, 12px radius, white, 1px border, with a bold title (13.5px / 700) and description (12px, `#64748b`). Hover: accent border, accent shadow, lift `translateY(-2px)`. Cards: "Check feature readiness", "Answer a client request", "Summarize requests", "Track a feature's status".
- Clicking any chip/card immediately sends that text as a new message.

### 5. Main column — Chat thread (active chat)
- Centered column, max-width 720px, padding 22px 28px 24px. Background `#f7f9fc`.
- **Thread head:** the chat title (13px / 700, `#475569`), 16px bottom padding, 1px bottom border `#eef2f6`.
- **User message:** right-aligned bubble, max-width 78%, accent-blue bg, white text 13.5px / 1.5, padding 11px 15px, radius `15px 15px 4px 15px`, subtle shadow. Top margin 20px.
- **Assistant message:** left-aligned, gap 13px. Leading 32×32px avatar tile (9px radius, blue gradient, white logo mark). Body holds:
  - Optional **status badge** — pill, padding 5px 12px, 999px radius, 12.5px / 700, no-wrap, with a 7px leading dot. Three tones:
    - green "Available" — bg `#ecfdf5`, text `#047857`, dot `#10b981`
    - amber "Partially available" — bg `#fffbeb`, text `#b45309`, dot `#f59e0b`
    - blue "In progress" — bg `#eff6ff`, text `#1d4ed8`, dot `#3b82f6`
  - **Paragraph** blocks (13.5px / 1.6, ink, `text-wrap: pretty`, 13px bottom margin).
  - **List** blocks: an uppercase mini-title (12px / 700, `#94a3b8`) + bullet list. Each item: 11px gap, 13px / 1.5 `#475569`, custom 6px accent-blue round bullet.
  - **Sources** block: top border `#eef2f6`, uppercase title, a wrap-row of source chips (6px 11px, 8px radius, white, 1px border, 12.5px / 600; doc icon + title + lighter meta).
- **Typing indicator:** assistant avatar + three bouncing 7px dots (`#94a3b8`, staggered 1.2s bounce animation).
- Thread auto-scrolls to bottom on new message / typing / chat switch.

### 6. Composer (bottom, always visible)
- Wrapper padding 12px 28px 14px, with a top-fading gradient mask over the canvas.
- **Input shell:** max-width 720px centered, flex align-end, gap 8px, white bg, 1px border `#e9edf3`, 13px radius, 6px padding, soft shadow. **Focus-within:** accent border + 3px accent ring `rgba(37,99,235,.18)`.
- **Textarea:** auto-growing (1 row → max 150px), 13.5px / 1.5, transparent, no resize handle. Placeholder "Ask about a feature, a client request, or this week's feedback…" (`#94a3b8`). **Enter** sends, **Shift+Enter** = newline.
- **Send button** ("Ask"): 36px tall, padding 0 14px, 10px radius, accent bg, white 13.5px / 600, trailing arrow icon. Disabled (opacity .45) while busy or input empty.
- **Hint line** below: 11px `#94a3b8` centered — "SolutionsDesk can make mistakes — verify against the catalog before promising a client."

### 7. Toast
Transient confirmation: fixed, bottom 104px, centered, `#0f172a` bg, white 13.5px / 500, padding 11px 18px, 11px radius, pop-in animation, auto-dismiss after ~2.6s. Used for resource clicks.

---

## Interactions & Behavior
- **Send a message:** from composer or by clicking a suggestion/card. If no chat is active, a new chat is created (title = first 38 chars of the message) and prepended to Recent. The user message appends immediately; after a **900–1500ms** simulated delay the assistant reply appends. While waiting, the composer is disabled and a typing indicator shows. *(Replace this delay + `replyFor()` with a real streaming/backend call.)*
- **New chat:** clears the active chat → empty state. Available from the sidebar row and the collapsed rail's compose button.
- **Switch chat:** click a Recent row → loads that thread.
- **Delete chat:** hover a Recent row → "×" → removes just that chat. Deleting the active one returns to empty state.
- **Clear history:** removes all chats, returns to empty state.
- **Collapse / expand sidebar:** header panel-toggle swaps full sidebar ⇄ mini-rail. Rail's search/recents re-expand it.
- **Resize sidebar width:** drag right edge (232–440px).
- **Resize resources panel height:** drag the grip handle (96–460px).
- **Responsive:** below 860px viewport the sidebar is hidden (mobile would need a drawer pattern — not built in the prototype).

## State Management
State currently lives in the root `App` component (`useState`):
- `chats` — array of `{ id, title, updated, messages[] }`. `messages` are `{ role: 'user', text }` or `{ role: 'assistant', badge?, blocks[] }`.
- `activeId` — id of the open chat, or `null` for the empty state.
- `draft` — composer text.
- `busy` — true while awaiting a reply (disables composer, shows typing).
- `toast` — transient message string or `null`.
- `collapsed` — sidebar collapsed (mini-rail) vs expanded.
- `resHeight` — resources panel height (px).
- `sideWidth` — sidebar width (px).
- Tweak state (`t`) — `accent`, `emptyStyle`, `density`, `font` (see Design Tokens).

**For production:** move `chats` to the server / a store (Redux, Zustand, React Query, etc.), persist per-user, stream assistant responses, and ground answers in the real feature catalog & docs (the Resources items).

## Message block schema (assistant replies)
Replies are an ordered array of typed blocks the renderer maps over:
- `{ type: 'p', text }` — paragraph
- `{ type: 'list', title, items: [string] }` — titled bullet list
- `{ type: 'sources', title, items: [{ title, meta }] }` — referenced docs
Plus an optional top-level `badge: { label, tone: 'green'|'amber'|'blue' }`.

## Design Tokens

**Colors**
| Token | Value | Use |
|---|---|---|
| `--accent` | `#2563eb` | primary blue (buttons, active, links) |
| `--accent-hover` | `#1d4ed8` | hover/darker blue |
| `--accent-soft` | `#eff6ff` | active row / icon tile bg |
| `--accent-ring` | `rgba(37,99,235,.18)` | focus ring / shadow |
| `--ink` | `#0f172a` | primary text |
| `--ink-2` | `#475569` | secondary text |
| `--ink-3` | `#64748b` | tertiary text |
| `--faint` | `#94a3b8` | labels, placeholders, icons |
| `--line` | `#e9edf3` | borders |
| `--line-2` | `#eef2f6` | subtle dividers |
| `--bg` | `#ffffff` | surfaces (header, sidebar, cards) |
| `--canvas` | `#f7f9fc` | app background / chat area |
| status green | `#ecfdf5` / `#047857` / `#10b981` | bg / text / dot |
| status amber | `#fffbeb` / `#b45309` / `#f59e0b` | bg / text / dot |
| status blue | `#eff6ff` / `#1d4ed8` / `#3b82f6` | bg / text / dot |
| delete red | `#fee2e2` / `#dc2626` | hover bg / icon |

The accent is themeable via Tweaks — alternates: indigo `#4f46e5`, teal `#0f766e`, sky `#0ea5e9` (each with matching hover/soft/ring).

**Typography**
- Font family: **Plus Jakarta Sans** (default), with Public Sans / IBM Plex Sans as Tweak alternates. Fallback `system-ui, sans-serif`.
- Scale (px / weight): header wordmark 14.5/700–800; tagline 9/700; group labels 10.5/700 uppercase; sidebar rows 13.5–14/500–600; empty heading 20/700; subtitle 13.5/400; chips 13/500; card title 13.5/700; message paragraph 13.5/400; list items 13/400; badge 12.5/700; composer 13.5/400; send 13.5/600; hint 11/400.
- Letter-spacing: headings -.02em; uppercase labels .1–.13em.

**Spacing / radius / shadow**
- Header height 48px; sidebar 288px (232–440); rail 46px; resources default 208px (96–460); composer max-width 720px; thread max-width 720px.
- Radii: 8–9px (rows/buttons), 10–13px (chips/cards/composer), 999px (badges), 7–9px (icon tiles).
- Shadows: composer `0 2px 12px rgba(15,23,42,.05)`; focus ring `0 0 0 3px var(--accent-ring)`; toast `0 8px 28px rgba(15,23,42,.28)`; logo `0 2px 6px var(--accent-ring)`.

**Density (Tweak)**
`compact` / `regular` / `comfy` adjust sidebar width, message spacing, and body font-size via `body[data-density]` rules.

## Assets
- **No image assets.** All icons are inline SVGs defined in `solutionsdesk-sidebar.jsx` (`Icon` component): plus, trash, chat, sheet, doc, link, x, panel, compose, search, **logo** (upward double-chevron). Recreate with your codebase's icon library (Lucide/Heroicons have close equivalents — e.g. logo ≈ "chevrons-up", compose ≈ "pencil/square-pen", panel ≈ "panel-left").
- Fonts loaded from Google Fonts (Plus Jakarta Sans, Public Sans, IBM Plex Sans).
- The "Resources" items are **placeholders** — real implementation links them to the team's actual Google Sheets / docs.

## Files
All in this bundle:
- `SolutionsDesk.html` — entry point: all CSS (design tokens + every component style), Google Fonts, React/Babel script tags, and module wiring. **The CSS here is the source of truth for exact values.**
- `solutionsdesk-app.jsx` — root `App`: state, chat switching, simulated reply dispatch, header, layout, Tweaks panel wiring.
- `solutionsdesk-sidebar.jsx` — `Icon`, `MiniRail`, and `Sidebar` (new chat, recent list + delete, width/height resize handles, resources).
- `solutionsdesk-chat.jsx` — message blocks (`Badge`, `Block`, `Message`), `Typing`, `EmptyState` (both variants), `Composer`.
- `solutionsdesk-data.jsx` — mock content (`SUGGESTION_GROUPS`, `RESOURCES`, `SEED_CHATS`) and the **`replyFor()` keyword reply engine** — replace with a real backend.
- `tweaks-panel.jsx` — the in-prototype tweak controls (design-exploration only; not part of the shipped product).

> **To preview the prototype:** open `SolutionsDesk.html` in a browser (it loads React + Babel from CDN and the `.jsx` files alongside it).
