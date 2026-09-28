# composite_v1 ship gate (verify_prod)

| Arm | Hard | Must-rec | Prec | F1 |
|-----|------|----------|------|-----|
| polytrace | 3/10 | 0.9167 | 0.7341 | 0.7837 |
| callgraph_jedi | 7/10 | 0.9667 | 0.6159 | 0.7324 |
| **composite_v1** | **9/10** | **0.9667** | **0.8351** | **0.8732** |

Gate (hard≥poly, must-rec≥0.90, F1≥poly): **PASS**

Failed composite: ['p19']

**Production default:** CTX_TRACE_ENGINE unset → composite_v1. Rollback: CTX_TRACE_ENGINE=polytrace.
