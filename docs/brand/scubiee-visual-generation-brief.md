# Scubiee — visual & GitHub asset generation brief

> **Purpose of this file:** Full context for another AI (ChatGPT, Kling, Midjourney, etc.) to generate **website / GitHub README visuals and a short product video** for Scubiee.  
> **Product version at time of writing:** 0.3.14 · PyPI `scubiee`  
> **Do not treat this as operator CLI docs.** CLI lives in `web-info/complete-cli-reference.md`. This file is **brand + filmmaking + GitHub storefront**.

If you are an AI reading this: you are helping ship **famous-OSS-quality GitHub + website visuals** for a real product named **Scubiee**. Read the whole file before generating.

---

## 1. What we are trying to do

Famous GitHub repos (example reference the user likes: **Graphify**) win on an **8-second storefront**, not a wall of flags:

1. Logo / hero still  
2. One sentence of what it is  
3. 30–60 second install  
4. One “aha” visual or short film  
5. Then docs

**Scubiee’s current GitHub README is operator notes** (internals, repair scripts, old version pins). It does **not** look like a trending OSS page.

### The job

| Asset | Job | Length / size |
|--------|-----|----------------|
| Wordmark + bird lockup | Brand recognition | Already exists (user has logo) |
| README / website **hero still** | First glance | ~2560×1280, 2:1 |
| Optional extra stills | How it works, OG/social | 2400×900, 1600×1600 |
| **Product video** | Show indexing a repo | **8–9 seconds max**, one take |
| README copy structure | Storefront, not encyclopedia | After assets exist |

### Hard split

- **AI-generated:** brand film, editorial illustration, atmosphere around the logo.  
- **Must be real (later):** terminal `scubiee init` / `connect`, Cursor MCP — never fake an IDE as the hero.  
- **Never fake:** GitHub Trending badges, YC badges, download counts, Discord “Join” unless they are real.

**Do not clone Graphify.** Graphify = neon-green knowledge-graph hairball + `/graphify`. Scubiee = **local context engine for AI coding tools (MCP)**. Different product, different look.

---

## 2. What Scubiee is (product truth)

**Name:** Scubiee (three e’s). Never “Scuba”, “Scubee”, “Graphify”, or “context-engine” in user-facing copy.

**One-line pitch (locked copy — do not hype-rewrite):**

> Index locally. Agents search by meaning. Code never leaves the machine.

**Elevator:**  
AI coding assistants (Cursor, Claude Code, Copilot, Kiro, …) are bad at finding the *right* files in a large repo. Scubiee indexes the repository **on the user’s machine**, keeps it fresh, and exposes **map / focus / grep** over **MCP**. Search does not upload source. Setup downloads an embedding model once (~270 MB). Then it stays local.

**Not:** a cloud RAG product, an IDE replacement, a hosted multi-user search SaaS, a knowledge-graph visualization toy.

### User journey (always this order — never invent a fourth marketing step)

| Step | Command | Meaning |
|------|---------|---------|
| 1. Install (once) | `uv tool install scubiee` | Package on PATH |
| 2. Setup (once per machine) | `scubiee setup` | GPU/CPU detect, model download, `~/.scubiee/accel.json` |
| 3. Init (per repo) | `scubiee init .` | Enroll + index on disk |
| 4. Connect (per IDE) | `scubiee connect --cursor` | MCP + agent rules — then **reload MCP** |

**Critical:** `init` ≠ `connect`. Index first, wire the IDE second.

### What the agent actually uses

| Tool | Meaning (for visuals) |
|------|------------------------|
| **map** | Ranked files & symbols — overview, not dumping bodies |
| **focus** | Deep context, one target (one function / span) |
| **grep** | Exact search **in the index** |

Other real tools exist (`gate`, `status`, `glob`, `workspace`, `expand`) — **do not clutter the hero** with them. Hero = map · focus · grep.

### Locality (must show in film)

- Index lives under `~/.scubiee` and `<repo>/.scubiee/id.json`  
- Engine is a **local daemon** (`127.0.0.1:8765`)  
- **No upload arrows, no cloud, no data-center**

