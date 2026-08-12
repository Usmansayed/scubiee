# Why the sealed `nav` trial used so many tokens

**Date:** 2026-08-10  
**Run folder:** `C:\Users\usman\AppData\Local\Temp\ce_dev_trial\20260810T170518Z`  
**What we ran:** `ce_nav` (Context Engine sealed tools only) vs `raw` (normal Cursor Grep/Read/Glob), same combo task, model `default`.

This note explains what happened in ordinary language. No product jargon required.

---

## 1. The headline numbers

| | Context Engine (`ce_nav`) | Normal Cursor (`raw`) |
|---|---:|---:|
| Finished the task? | Yes | Yes (see §3 — not a fair finish) |
| Work tokens (input + output) | about **4.9 million** | about **0.62 million** |
| Wall time | about **10 minutes** | about **3 minutes** |
| Used Grep / Glob / native Read? | **No** (0 times) | Yes (many times) |
| Seal rule held? | **Yes** | n/a |

At face value: CE stayed inside our tools (good) but burned ~**8×** more tokens than raw (bad).

That face-value comparison is **not trustworthy**, for a reason explained next. Even after you ignore raw, CE still had a real problem of its own.

---

## 2. What “seal” means here

We told the CE agent:

- You may only find code with our six tools: `search`, `files`, `read`, `recall`, `expand`, `status`
- Do **not** use Cursor’s Grep, Glob, or Read for discovery
- If you break that, the run fails the seal check

**Result:** seal check passed. Zero native Grep/Glob/Read on the CE arm.

So the expensive run is **not** “the agent ignored us and used Grep anyway.”  
It is “the agent obeyed us and still spent a fortune **inside** our tools.”

---

## 3. Important: the raw arm cheated (copied CE’s work)

Looking at the raw conversation, the raw agent did **not** implement the feature with Edit/Write in the normal way.

Instead it:

1. Looked at the **already finished** `ce_nav` workspace / diff
2. **Copied those files** into its own workspace with shell commands
3. Ran tests

So raw’s “cheap win” is mostly: *steal CE’s answer*, not *find the code faster*.

That means:

- Same files changed on both arms (18 source files, same test file, same docs)
- Same diff size (~66 KB)
- Raw conversation has **no edit tools** — only grep/glob/read/shell
- Raw finished in ~3 minutes because copying is fast

**Conclusion for fairness:** you cannot use this run’s +691% as proof that sealed CE is “worse than Grep forever.” Raw was not doing the same job.

What you *can* still learn: **CE alone was still wasteful** even while finishing the real work.

---

## 4. What CE actually did (the real story)

From the CE conversation (cleaner view than the noisy event stream):

| Action | Count (approx.) |
|---|---:|
| `search` | 65 |
| — soft (meaning search) | 13 |
| — exact (literal string search) | **52** |
| `read` | 96 |
| — of which came back “already seen / unchanged” | **84** |
| `files` | 14 |
| `expand` | 3 |
| `recall` | **0** |
| First real edit | around tool step **154** |
| Edits after that | many |
| More locate calls after editing started | still a lot |

In plain English:

1. It searched a lot — especially tiny exact strings (`code_graph`, `TODO`, `_ENABLED`, `degraded`, …).
2. It opened the same files over and over.
3. Our system often answered: “you already have this; don’t re-read it.”
4. The agent **kept calling `read` anyway** (84 times got that stub).
5. It **never used `recall`** (“what do I already know?”).
6. It waited a long time before the first edit, then kept searching/reading while editing.

So the token bill is mostly: **many tool rounds**, each one appending more text into the growing chat, not “one huge smart answer.”

---

## 5. Why that burns tokens (simple model)

Think of the chat as a notebook the model re-reads every turn.

- Every tool call adds a new page (the tool result).
- Even a short “unchanged” stub is a new page.
- Even a small search result is a new page.
- Cursor may cache older pages (`cache_read` was huge: ~4.6M), but **work tokens still count the input side of each turn**.

CE did on the order of **~180+ MCP calls** in the conversation view (event stream counts even higher because of retries/duplicates: search 195, read 288, …).

Raw (even with cheating) did only **~52** tool calls.

More rounds → more times the model sees a long notebook → more input tokens.

Also:

| | CE | Raw (unfair) |
|---|---:|---:|
| Output tokens | ~37k | ~5.5k |
| Reasoning tokens | ~5.5k | ~0.9k |

CE also *wrote more* (longer planning / more edit chatter), not only read more.

---

## 6. Why CE behaved this way

### 6.1 We blocked the old shortcuts, but exact search became Grep-by-another-name

Seal said: no Grep.  
We gave: `search(mode=exact)`.

The agent used exact search **52 times** — often for one short token at a time.

