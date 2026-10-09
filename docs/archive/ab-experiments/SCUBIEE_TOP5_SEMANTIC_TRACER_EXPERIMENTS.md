# Scubiee / TraceMap — Top 5 Semantic Tracer Architectures & Experiments

## Objective

We already have `composite_v1` as the structural baseline. It uses AST/LSP call relationships, optional Graphify/PDG, DFG, forward membership filtering, best-first expansion, hop decay, sink/faction precision guards, and composite ranking.

The current semantic experiments mostly operate **inside the structural island**. That means they can demote or rerank nodes the graph has already discovered, but they cannot reliably recover important nodes that the structural graph never reaches. The current research notes identify this as the central proposal/recall gap. fileciteturn0file0L11-L20

The next research phase should therefore test fundamentally different ways of using vectors.

### Core principle

> **The graph provides program-grounded evidence. The vector space provides semantic evidence. The tracer should intelligently combine them rather than treating vector similarity as truth.**

The five architectures below are deliberately different. Implement them independently enough that we can measure what actually works.

---

# Architecture 1 — Vector Candidate Proposal → Structural Verification

## Hypothesis

The biggest weakness in the current semantic tracer is that embeddings do not propose new pack membership. If a relevant symbol is outside the structural frontier, semantic filtering cannot recover it.

This architecture directly attacks that problem.

## Pipeline

```text
Query + Seed
    ↓
composite_v1 structural trace
    ↓
current graph frontier
    ↓
FAISS / vector search over PRODUCT embedding space
    ↓
top-K semantic candidates outside current frontier
    ↓
chunk → file → AST symbol resolution
    ↓
structural verification
    ↓
accepted candidates become new seeds/frontier nodes
    ↓
composite-style expansion
    ↓
final heatmap
```

The existing research notes explicitly identify this `chunk → symbol` bridge and vector proposal as a primary hypothesis to test. fileciteturn1file0L11-L20

## Critical difference from current teleport

Do NOT implement:

```text
vector neighbor → automatically hot
```

Instead:

```text
vector neighbor → candidate
                    ↓
              structural evidence
                    ↓
            verify / reject / weak-accept
```

The vector system is allowed to suggest a missing semantic island, but the graph remains the authority for program relationships.

## Vector retrieval

Use the existing PRODUCT FAISS collection first. Do not create another unrelated embedding corpus for this experiment.

The research notes specifically identify the current mismatch between product enriched-chunk vectors and trace-lab symbol vectors as an architecture problem. fileciteturn0file0L75-L93

### Retrieve

For a query, test:

```text
top 10
top 20
top 50
top 100
```

Measure whether the true missing symbols appear.

## Candidate promotion

For every vector candidate:

```text
chunk
 → file
 → AST node(s)
 → symbol
 → graph node ID
```

Determine whether:

- the symbol is already present
- the file is already present
- the candidate has a path to the traced graph
- the candidate shares data flow
- the candidate shares callers/callees
- the candidate belongs to a relevant semantic cluster

Then assign a proposal score.

## Experiments

### A1
Vector candidate is accepted only if there is a graph path to the current trace.

### A2
Allow one-hop structural bridge.

### A3
Allow two-hop structural bridge.

### A4
Allow shared symbol/data-flow evidence without direct call path.

### A5
Allow isolated semantic candidates only when similarity exceeds a very high threshold.

## Measure

The main question:

> Can vector proposals recover the exact must-symbols that `composite_v1` misses?

Especially test the known hard cases where composite and fuse miss the same symbols. fileciteturn1file0L143-L253

## Success condition

This architecture is valuable only if it increases must-recall on seed-hard boards **without a major precision collapse**.

---

# Architecture 2 — Semantic Frontier / Best-First Expansion

## Hypothesis

Instead of using vectors only to find extra nodes, use semantic similarity to determine:

> **Which of the currently available graph edges should we expand next?**

This changes semantic search from a retrieval operation into a traversal-control mechanism.

## Pipeline

```text
Seed
 ↓
Graph neighborhood
 ↓
Candidate outgoing edges
 ↓
For each candidate:
    graph score
    DFG score
    BM25 score
    vector score
 ↓
Unified expansion score
 ↓
Priority queue / best-first search
 ↓
Expand highest-value candidate
 ↓
Update trace state
 ↓
Repeat
```