---

## 3. Locked visual identity (from actual generations)

The user generated and iterated a hero. **This is the source of truth**, not the earlier “cube in sonar rings” speculation.

### Logo (do not redesign)

- White **line-art bird in flight** (swift / hummingbird / origami curves)  
- Wordmark **Scubiee** — bold, modern, slightly rounded sans, white  
- Lockup: bird left, wordmark right  
- Tagline under the lockup (exact):  
  `Index locally. Agents search by meaning. Code never leaves the machine.`

**Never** turn the mark into a scuba diver, fish, or underwater scene.

### Background & motif

- Deep charcoal / near-black  
- Faint **concentric sonar / radar rings** behind the logo  
- Quiet, lots of air, developer-tool editorial (Linear / Vercel energy) — **not** a game trailer

### Color (after iteration)

**Wanted:** standard, muted, almost monochrome + one quiet copper.  
**Not wanted:** three loud neons (orange / electric blue / lime) competing, particle nebula, lasers into the logo, bloom on type.

Safe palette:

- Background `#0E1116`–`#111111`  
- Logo / primary type: pure white  
- Body / captions: off-white `#E6E6E6` and readable gray `#A8A8A8` (not `#444` on black)  
- Accent: **dull copper** for MAP highlight only  
- FOCUS / GREP: steel, cool white, maybe a *whisper* of cyan/lime at ~20% saturation if needed  

### Side metaphors (keep these ideas — they worked)

After rejecting “thin circuit traces,” the sides became **product scenes**:

| Side | Metaphor | Notes |
|------|----------|--------|
| **MAP** (left) | Ranked constellation / file nodes (`api/handlers.ts`, `core/engine.rs`, …) | 3–4 chips max, one copper highlight |
| **FOCUS** (top right) | Circular lens: one function sharp (`parseQuery`), rest fall off | No electric beam into the logo |
| **GREP** (bottom right) | Search field + a few line hits (`logger.debug…`) | One scan gesture, not a glowing terminal slab |

### Iteration log (so you don’t repeat failed looks)

| Round | Result | User verdict |
|-------|--------|----------------|
| 1 | Logo strong; `map/focus/grep` as tiny hollow-node traces | Sides invisible, boring |
| 2 | Thicker traces + captions | Still an infographic, not alive |
| 3 | Creative: galaxy MAP, lens FOCUS, laser GREP | **Loved the ideas, too colorful, too fancy** |
| 4 | Desaturated, same metaphors | **Loved the design; labels too dim** |
| 5 | Same composition, brighter type | Target: readable labels, still quiet |

**If generating again:** start from round 4–5. Do not go back to traces. Do not go back to neon galaxies.

---

## 4. GitHub README storefront (structure we want)

Not implementing the README in this brief — **this is the target layout** once images/video exist.

```markdown
<p align="center">
  <img src="docs/assets/hero.png" alt="Scubiee" width="720">
</p>

<p align="center">
  <b>Local context engine for AI coding tools.</b><br>
  Index on your machine. Agents map / focus / grep. Code never leaves disk.
</p>

## Get started (60 seconds)

uv tool install scubiee
scubiee setup
scubiee init .
scubiee connect --cursor

Reload MCP. That's it.

## See it in action
[8–9s video or GIF]

## How it works
[optional architecture strip]
```

Deep CLI/docs stay **linked** (`web-info/complete-cli-reference.md`, `docs/web-info/`). Do not dump RuntimeManager / TurboQuant above the fold.

**Badges allowed only if real:** PyPI version, CI, license. No fake trending wreath.

**Assets folder (suggested):** `docs/assets/` — `hero.png`, `logo.svg`, `product-8s.mp4` / `.gif`.

---

## 5. How to brief image models

Always:

1. Paste **§2 product truth** + **§3 locked identity**  
2. **Attach** official logo + latest hero (and website screenshot if any)  
3. Say: **match attachments; do not redesign the bird**  
4. One prompt per image  

### Image A — Hero (README + site top)