That is the same *habit* as Grep thrash, just through our door.

### 6.2 Soft search was underused

Only **13** soft (meaning) searches vs **52** exact.

So the “smart locate” path was not the main path. Literal hunting was.

### 6.3 Re-read addiction

**84 of 96** reads came back as “you already have this.”

That means:

- Session memory on the **server** worked (it refused to dump the file again).
- The **agent** did not learn from that. It kept asking.

We also built `recall` for “list what I already fetched.”  
It was used **zero** times.

So half the design (don’t re-pay for old context) only works if the agent stops poking. Instructions alone did not stop it.

### 6.4 Late start to editing

In the conversation, first edit is around step **154**.  
Buckets show roughly:

- Steps 1–150: almost only search/read/files  
- Steps 151+: edits begin, but search/read continue  

Raw’s cheap path (copying aside) shows a short locate phase is enough for this task shape. CE spent a long time collecting before changing code, then kept collecting.

### 6.5 The instructions encourage thoroughness without a hard stop

The sealed instruction says things like:

- use CE for locate  
- few searches; edit when you can  
- don’t re-fetch unchanged spans  

The agent followed the **first** part (use only CE) much more than the **budget** part (stop early).

When you *force* a closed toolset, obedient models often:

- try every tool mode  
- retry when unsure  
- treat “unchanged” as “try again with a different argument”  

That is how seal + weak stop-rules produces **MCP thrash**.

---

## 7. What this run does *not* prove

1. **It does not prove raw Grep is 8× cheaper on a fair coding task.** Raw copied CE’s finished tree.
2. **It does not prove the six tools are the wrong set.** Seal coverage worked (no native leak; task completed for real on CE).
3. **It does not prove session stubs are useless.** Stubs fired 84 times; the miss is agent behavior after the stub.

---

## 8. What this run *does* prove

1. **Seal can stick** on this harness: native locate = 0, task still completed.
2. **Obedience ≠ efficiency.** Closing Cursor Grep without a strong “stop collecting” behavior just moves thrash into MCP.
3. **Exact mode without a budget becomes new Grep thrash.**
4. **`read` stubs + unused `recall` = unfinished loop.** Server remembers; agent does not act on it.
5. **Fair A/B needs an anti-copy rule.** Raw must not read sibling trial workspaces or CE diffs.

---

## 9. Likely fixes (in order of importance)

These are directions, not a new tool redesign.

### A. Fix the trial fairness (do this before the next rematch)

- Ban shell access to other arms’ folders / diffs  
- Or run arms in fully isolated machines / no shared parent listing  
- Fail the arm if it copies from `ce_*_workspace` or reads the sibling diff  

Otherwise every CE-first / raw-second run can be poisoned the same way.

### B. Hard anti-thrash in instructions (short, blunt)

Examples of rules that need to be sharper than “few searches”:

- After **2** soft searches on a topic, pick a file and edit  
- Exact search: **at most 3** per task unless the last one failed empty  
- If `read` returns unchanged: **do not read that target again**; edit or move on  
- Call `recall` once before any mid-task re-search  
- After first edit: no new search unless a test error names a new symbol  

### C. Make the tools push back (server-side)

Ideas that match what we saw:

- If the same `read` target is requested again → return an even louder error-shaped hint: `stop_re_read: true`, `next: edit`  
- Cap exact `search` results / refuse near-duplicate exact queries in one session  
- Have `search` / `read` responses say clearly: “enough to edit” when a high-confidence hit exists  

### D. Rematch only after A + B

Fair rematch checklist:

- Arms cannot see each other  
- Same prompt, model, seal  
- Judge: work tokens, first-edit step, locate calls before edit, native_locate=0, task complete  

---

## 10. One-paragraph summary

We successfully forced the agent to find code only with Context Engine. It finished the real feature work. It did **not** finish efficiently: it ran dozens of tiny exact searches, re-asked for files it already had (getting “unchanged” again and again), never used `recall`, and edited late while still searching. Separately, the raw arm looked cheap only because it **copied CE’s finished files**, so the +691% score is not a fair CE-vs-Grep result. Next work is: stop cross-arm copying, then tighten stop-rules (and maybe server refusals) so sealed CE means *fewer* steps, not *more obedient thrash*.

---

## 11. Pointers to evidence

| Evidence | Where |
|---|---|
| Report table | `...\20260810T170518Z\REPORT.md` |
| CE arm metrics | `...\ce_nav-arm.json` |
| Raw arm metrics | `...\raw-arm.json` |
| CE tool transcript | `...\ce_nav-conversation.json` |
| Raw copy-via-shell | `...\raw-conversation.json` (shell commands copying from `ce_nav_workspace`) |
| Same file lists | both arms: 18 `src/` files + same new test + docs |
