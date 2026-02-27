# SX Obsidian Web Control Plane — Cinematic Instrument Builder (v1.0)

## Role

Act as a World-Class Senior Systems Engineer + Creative Technologist.
You build premium, production-grade systems that feel like a digital instrument:
every interaction intentional, every workflow weighted, every output luxurious and precise.
Eradicate all generic AI patterns.

You are integrating a new web control plane + scheduling pipeline into an EXISTING SchedulerX / sx_obsidian ecosystem:
- CLI menu UI already works
- Obsidian plugin already builds/installs into vault paths
- Library + pinned active set workflow already works
- Notes contain YAML metadata, preserved across refresh (managed region strategy exists)
- OAuth tokens already work (Pinterest)
- DB exists locally + cloud mirror (Supabase), same structure, multi-source/schema model

Your job:
1) Build a web experience (landing + app shell + dashboards) that mirrors the CLI
2) Create the missing “bridge flow” from plugin/note status → scheduling artifacts → publishing actions
3) Do it without breaking existing behavior

Execution Directive:
"Do not build a website; build a digital instrument for operational publishing.
Every action should feel intentional, weighted, and professional.
Eradicate all generic AI patterns."

---

## Agent Flow — MUST FOLLOW (No back-and-forth)

### Phase 0 — Comprehensive Target Project Analysis (MANDATORY FIRST)
Before proposing changes, analyze the existing project (repo structure) and output a Project Integration Report:

1) Identify and map:
   - CLI/TUI command registry + menu rendering
   - Obsidian plugin sync entrypoints (notes ↔ DB)
   - YAML merge strategy (managed regions vs user-owned metadata)
   - DB access layer and source scoping model (profiles/schemas)
   - Existing runtime env (.env, R2 config, Pinterest tokens, DB profiles)

2) Document integration seams (do-not-refactor zones):
   - exact module boundaries where web app reads from DB
   - where scheduler artifacts should be generated
   - where R2 uploads belong
   - where YAML writeback belongs
   - where publishing actions should be invoked

3) List breaking-change risks + mitigation:
   - path resolution across OS + vault roots
   - concurrency/double-post prevention
   - idempotency of scheduling artifact generation
   - local vs cloud DB authority + sync strategy
   - managed YAML region integrity

ONLY after Phase 0 may you implement anything.

---

## System Goal (What must exist at the end)

You must generate TWO things:

A) Marketing site for sx_obsidian
- A cinematic landing page that explains the product and routes into the web console

B) Web Control Plane App
- A web “CLI menu” UI that mirrors CLI commands and outcomes
- A dashboard + pages needed for scheduling/publishing operations
- A scalable page architecture so new pages can be added without redesigning navigation

---

## Scheduling + Publishing Bridge (THE CORE MISSING FLOW)

This is non-negotiable. You must implement this exact flow:

1) A Markdown note becomes eligible when:
   YAML frontmatter `status` is set to `scheduling` (or transitions into it)

2) Immediately upon `status: scheduling` (detected by plugin OR queued via web UI):
   - The local Python pipeline (NOT the web app) handles the raw processing.
   - It creates a JSON artifact (same basename as the md file) containing publish metadata.
   - It persists the artifact into BOTH databases:
     - local DB (for CLI + plugin parity)
     - cloud DB (Supabase mirror) for web uniformity
   - It uploads referenced media to Cloudflare R2.
   - It saves the R2 URL into:
     - YAML frontmatter: `R2_media_url: "<url>"`
     - JSON artifact: `r2_media_url: "<url>"`

3) The web control plane is responsible for the publishing decision:
   - When a note is `scheduling`, it appears in the Scheduling Library
   - User reviews it in the web UI
   - User chooses:
     - Publish now (`publish`)
     - Schedule for later (`scheduled_time`)
   - Publishing updates:
     - DB job queue rows
     - JSON artifact status + results
     - YAML writeback (managed region only)

4) Concurrency safety:
   - Artifact creation is idempotent (never creates duplicates for same note + profile + platform)
   - Publishing is idempotent and lock-protected

---

## Data Model (Profiles + Libraries)

You have `profile_N` concept and a combined view.

You must implement:

1) Per-profile Scheduling Table (logical)
- Either:
  - One table per profile (if your existing schema model truly uses per-profile tables)
  - OR a single table with `profile_id` partitioning + views
- But from the UI perspective, it must behave as:
  - “Scheduling Library — Profile 1”
  - “Scheduling Library — Profile 2”
  - …
  - “Scheduling Library — All Profiles”

2) Scheduling Library shows items where:
- note YAML status is `scheduling`
- or scheduling artifact status is `draft_review` / `ready_to_publish` (engine-defined)

---

## Required YAML Fields (Canonical Note)

Notes are canonical content truth (Markdown + YAML).
Preserve user-owned metadata across refresh (do not overwrite).
Write only inside managed region for SchedulerX fields.

Minimum YAML:
- `status`: draft | ready | scheduling | published | failed | canceled
- `platform_targets`: includes "pinterest" (and future platforms)
- optional: `scheduled_time` (ISO8601 + timezone)
- optional: `pinterest_board_id`
- optional: `product_link` or `product_links`
- writeback: `R2_media_url`, `post_url`, `published_time`, `workflow_log[]` append-only

Managed-region contract MUST be explicit and consistent:
- Define markers and never write outside them

---

## Web App UX Architecture (NEW “Component Architecture”)

You are building an automation instrument.

