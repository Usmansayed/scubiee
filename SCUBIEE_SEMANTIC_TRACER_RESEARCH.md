# Scubiee — Semantic Tracer Research & Cursor Agent Task

## Mission

Build and experimentally determine the best **non-LLM semantic code tracer** for Scubiee.

The core problem is:

> Given a natural-language query and a seed code chunk/symbol known to be relevant, trace the repository and produce the smallest, highest-quality set of code needed to understand the requested behavior.

The tracer must decide:

- Which connected nodes are relevant
- Which graph edges/paths should be expanded
- Which paths should be ignored
- How far to trace
- When to stop
- Which disconnected semantic areas may have been missed
- How strongly every discovered node should be ranked

The final output should be a **relevance heatmap**, ideally down to symbol and line range, with enough evidence to explain why each node received its score.

**Do not start by building a large LLM-based solution.** The goal is to exploit programming intelligence, static analysis, graph algorithms, lexical retrieval, embeddings, and small/cheap learned ranking where useful. LLMs may be used later only as an optional comparison/baseline if needed.

---

# 1. Core Research Hypothesis

Traditional code RAG treats a repository too much like a collection of text chunks.

Scubiee should instead treat the repository as a **heterogeneous program graph** and solve a relevance propagation / search problem over that graph.

Conceptually:

```text
QUERY + SEED CHUNK
        |
        v
PROGRAM INTELLIGENCE
        |
        +--> AST / Tree-sitter
        +--> LSP / compiler symbol resolution
        +--> Call graph
        +--> CFG
        +--> DFG
        +--> PDG
        +--> References / imports / types
        +--> Code Property Graph / Graphify / Joern if useful
        |
        v
CANDIDATE PROGRAM SUBGRAPH
        |
        +--> BM25 / lexical retrieval
        +--> Code embeddings / vector search
        +--> structural relevance
        +--> data-flow relevance
        +--> control-flow relevance
        +--> path reinforcement
        +--> node specificity / genericness
        |
        v
RELEVANCE PROPAGATION / PRIORITIZED SEARCH
        |
        +--> prioritized slicing
        +--> Personalized PageRank / relevance diffusion
        +--> best-first traversal / priority queue
        +--> query-conditioned edge weights
        |
        v
HEATMAP
        |
        v
STOP WHEN MARGINAL INFORMATION GAIN IS LOW
```

---

# 2. Research Areas That Must Be Investigated

The following are not assumptions that they all belong in the final system. They are candidate technologies/algorithms that must be implemented and benchmarked.

## 2.1 Program Slicing

Investigate:

- Forward slicing
- Backward slicing
- Bidirectional slicing
- Static slicing
- Demand-driven slicing

Question:

> Starting from a seed symbol/value/statement, what program elements can affect it or be affected by it?

Measure how much useful coverage a conventional slice provides and how much irrelevant code it introduces.

### Important research direction

Investigate **prioritized static slicing / PrioSlice-style approaches** that assign relative importance/probability to statements/nodes instead of producing a flat slice.

This is highly relevant to Scubiee's heatmap idea.

---

# 3. Program Dependence Graphs

Investigate and implement a graph representation combining:

- Data dependencies
- Control dependencies
- Function calls
- Symbol references
- Interprocedural dependencies where feasible

The **Program Dependence Graph (PDG)** should be treated as one of the main semantic foundations.

The tracer should distinguish:

```text
A -> calls -> B
A -> controls -> B
A -> produces_data_for -> B
A -> references -> B
A -> imports -> B
```

These edges should not have identical importance.

---

# 4. Data Flow Analysis

This is a high-priority capability.

Build or integrate reliable analysis for:

- Variable definitions
- Uses
- Parameter flow
- Return-value flow
- Field/object propagation where possible
- Interprocedural data flow where practical
- Sources
- Transformations
- Sinks

Example:

```text
HTTP request
   |
   v
Authorization header
   |
   v
extractToken()
   |
   v
token
   |
   v
verifyJWT()
   |
   v
payload.userId
   |
   v
getUser()
   |
   v
authenticated user
```

The tracer should be able to recognize this as a coherent behavioral chain even when individual symbol names are generic.

---

# 5. Control Flow

