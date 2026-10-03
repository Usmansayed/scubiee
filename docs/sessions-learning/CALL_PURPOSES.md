# What are the API calls actually spent on? (auto-generated)

Per-purpose call counts across dev cells, by arm. The question: which calls could a better
tool collapse? Source: data/sessions.jsonl.

## Average calls per purpose, per cell

| arm | cells | locate_find | read_body | locate_wire | grep_literal | edit | other | pre-edit locate steps |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| without | 10 | 0.0 | 3.4 | 5.2 | 0.9 | 3.9 | 3.9 | 7.9 |
| mini | 7 | 0.9 | 2.9 | 3.6 | 0.3 | 2.0 | 3.0 | 6.6 |
| mini_v3 | 19 | 1.1 | 1.6 | 1.2 | 0.4 | 3.1 | 0.5 | 4.2 |
| newmap | 15 | 1.1 | 1.9 | 1.4 | 0.1 | 3.4 | 0.5 | 4.2 |
| mini_plus | 2 | 1.0 | 1.0 | 1.5 | 0.5 | 4.0 | 0.5 | 4 |

## Reading it
- **read_body** = the agent fetching code (native Read, or map view/include_bodies).
- **locate_wire** = calls spent tracing callers/callees/uses (map refs/around or grep chains).
- **pre-edit locate steps** = how many non-edit retrieval calls happen before the first edit;
  this is the number a better tool must drive toward 1.

## Most common consecutive retrieval steps (collapse targets)

| from -> to | count |
|---|--:|
| locate_wire -> locate_wire | 79 |
| other -> other | 43 |
| locate_find -> read_body | 37 |
| locate_wire -> read_body | 28 |
| read_body -> other | 26 |
| read_body -> locate_wire | 19 |
| read_body -> read_body | 19 |
| read_body -> grep_literal | 13 |
| grep_literal -> read_body | 11 |
| other -> locate_wire | 11 |
| locate_find -> locate_wire | 5 |
| other -> read_body | 4 |