## Candidate scoring

For every candidate node consider:

```text
query_similarity
seed_similarity
trace_similarity
BM25
graph_distance
call_edge_strength
DFG strength
control dependency
path reinforcement
genericness
```

Example:

```text
verifyJWT()
    graph = 0.93
    semantic = 0.95
    DFG = 0.91
    BM25 = 0.84
    final = 0.94

logger.info()
    graph = 0.71
    semantic = 0.13
    DFG = 0.00
    BM25 = 0.07
    final = 0.12
```

## Fusion experiments

### B1 — Additive

```text
final = structural + semantic
```

### B2 — Multiplicative

```text
final = structural × semantic
```

### B3 — Gated

```text
semantic > threshold
AND
structural > threshold
```

### B4 — Learned

Feed all features to a small ranker such as:

- LightGBM
- XGBoost
- logistic regression

and predict:

```text
P(candidate is relevant)
```

## Why this matters

The current `composite_v1` already uses best-first expansion and hop decay. The experiment is to determine whether semantic evidence can improve the **ordering of expansion**, rather than merely modifying the final heat after traversal.

## Stopping

Test:

- fixed hop limit
- score floor
- semantic score floor
- marginal information gain
- priority queue exhaustion

## Success condition

We want higher must-recall and/or faster discovery of must-symbols with the same or fewer nodes explored.

---

# Architecture 3 — Multi-View Semantic Representation

## Hypothesis

A single code embedding is too crude.

A function has multiple meanings:

- what its source code says
- what its symbol name says
- what it does
- what data passes through it
- how it relates to the graph

The vector system should represent these separately.

## Build multiple representations for every graph node

### View 1 — Raw Code

```text
function verifyJWT(token) {
    ...
}
```

### View 2 — Symbol Representation

```text
Function:
verifyJWT

Parameters:
token

Return:
payload
```

### View 3 — Behavior Representation

```text
Purpose:
validates JWT

Inputs:
token

Outputs:
claims/payload

Operations:
decode
signature verification
expiration check
```

### View 4 — Data-flow Representation

```text
token
 → verifyJWT
 → payload
 → userId
```

### View 5 — Graph-context Representation

```text
Called by:
authMiddleware

Calls:
decodeJWT
verifySignature

Reads:
JWT_PUBLIC_KEY

Returns:
authenticated claims
```

The representations should be generated primarily from deterministic program intelligence rather than an LLM.

## Vector storage

Each vector record must preserve:

```text
node_id
representation_type
file
symbol
line range
corpus fingerprint
embedding model/version
```

so every vector result maps back to the canonical graph node and heatmap location.

## Query matching

For each candidate:

```text
query ↔ raw_code
query ↔ symbol
query ↔ behavior
query ↔ dataflow
query ↔ graph_context
```

Then experiment with:

```text
max similarity
weighted average
learned fusion
```

Example:

```text
verifyJWT

raw_code       = 0.81
symbol         = 0.73
behavior       = 0.95
dataflow       = 0.92
graph_context  = 0.89
```

This may reveal that behavioral/data-flow representations are much more useful than raw chunk embeddings.

## Additional experiment

Embed the QUERY against:

- whole function
- function summary representation
- data-flow representation
- path representation

and compare recall.

## Success condition

Determine whether multi-view embeddings can discover relevant code that the existing single representation misses.

---

# Architecture 4 — Semantic Trace State + Semantic Islands

## Hypothesis

The meaning of the investigation changes as tracing progresses.

The initial query may be vague:

```text
"Fix the authentication bug."
```

After exploration, the system may discover:

```text
authentication
JWT
session expiry
refresh tokens
```

The tracer should therefore maintain a dynamic semantic state instead of repeatedly embedding only the original query.

## Trace state

Maintain:

```text
query embedding

seed embeddings

high-confidence node embeddings

important data-flow embeddings

important path embeddings

semantic clusters discovered

current frontier
```

## Trace vector

Experiment with:

```text
trace_vector =
weighted combination of:
    query
    seed
    hot nodes
    recent path
    important data-flow
```

Weights should favor high-confidence nodes.

## Dynamic semantic search

At each exploration stage:

```text
current trace state
      ↓
vector search
      ↓
semantic neighbors
      ↓
compare against existing graph
      ↓
identify possible missing semantic islands
```