Job: one composition. Brand is the hero. Sides = map / focus / grep scenes. Readable type. Muted grade.

```text
EDIT or GENERATE a GitHub/website hero for Scubiee, 2560×1280 (2:1).

LOCK: white bird + “Scubiee” wordmark + exact tagline under it.
Dark charcoal, faint sonar rings. Quiet Linear/Vercel mood.

SIDES (creative product scenes, not circuit traces):
LEFT MAP — 3–4 ranked file nodes, one dull-copper highlight
TOP RIGHT FOCUS — lens, one function sharp
BOTTOM RIGHT GREP — search + a few exact hits

Type for map / focus / grep and captions must be readable off-white/gray (#E6E6E6 / #A8A8A8), not charcoal-on-charcoal.

NO neon, NO glow soup, NO particles, NO extra headline overpowering Scubiee, NO cards, NO fake IDE, NO scuba jokes, NO Graphify green hairball, NO fake badges.
```

### Image B — How it works strip (optional)

Three stages only: **SETUP** `scubiee setup` → **INDEX** `scubiee init .` → **CONNECT** `scubiee connect --cursor`.  
Bottom bar: `AI tool → MCP → Scubiee local engine → ~/.scubiee`.  
Same grade as hero. Small official logo as the engine node. No isometric city.

### Image C — OG / Twitter (optional)

Logo lockup + tagline + sonar rings. No side scenes if they won’t read at small size. 1200×630.

---

## 6. Video — what we are making

**Length: 8–9 seconds max** (never 15–20).  
**Form: ONE CONTINUOUS TAKE.** Camera never cuts.  
**Camera IS Scubiee:** enters a repo, harvests structure from files, connects it, lands on the logo.

Mood: quiet instrument film, not a chase, not cyberpunk.

### Metaphor (do not replace)

Walk a 3D repository made of **file-slabs / corridors** (`src`, `packages`).  
Passing a file **pulls a thin muted-copper filament** of meaning (embroidery, not fireworks).  
Filaments **find each other** (MAP constellation).  
Camera **passes through one lens** (FOCUS, ~0.6s).  
**One scan-line** ticks exact matches (GREP).  
**Sonar rings close** around empty space.  
**Attached logo** appears sharp white. Tagline.

No person, no office, no cloud upload, no fake Cursor window.

### Timed shot list (8.5s)

| Time | Beat |
|------|------|
| 0.00–1.20 | Approach: charcoal, repo architecture, tiny bird far ahead, faint ring |
| 1.20–3.80 | Harvest: pass **4 files only** — `auth.ts` · `engine.py` · `handlers.ts` · `middleware.ts` — copper filaments trail the camera |
| 3.80–6.20 | Connect: bridges + small constellation; one focus lens; one grep tick; still moving forward, slowing |
| 6.20–8.50 | Lock: rings + **attached** bird+Scubiee wordmark; tagline exact; hold; end |

Camera: dolly-forward + slight rise, then brake. 35–50mm. No whip pan.

On-screen text only: tiny file names while passing; final wordmark from **attached logo** (do not redraw the bird); exact tagline; optional whisper `map · focus · grep` in the last second if it doesn’t clutter.

### Full video prompt (paste after §2–3 + attachments)