Investigate:

- Control Flow Graphs
- Branch conditions
- Exception paths
- Async boundaries where statically discoverable
- Event/callback relationships

This matters because code can be relevant because it **controls execution**, even when there is no direct data-flow edge.

Example:

```text
if authenticated:
    allowRequest()
```

Authentication state controls request authorization even if there is no obvious data transformation.

---

# 6. Code Property Graph

Deeply investigate **Code Property Graph (CPG)** approaches.

Evaluate whether an existing implementation such as Joern/CPG can provide useful low-level program intelligence instead of reinventing everything.

Explore whether CPG can unify or expose:

- AST
- CFG
- Data Flow
- Control Dependence
- Call Graph
- Type information
- Symbol relationships

The goal is not to adopt a tool because it is popular. Benchmark whether it improves tracing quality and development speed.

---

# 7. Graphify

Graphify is available in the Scubiee ecosystem and should be treated as an important candidate source of structural relationships.

Evaluate:

- What graph entities it already provides
- What edge types it exposes
- How accurate those edges are
- What it misses
- Whether it duplicates AST/LSP/CPG information
- Whether it improves recall/precision
- Whether it creates excessive noise

Graphify should be one source of program structure, not automatically the whole tracing algorithm.

---

# 8. LSP / Compiler Intelligence

Use deterministic language intelligence wherever possible.

Investigate:

- Go-to-definition
- Find-references
- Symbol hierarchy
- Call hierarchy
- Type hierarchy
- Type inference where exposed
- Workspace symbol indexing
- Language-specific compiler APIs

The principle is:

> Never use an LLM to answer a fact the language/tooling can determine exactly.

Examples:

```text
Where is this function defined?
Who calls this function?
What type does this value have?
Which implementations satisfy this interface?
What symbol does this reference resolve to?
```

These should be deterministic whenever possible.

---

# 9. BM25 / Lexical Retrieval

Do not use BM25 only as a first-stage chunk retriever.

Use it as a relevance signal throughout tracing.

Given the query, score:

- Files
- Symbols
- Function descriptions
- Identifiers
- Comments/docstrings
- Structured symbol summaries

Consider query expansion into multiple lexical concepts.

Example:

```text
authentication
JWT validation
token verification
user identity
session validation
authorization
```

Use lexical retrieval to discover candidates the structural graph may not reach.

---

# 10. Embeddings / Vector Search

Do not make vector search the source of truth.

Use it for **semantic candidate discovery** and semantic relevance signals.

Maintain multiple possible vector representations:

### A. Raw code chunks

Traditional code chunk embeddings.

### B. Symbol-level representations

Represent functions/classes using structured information:

```text
SYMBOL: verifyJWT
INPUTS: token
OUTPUTS: payload
CALLS: decodeJWT, verifySignature
CALLED_BY: authMiddleware
ROLE: token validation / authentication
```

### C. Data-flow summaries

Embed meaningful program flows.

### D. Module-level behavior summaries

Embed a concise deterministic summary of module responsibilities.

The vector DB should primarily answer:

> What semantically related area might we be missing?

Then verify or strengthen that candidate using program structure.

Principle:

> Vector search proposes. Program intelligence verifies.

---

# 11. Multi-Level Semantic Representation

Do not create only a file-to-file graph.

Represent multiple node levels:

```text
Repository
  |
  +-- Module
        |
        +-- File
              |
              +-- Class
              |     |
              |     +-- Method
              |
              +-- Function
              |     |
              |     +-- Variable / parameter / return
              |
              +-- API route
              +-- Event
              +-- Database interaction
```

The tracer should be able to zoom from coarse to fine:

```text
Repository
  -> Module
    -> File
      -> Symbol
        -> Code region / line range
```

This enables hierarchical tracing rather than expanding thousands of low-level nodes immediately.

---

# 12. Heterogeneous Graph

Different node types and edge types matter differently.

Potential node types:

- File
- Module
- Class
- Function
- Method
- Variable
- Parameter
- Return value
- API route
- Database table/query
- Event
- Configuration key

Potential edge types:

- CALLS
- CALLED_BY
- READS
- WRITES
- PRODUCES
- CONSUMES
- PASSES_DATA_TO
- CONTROLS
- REFERENCES
- IMPORTS
- EXPORTS
- IMPLEMENTS
- INHERITS
- ROUTES_TO
- EMITS
- LISTENS_TO
- DATABASE_READ
- DATABASE_WRITE

The traversal engine must understand that these are not equivalent.

---

# 13. Query-Conditioned Traversal

The tracer must adapt graph behavior to the query.

Examples:

## Query

```text
How does authentication work?
```

Prioritize:

```text
CALLS
DATA FLOW
CONTROL FLOW
ROUTES
MIDDLEWARE
AUTHORIZATION
```

## Query

```text
Where is authentication configured?
```

Prioritize:

```text
CONFIG REFERENCES
ENVIRONMENT REFERENCES
IMPORTS
SYMBOL REFERENCES
CONFIG LOADERS
```

## Query

```text
What happens after payment succeeds?
```

Prioritize:

```text
DOWNSTREAM CALLS
EVENTS
ASYNC JOBS
WEBHOOKS
DATABASE WRITES
```

Build an explicit concept of **trace mode**.

Start with deterministic query classification where possible rather than immediately adding an LLM.

---

# 14. Best-First Search

Do not use naive BFS as the primary tracer.

Build a priority queue.

At every step:

1. Generate candidate expansions
2. Score them
3. Put them in a priority queue
4. Expand the highest-value candidate
5. Update the heatmap
6. Re-score frontier candidates
7. Continue until stopping criteria are reached

Conceptually:

```text
0.98 -> verifyJWT
0.94 -> getUserFromToken
0.82 -> refreshSession
0.71 -> rateLimiter
0.12 -> logger
0.07 -> analytics
```

Expand high-value paths first.

---

# 15. Relevance Propagation / Personalized PageRank

Implement a graph diffusion experiment.

Start with the seed node(s) as high-confidence relevance sources.

Propagate relevance through the heterogeneous graph.

Use edge-type-specific weights.

Example starting point only — these values must be benchmarked, not assumed:

```text
DATA_FLOW            1.00
CALLS                0.90
CONTROL_DEPENDENCY   0.90
REFERENCES           0.70
TYPES                0.60
IMPORTS              0.30
GENERIC_UTIL         0.10
```

Compare:

- Plain graph distance
- Weighted diffusion
- Personalized PageRank
- Best-first traversal
- Hybrid approaches

---

# 16. Prioritized Slicing

Implement a PrioSlice-like experiment.

Instead of asking only:

```text
Is this node inside the slice?
```

ask:

```text
How strongly should this node matter?
```

Generate a relevance score for every reachable node and order nodes by estimated importance.

This is expected to be one of the strongest candidates for the heatmap layer.

---

# 17. Path Reinforcement

A node reached through multiple independently relevant paths should generally receive greater confidence.

Example:

```text
authMiddleware -> getUser -> userRepository

sessionService -> getSessionUser -> userRepository
```

If both paths are relevant to the query, `userRepository` should receive stronger evidence than a node reached through only one weak path.

Implement a path reinforcement feature.

---

# 18. Generic-Node Penalty

Large repositories contain nodes such as:

```text
logger
metrics
config
helpers
common utilities
shared wrappers
```

These can be structurally connected to thousands of nodes.

Create a genericness / repository-frequency signal.

A node that is used everywhere should not receive high relevance merely because it is connected.

This is conceptually similar to the intuition behind IDF in information retrieval.

Experiment with a **Code Relationship IDF / specificity** feature.

---

# 19. Data Importance

Not every variable or data item matters equally.

Build features for data importance.

A value should become more important when it:

- Propagates across multiple functions
- Controls branches
- Reaches a database write
- Reaches an API response
- Determines authorization
- Is consumed by important downstream nodes
- Appears in the central execution path

Example:

```text
token       HIGH
payload     HIGH
userId      HIGH
user        HIGH

loggerEvent LOW
metricName  LOW
```

The goal is to trace **behaviorally meaningful data**, not every variable.

---

# 20. Semantic Teleportation

Graph traversal can miss disconnected semantic areas.

Therefore, periodically use BM25 and embeddings to ask:

> Are there important semantic regions we have not reached structurally?