## Semantic island detection

Suppose the trace contains:

```text
authentication
JWT
middleware
```

Vector search finds a strong cluster around:

```text
session expiry
refresh session
session store
```

but none of those nodes are currently in the graph.

Mark this as:

```text
POTENTIAL MISSING SEMANTIC ISLAND
```

Then verify it structurally.

Do NOT automatically make the entire cluster hot.

## Multi-cluster representation

Do not assume one centroid is enough.

Experiment with:

```text
authentication cluster
session cluster
database cluster
authorization cluster
```

and calculate candidate similarity against the most relevant cluster.

## Why this architecture is different

Architecture 1 uses vectors to propose nodes.

Architecture 4 uses vectors to understand the **evolving meaning of the entire investigation**.

## Success condition

Test whether dynamic trace-state embeddings recover relevant regions missed by:

- query-only vector search
- seed-only vector search
- static graph traversal

---

# Architecture 5 — Learned Semantic Heat / Information-Gain Tracer

## Hypothesis

Rather than hand-tuning dozens of semantic and graph weights, use the benchmark data to learn what combinations of signals actually predict relevance.

This should be the most ambitious experiment.

## Feature vector

For each candidate node/edge/path:

```text
graph distance

edge type

call strength

DFG strength

control dependency

query similarity

seed similarity

trace similarity

BM25 score

raw-code similarity

behavior similarity

data-flow similarity

graph-context similarity

nearest-hot-node similarity

number of supporting paths

node degree

repository frequency

genericness

foreign/faction score

path length
```

## Training target

For every benchmark task:

```text
1 = task-relevant
0 = irrelevant
```

Optionally use graded labels:

```text
1.0 = essential
0.75 = strongly useful
0.50 = useful
0.25 = weakly relevant
0.0 = irrelevant
```

## Models to test

Start extremely simple:

### C1
Logistic regression

### C2
LightGBM

### C3
XGBoost

Only investigate neural/GNN approaches if these plateau.

## Output

```text
P(node is relevant)
```

This becomes the heat value or an input to the final heat function.

---

# Information-Gain Expansion

This architecture should also experiment with:

> Which expansion gives the most new useful information per unit of traversal cost?

For a candidate:

```text
new semantic concepts
+
new graph relationships
+
new data-flow relationships
+
new relevant files
+
new relevant symbols
```

versus:

```text
cost of exploring candidate
```

Potential score:

```text
information_gain =
new_relevant_information / expansion_cost
```

Use this to decide when to stop.

## Example

```text
Expansion 1:
finds JWT validation
high gain

Expansion 2:
finds user lookup
high gain

Expansion 3:
finds permission check
high gain

Expansion 4:
finds logger helper
very low gain

Expansion 5:
finds metrics wrapper
very low gain
```

The tracer should stop once the expected information gain becomes consistently low.

## Success condition

Beat manually tuned composite/semantic heuristics on held-out benchmark cases.

---

# Cross-Architecture Experiment Matrix

Do NOT only compare the final five implementations.

Run controlled ablations.

## Baseline

```text
A0 = composite_v1
```

## Semantic proposal

```text
A1 = composite_v1 + vector proposal
```

## Semantic best-first

```text
A2 = composite_v1 + vector-guided edge ranking
```

## Multi-view

```text
A3 = composite_v1 + multi-view vectors
```

## Dynamic semantic state

```text
A4 = composite_v1 + trace-state vectors
```

## Learned ranker

```text
A5 = composite_v1 + learned semantic heat
```

Then combinations:

```text
A6 = A1 + A2
A7 = A1 + A3
A8 = A1 + A4
A9 = A1 + A2 + A3
A10 = full hybrid
```

Do not assume the full hybrid will win.

---

# Critical Benchmark Design

The existing experiments show an important evaluation problem:

When the seed is already in the correct must-file, structural methods have a large advantage, and semantic filtering can appear to tie even if it has useful recall potential. fileciteturn0file0L613-L614

Therefore create two benchmark categories.

## Category A — Seed-perfect

Seed is already inside the important region.

Purpose:

- measure precision
- measure noise
- measure ranking
- measure unnecessary expansion

## Category B — Seed-hard

Seed is relevant but structural tracing is known to miss at least one important must-symbol.

Purpose:

- measure semantic recall
- measure vector proposal effectiveness
- measure semantic island recovery

The most important metric for the new vector architectures is:

```text
Δ must-recall over composite_v1
```

not simply:

```text
more nodes retrieved
```

---

# Ground Truth Protocol

Maintain the blind protocol.

For each task:

```text
1. Write query without looking at gold context.
2. Run map.
3. Select seed/chunks.
4. Run tracer.
5. Save output.
6. ONLY THEN independently determine ground-truth context.
```

Do not inspect expected answers before tracing.

This prevents the benchmark from becoming biased.

---

# Required Metrics

Every experiment should report:

### Recall

```text
must nodes found / total must nodes
```

### Precision

```text
must/relevant nodes found / total returned nodes
```

### Top-K recall

How many required nodes appear in:

```text
top 5
top 10
top 20
```

### Must-file recall

### Must-symbol recall

### False negatives

Especially critical missing nodes.

### False positives

Especially high-heat false positives.

### Mean heat

Useful only as a secondary metric.

### Nodes explored

### Edges explored

### Vector queries

### Runtime

### Tokens to first correct body

### Agent task success

Ultimately:

> Does the resulting context help the coding agent solve the task?

---

# Required Failure Analysis

For every false negative, determine:

```text
Was the node absent from the vector index?

Was it present but outside top-K?

Was the chunk → symbol mapping wrong?

Was semantic similarity too low?

Was graph verification too strict?

Was the node structurally disconnected?

Was the wrong representation embedded?

Was the tracer stopped too early?
```

For every false positive:

```text
Why did vectors think it was relevant?

Was the graph relationship misleading?

Was the node too generic?

Was BM25 misleading?

Was the embedding representation poor?

Did a high-degree hub attract heat?
```

This analysis is more important than simply reporting one aggregate F1 number.

---

# Very Important Engineering Rule

Do NOT destroy the existing `composite_v1`.

All new experiments must be feature-flagged.

For example:

```text
CTX_TRACE_SEMANTIC_PROPOSAL=0
CTX_TRACE_SEMANTIC_FRONTIER=0
CTX_TRACE_SEMANTIC_STATE=0
CTX_TRACE_SEMANTIC_MULTIVIEW=0
CTX_TRACE_SEMANTIC_LEARNED=0
```

The default must remain:

```text
composite_v1
```

until an experiment demonstrates a consistent improvement on blind seed-hard tasks.

This is consistent with the current research stance. fileciteturn1file0L34-L39

---

# What We Ultimately Want

The final tracer should conceptually behave like this:

```text
                 QUERY
                   +
                SEED
                   │
                   ▼
          PROGRAM KNOWLEDGE GRAPH
                   │
       ┌───────────┼───────────┐
       ▼           ▼           ▼
      CALLS       DFG          PDG
       │           │           │
       └───────────┼───────────┘
                   ▼
             CURRENT TRACE
                   │
          ┌────────┴────────┐
          ▼                 ▼
      VECTOR SEARCH       BM25
          │                 │
          └────────┬────────┘
                   ▼
             CANDIDATES
                   │
                   ▼
           SEMANTIC + GRAPH
              SCORING
                   │
                   ▼
             BEST PATH(S)
                   │
                   ▼
           TRACE / EXPAND
                   │
                   ▼
        UPDATE SEMANTIC STATE
                   │
                   ▼
           MISSING-ISLAND CHECK
                   │
             ┌─────┴─────┐
             ▼           ▼
          EXPAND        STOP
             │
             └────────↺
                   │
                   ▼
              HEATMAP 🔥
```

The key property is:

> **Vectors should help the tracer decide where to explore, not merely make already-discovered nodes hotter or colder.**

---

# Final Rule

Do not conclude that semantic search is useful because:

- scores look nicer
- heatmaps look more intuitive
- more nodes were found
- average similarity increased

The only meaningful question is:

> **Can we use semantic vector information to recover important code that `composite_v1` misses, rank the right paths higher, reduce unnecessary exploration, and ultimately improve agent task success without destroying precision or speed?**

The current evidence establishes that the existing semantic arms do not reliably recover the structural misses. fileciteturn1file0L36-L39

The next experiments must therefore focus specifically on **semantic proposal, semantic path selection, evolving semantic state, and learned relevance**, rather than another simple embedding-based filter.