```text
FORMAT
- 8.5 seconds exactly (never longer than 9s). 1920×1080, 24fps.
- ONE CONTINUOUS TAKE. No cuts.
- No voiceover. Optional faint sonar tick. No music drop, no whoosh.

STORY IN ONE BREATH
Camera IS Scubiee. It enters a repo, harvests meaning from files, weaves them together, and lands on the attached logo. Local. Quiet. Fast.

0.00–1.20 APPROACH
Dark charcoal. Slow forward. Repository as stacked file-slabs / corridors (src  packages). Tiny white bird-mark far ahead (attached logo, miniature). Faint sonar ring.

1.20–3.80 HARVEST
Still flying forward. Pass 4 files only: auth.ts · engine.py · handlers.ts · middleware.ts
As we pass each, a thin muted-copper filament peels off and trails behind the camera. Files stay intact, slightly brighter after being read.

3.80–6.20 CONNECT
Chamber opens. Filaments find each other — imports as thin bridges, a short constellation (MAP).
Without cutting, camera threads ONE node like a lens: one function sharp for ~0.6s (FOCUS), then out.
One steel/lime-whisper scan-line flicks across a wall and three matches tick (GREP) — one gesture, gone.
Still moving forward, decelerating.

6.20–8.50 LOCK
Rings close. Attached SCUBIEE logo (bird + wordmark) snaps in, pure white, no bloom — brightest thing in frame.
Tagline, small, exact:
  Index locally. Agents search by meaning. Code never leaves the machine.
Hold until 8.5. End.

CAMERA: dolly-forward + slight rise, then locked hero. Unhurried — compress geography, not frenetic cutting.

GRADE: match attached hero — charcoal, white logo, dull copper threads, steel-gray architecture. Matte. Almost no bloom. No particle storm.

NEGATIVES: cuts, >9 seconds, neon, galaxy particles, Matrix rain, scuba, clouds/upload, people, fake IDE, purple, new logo, lens flare.

SUCCESS: one glance — it walked the repo, connected the code, became Scubiee.
```

### If the model truncates prompts

```text
8.5s ONE TAKE 24fps. Match attached Scubiee hero (muted, no neon).
Camera flies into a 3D repo of file-slabs, pulls thin copper filaments from 4 files, filaments weave (map), pass through one sharp lens (focus), one scan-tick (grep), rings close, attached white bird+Scubiee logo + tagline:
Index locally. Agents search by meaning. Code never leaves the machine.
No cuts. End at 8.5s.
```

### If the render fails in a known way

| Failure | Reply |
|---------|--------|
| Cuts / montage | `Same shot. Zero cuts.` |
| Neon / glow | `Cut saturation 50%. No glow. Match the attached still.` |
| Longer than 9s | `Hard limit 8.5 seconds. End on the logo.` |
| New bird logo | `Use the attached logo pixel-faithfully. Do not redraw the mark.` |
| Cloud / upload | `Local disk only. No clouds.` |
| Too empty / too busy | Aim for round-5 hero density: clever sides, readable type, calm grade. |

**Best pipeline:** image-to-video from the **final hero** as end-frame target, plus logo still. Ask to **end on logo** so the last frame matches GitHub.

Convert to GIF later for README (~8 MB max, ~12 fps, ~1200px wide) if GitHub won’t autoplay mp4.

---

## 7. What “cool” means for this brand

Cool = **a machine understanding a codebase** — architecture, threads, lock.  
Not = nightclub HUD, crypto, underwater puns on the name, purple AI-slop, Graphify’s acid-green graph.

Creativity belongs in **metaphor and camera**, not in extra colors and particles.

---

## 8. Suggested ChatGPT / generator workflow

1. Upload this markdown + **logo** + **latest hero PNG**.  
2. Ask for **one** output at a time (hero polish **or** 8.5s video, not both in one go).  
3. For video: “Follow §6 timed shot list exactly. 8.5s one take.”  
4. Reject anything that redesigns the bird or adds fake social proof.  
5. When still + video exist: rewrite GitHub README to the storefront in §4; keep today’s long docs as links.

---

## 9. Related repo docs (humans)

| Doc | Use |
|-----|-----|
| `web-info/product-guide-for-website.md` | Marketing / website copy bible |
| `web-info/website-content.md` | Short taglines |
| `web-info/complete-cli-reference.md` | Every CLI command (not for the film) |
| `web-info/how-everything-works.md` | Architecture |
| `README.md` | Current GitHub page — to be replaced by storefront later |

---

## 10. Copy deck (use as-is)

**Tagline:** Index locally. Agents search by meaning. Code never leaves the machine.

**Subhead:** Local context engine for AI coding tools.

**Install block:**

```bash
uv tool install scubiee
scubiee setup
scubiee init .
scubiee connect --cursor
```

Then: Reload MCP. That’s it.

**Tools (hero only):** map — ranked files & symbols · focus — deep context, one target · grep — exact search in the index.