Example:

```text
Graph exploration
      |
      v
Candidate frontier
      |
      +--> BM25 search
      +--> Vector search
      |
      v
Potential missing semantic nodes
      |
      v
Structural validation
      |
      v
Add valid candidates to frontier
```

This should be a controlled mechanism, not a constant vector search loop.

---

# 21. Stopping / Expansion Logic

Do not use only a fixed hop count such as:

```text
Stop after 3 hops.
```

Implement several possible stopping signals.

### A. Heat threshold

Stop expanding nodes below a relevance threshold.

### B. Priority threshold

Stop when the best remaining frontier candidate is too weak.

### C. Marginal information gain

Track whether recent expansions discover meaningful new relevant information.

### D. Semantic saturation

Determine whether newly discovered nodes are increasingly redundant.

### E. Task coverage

For trace modes such as FLOW_TRACE, determine whether major source/process/sink components are already covered.

The goal is:

> Stop because additional expansion has low information value, not because an arbitrary depth was reached.

---

# 22. Information Gain

Experiment with an explicit information-gain concept:

```text
Information Gain of Expansion
= New Relevant Information Discovered
  -----------------------------------
  Expansion Cost
```

An expansion that discovers another core dependency is valuable.

An expansion that discovers the 37th generic logger/helper is not.

This should influence traversal and stopping.

---

# 23. Learn-to-Rank Instead of LLM

Once enough benchmark data exists, test lightweight ML ranking models:

- Logistic regression
- LightGBM
- XGBoost
- Random forest
- Small neural ranker if justified

Features may include:

```text
graph distance
edge type
call strength
data-flow strength
control dependency
BM25 score
embedding similarity
number of supporting paths
node specificity
genericness
query mode
file/module relevance
source/sink importance
```

Output:

```text
P(node is relevant)
```

This is potentially much cheaper and faster than an LLM while being trainable directly on Scubiee's benchmark data.

---

# 24. Optional Later Experiment: GNN

Do not start with a Graph Neural Network.

Only investigate GNNs after the deterministic + classical ranking approaches are benchmarked.

Potential future formulation:

> Given a heterogeneous program graph, query representation, and seed node, predict the probability that each node belongs to the relevant subgraph.

This is potentially powerful but introduces much greater complexity and training requirements.

---

# 25. Heatmap Output

The tracer should produce both machine-readable and human-readable output.

Example:

```text
QUERY:
How does authentication work?

HEATMAP

🔥 0.99
src/middleware/auth.ts
 authMiddleware()
 Lines 40–120

Reason:
Seed node / authentication entry point

🔥 0.96
src/services/jwt.ts
 verifyJWT()
 Lines 22–90

Reason:
Direct downstream call + strong data-flow relationship

🟠 0.84
src/repositories/user.ts
 findUserById()
 Lines 44–88

Reason:
User identity propagated from authentication flow

🟢 0.05
src/utils/logger.ts
 logger.info()

Reason:
Structurally connected but generic and not behaviorally relevant
```

Each result should ideally include:

- File
- Symbol
- Line range
- Heat score
- Relationship type(s)
- Discovery path
- Contributing signals
- Short reason

---

# 26. Benchmark / Verification System — Build First

Verification is a first-class product requirement.

Before attempting a sophisticated final tracer, build a reproducible benchmark environment.

Each benchmark task should contain:

```text
Repository
Query
Seed chunk / seed symbol
Ground-truth relevant nodes
Optional relevance levels
```

Example:

```json
{
  "query": "How does authentication work?",
  "seed": {
    "file": "src/middleware/auth.ts",
    "symbol": "authMiddleware"
  },
  "relevant": [
    "authMiddleware",
    "verifyJWT",
    "decodeJWT",
    "getUser",
    "userRepository"
  ]
}
```

Ground truth does not need to be perfect initially, but it must be reviewable and consistently defined.

---

# 27. Compare Methods Independently

At minimum benchmark:

```text
A. BM25 only
B. Embeddings only
C. Structural graph only
D. Program slicing only
E. Prioritized slicing
F. Personalized PageRank
G. Best-first graph search
H. BM25 + graph
I. Embeddings + graph
J. BM25 + embeddings + graph
K. Full hybrid with data flow / control flow / PDG
L. Full hybrid + lightweight learned ranker
```