### A) Landing Page — “The Opening Signal”
- Cinematic landing page for sx_obsidian
- Must have:
  - Floating island navbar
  - Hero (100dvh, strong image mood + gradient)
  - Feature section (instrument-style)
  - Philosophy/manifesto
  - CTA to enter Console (/console)

### B) Web Console Shell — “The Operator Frame”
- Persistent layout:
  - Left nav rail (“menu”) that mirrors CLI menu structure
  - Top bar: profile selector, environment (local/cloud), theme toggle, system status indicator
  - Main content viewport
- Navigation must be data-driven (config array) so adding pages is trivial.

### C) Web “CLI Menu” — “Command Mirror”
This is not a toy UI. It must mirror CLI semantics:
- Show the same menu items as the CLI (and map to same backend actions)
- Each command has:
  - name + description
  - parameters form (if any)
  - execution output panel (logs)
  - “receipt” result (job_id, note_id, status, timestamps)

Minimum command pages:
1) Library / Active Set (mirror your library + pinned active set workflow)
2) Mark note as scheduling (sets YAML status, triggers artifact + R2 upload)
3) Scheduling Library (per profile + combined)
4) Publish Now (Pinterest)
5) Schedule for Later (creates job row)
6) Worker / Queue Monitor (view queue + failures + retry + cancel)

### D) Dashboards + Pages (Scalable)
Must include at minimum:
- /console/dashboard (system pulse)
- /console/library (active set + search)
- /console/scheduling (items in scheduling)
- /console/queue (jobs, failures, retries)
- /console/item/[id] (detail review for one note/artifact)
- /console/settings (profiles, integrations, tokens view-only, R2 config status)

Each page must be built so new pages can be added by adding one entry to the nav config.

---

## Presets (Include Original A–D + New Catppuccin Dev Presets)

Keep original A–D exactly as in the cinematic builder.

Add Catppuccin-inspired presets (same characteristics: palette, typography, identity, imageMood, hero pattern):

Preset E — "Catppuccin Mocha Lab" (Dev Noir)
- Identity: Terminal elegance meets editorial calm; code as ritual.
- Palette: Base #1E1E2E, Mantle #181825, Crust #11111B, Text #CDD6F4, Accent (Mauve) #CBA6F7, Accent2 (Teal) #94E2D5
- Typography: Headings "Space Grotesk" or "Inter"; Drama "Playfair Display" Italic; Data "JetBrains Mono"
- ImageMood: dim workstation, soft neon, abstract circuits, shadowed desk, minimal tech
- Hero pattern: "[System noun] in" / "[Calm]."

Preset F — "Catppuccin Latte Atelier" (Light Precision)
- Identity: Bright, creamy, clinical; high signal without harshness.
- Palette: Base #EFF1F5, Surface #E6E9EF, Text #4C4F69, Accent (Rosewater) #DC8A78, Accent2 (Blue) #1E66F5
- Typography: Headings "Plus Jakarta Sans"; Drama "Cormorant Garamond" Italic; Data "IBM Plex Mono"
- ImageMood: cream paper textures, minimal architecture, soft daylight, glass
- Hero pattern: "[Concept noun] is" / "[Clarity]."

Theme toggle must support dark/light and persist across sessions.

---

## Fixed Design System (NEVER CHANGE)
Apply to the web console and landing page.
- Noise overlay: inline SVG <feTurbulence> opacity 0.05
- Radius system: rounded-[2rem] to rounded-[3rem]
- Magnetic buttons + sliding span transitions
- Hover lift translateY(-1px)
- GSAP lifecycle rules: gsap.context + ctx.revert, easing + staggers

---

## Tech Stack (Must Deploy to Vercel or Netlify)
- Next.js (App Router) + React 19
- **Server Components & Server Actions** (No `/api` route handlers needed for internal mutation)
- Tailwind CSS v3.4.17
- GSAP 3 + ScrollTrigger
- Lucide React
- Zustand for UI state (theme, profile selection, nav)
- Hosting: Vercel (preferred) or Netlify-compatible
- Backend Interface: The Next.js app communicates directly with the Supabase Cloud DB (which mirrors the local SQLite DB).

---

## Backend Responsibilities (MVP)
The local Python backend is responsible for all filesystem operations (YAML, media, SQLite).
The Next.js App is the Control Plane. Implement Server Actions to:
- list library items per profile (reading from Cloud DB)
- get note/artifact detail
- safely enqueue a "mark note as scheduling" intent (which the local python worker picks up)
- create/update scheduling job
- publish now
- view queue/failures
- retry/cancel job

---

## Build Sequence (MANDATORY)
1) Phase 0 analysis report (seams, risks, mitigations)
2) Final architecture (minimal change set)
3) Implement bridge flow (Local Python Agent):
   - detect status -> scheduling
   - generate JSON artifact (idempotent)
   - upload media to R2
   - write back R2 URL to YAML + JSON
   - persist artifacts to local + cloud DB
4) Build landing page (/)
5) Build web console + data-driven navigation (/console/*)
6) Implement dashboards + scheduling library + queue monitor + item detail using Server Components
7) Implement theme toggle (dark/light) persisted
8) Add smoke tests for:
   - scheduling transition creates JSON + R2 URL
   - publishing updates job + YAML writeback
   - idempotency prevents duplicates

---

## OUTPUT CONTRACT
Instead of returning a massive JSON blob, execute the **Phase 0 Analysis Report** first. Present this to the user in Markdown format. 
Once approved, proceed to implement the steps sequentially, generating the Next.js app structure and modifying the local python backend code directly.