Do not jump directly to the final hybrid system.

We need to understand which components actually improve performance.

---

# 28. Evaluation Metrics

For every benchmark case measure:

## Recall

```text
Relevant nodes found
--------------------
Relevant nodes in ground truth
```

## Precision

```text
Relevant nodes found
--------------------
Total nodes returned
```

## False negatives

Track every missed important node.

For each false negative, record:

- Why it was missed
- Which graph edge could have found it
- Whether BM25 could have found it
- Whether embeddings could have found it
- Whether a different trace mode would have found it

## False positives

Track every irrelevant node ranked highly.

For each false positive, record:

- Why it received heat
- Which feature caused the mistake
- Whether genericness should have penalized it
- Whether an edge weight is incorrect

## Ranking quality

Relevant nodes should appear near the top.

Evaluate ranking quality, not just set membership.

## Efficiency

Measure:

- Nodes explored
- Edges explored
- CPU time
- Memory
- Vector searches
- BM25 queries
- Total retrieval work
- Approximate tokens if any optional model is used

---

# 29. Critical Research Metric: Coverage vs Noise

The key Scubiee objective is:

> **Maximum task-relevant coverage with minimum irrelevant exploration.**

Create a visualization/report for every experiment showing:

```text
Recall / Coverage
        vs
Irrelevant Nodes / Noise
```

The ideal system moves toward:

```text
HIGH RECALL
HIGH PRECISION
LOW EXPLORATION COST
```

---

# 30. Failure Analysis Is Mandatory

When the tracer fails, do not simply tune weights randomly.

Classify the failure.

Possible categories:

```text
Missing static relationship
Missing dynamic relationship
Missing event/callback relationship
Weak semantic similarity
Bad lexical match
Generic node pollution
Incorrect edge weighting
Incorrect query mode
Premature stopping
Graph explosion
Disconnected semantic island
Incorrect line localization
```

Each failure category should lead to a concrete experiment.

---

# 31. Experimental Configuration

All major signals should be configurable so experiments can be reproduced.

Example:

```yaml
retrieval:
  bm25: true
  embeddings: true

program_analysis:
  ast: true
  lsp: true
  call_graph: true
  cfg: true
  dfg: true
  pdg: true
  graphify: true

ranking:
  personalized_pagerank: true
  prioritized_slice: true
  best_first: true
  learned_ranker: false

weights:
  semantic: 0.5
  lexical: 0.4
  structural: 1.0
  dataflow: 1.0
  controlflow: 0.8
  path_reinforcement: 0.7
  generic_penalty: 0.6
```

The exact values should be discovered through experiments.

---

# 32. Suggested Development Order

Implement in this order:

```text
1. Benchmark format
2. Evaluation harness
3. Repository fixtures / benchmark tasks
4. Program symbol index
5. Call/reference graph
6. Data-flow / PDG capabilities
7. Basic program slicing
8. Prioritized slicing
9. Best-first traversal
10. Personalized PageRank
11. BM25 integration
12. Embedding integration
13. Semantic teleportation
14. Genericness / specificity features
15. Path reinforcement
16. Query-conditioned edge weighting
17. Learned ranking experiment
18. Final heatmap generator
19. Extensive failure analysis
```

Do not skip the evaluation harness.

---

# 33. Important Design Principle

**Do not ask an LLM to determine facts that program analysis can know exactly.**

Bad:

```text
LLM: Does function A call function B?
```

Good:

```text
LSP / compiler / AST: A calls B.
```

Then semantic intelligence should be used for the harder question:

```text
Given that A calls B, and the task is X,
how relevant is that path to solving X?
```

Even this should first be attempted using graph algorithms, search signals, and lightweight ML before introducing an LLM.

---

# 34. The Target Algorithm

The long-term goal is a system roughly like:

```text
                  QUERY
                    +
                SEED CHUNK
                    |
                    v
             QUERY / TRACE MODE
                    |
                    v
          HETEROGENEOUS PROGRAM GRAPH
                    |
          +---------+---------+
          |                   |
          v                   v
     STRUCTURAL             SEARCH
     INTELLIGENCE            INTELLIGENCE
          |                   |
     AST/LSP/PDG         BM25/Embeddings
          |                   |
          +---------+---------+
                    |
                    v
          CANDIDATE FRONTIER
                    |
                    v
        RELEVANCE / HEAT ENGINE
                    |
        +-----------+------------+
        |           |            |
        v           v            v
   Prioritized   PageRank    Best-first
     slicing     diffusion     search
        |           |            |
        +-----------+------------+
                    |
                    v
             PATH EXPANSION
                    |
                    v
          SEMANTIC TELEPORTATION
                    |
                    v
          INFORMATION-GAIN TEST
                 /       \
           continue       stop
              |             |
              +-------> HEATMAP
```

---

# 35. What Success Looks Like

Given:

```text
Query:
How does authentication work?

Seed:
authMiddleware()
```

the system should ideally return something like:

```text
🔥 0.99  authMiddleware()
🔥 0.96  verifyJWT()
🔥 0.91  decodeJWT()
🔥 0.88  getUserFromToken()
🔥 0.83  userRepository.findById()
🟠 0.76  permissionCheck()
🟡 0.48  sessionConfig
🟢 0.06  logger
🟢 0.03  metrics
```

with paths such as:

```text
authMiddleware
  -> verifyJWT
     -> decodeJWT
        -> payload.userId
           -> getUserFromToken
              -> userRepository.findById
```

The important property is not that every technically connected node is returned.

The important property is:

> **The tracer identifies the relevant behavioral subgraph with very few critical misses and very little unrelated noise.**

---

# 36. Cursor Agent Instructions

You are the coding/research agent responsible for implementing and experimentally evaluating this system.

## First task

**Do not immediately build the final tracer. Build the simulation/benchmark environment first.**

We need to be able to answer:

> Which tracing strategy actually works best?

Create benchmark repositories/tasks and an evaluation framework that can run multiple tracing algorithms against the same inputs and compare results.

## Second task

Implement simple baselines before complex algorithms.

At minimum:

```text
BM25
Embedding retrieval
Basic graph expansion
Standard program slice
```

## Third task

Implement and compare:

```text
Prioritized slicing
Personalized PageRank
Best-first graph traversal
```

## Fourth task

Add:

```text
Data Flow
Control Flow
PDG
Code Property Graph / Graphify
```

## Fifth task

Add:

```text
BM25 + graph
Embeddings + graph
BM25 + embeddings + graph
```

## Sixth task

Add more intelligence:

```text
Path reinforcement
Generic-node penalty
Query-conditioned edge weighting
Semantic teleportation
Information-gain stopping
```

## Seventh task

Only after sufficient benchmark data exists, test:

```text
LightGBM / XGBoost / logistic regression
```

as a relevance ranker.

## Eighth task

Generate the final line/symbol-level heatmap and detailed failure reports.

---

# 37. Rules for the Agent

1. **Measure before claiming improvement.**
2. **Keep every major algorithm independently switchable.**
3. **Record experiment configuration and results.**
4. **Do not tune against a single example.**
5. **Do not assume semantic similarity means actual program relevance.**
6. **Do not assume structural connectivity means task relevance.**
7. **Prefer deterministic program facts over generated guesses.**
8. **Track false negatives aggressively.** Missing critical code is more dangerous than returning a few extra nodes.
9. **Do not optimize only for recall.** Excessive false positives destroy agent efficiency.
10. **Do not optimize only for token count.** Task coverage and correctness matter more.
11. **Keep raw evidence for why each node received its heat.**
12. **When something fails, inspect the failure before changing the algorithm.**

---

# 38. Final Research Question

The central question for the entire project is:

> **Can a query-conditioned heterogeneous program graph, combined with program slicing, data/control-flow analysis, BM25, embeddings, relevance diffusion, and lightweight ranking, accurately reconstruct the smallest useful behavioral subgraph of a large repository starting from a single seed chunk—without requiring a large language model?**

If the answer is yes, that behavioral subgraph becomes the foundation of Scubiee's context acquisition system.

The final product is not merely search.

It is:

# **A semantic program tracer that knows what to follow, what to ignore, and when it has enough context.**
