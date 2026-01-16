# Knowledge Extraction Agent

## Overview

A background agentic process that analyzes OTel traces from dbmeta MCP server usage to extract knowledge artifacts and improve the system's semantic understanding over time.

## Problem Statement

The dbmeta MCP server provides tools and rules for Claude to invoke, but we lack control over:
- Tool choices made by Claude
- Whether Claude follows the protocol (looking for prior knowledge, domain model, cached schema, query examples, prior errors and gotchas)

We do have OTel traces of all tool calls, which contain valuable signal about successful patterns, failures, and user corrections.

## Pattern Context

This approach goes by several names:
- Self-improving agents / Learning loops
- Experience replay for LLMs
- Continuous learning pipelines
- Data flywheel

Notable examples in industry:
- Databricks AI/BI learns from query corrections
- LangSmith's annotation to fine-tuning pipelines
- Braintrust's "learning from production" workflows
- RAG systems that learn from user feedback

## Architecture

```
+-------------------------------------------------------------+
|                    PRODUCTION PATH                          |
|  User -> Claude -> dbmeta MCP -> Database                   |
|              |                                              |
|         OTel Traces                                         |
+-------------------------------------------------------------+
              |
              v
+-------------------------------------------------------------+
|                 LEARNING PATH (Background)                  |
|                                                             |
|  +----------+    +---------------+    +------------------+  |
|  |  Trace   |--->| LLM Extractor |--->| Knowledge Vault  |  |
|  |  Store   |    |  (Haiku/etc)  |    |   (examples/     |  |
|  +----------+    +---------------+    |    learnings/)   |  |
|                         |             +------------------+  |
|                         v                                   |
|                  +-------------+                            |
|                  |   Review    | <- Human-in-the-loop       |
|                  |   Queue     |    (recommended)           |
|                  +-------------+                            |
+-------------------------------------------------------------+
```

## Pros

| Benefit | Why It Matters |
|---------|----------------|
| Continuous improvement | Knowledge vault gets better without manual curation |
| Captures tacit knowledge | Successful query patterns that humans wouldn't think to document |
| Error pattern detection | Automatically identifies common failure modes, gotchas |
| Scales with usage | More queries -> more learning signal -> better performance |
| Reduces toil | No manual log review to extract lessons |
| Fast iteration | Can surface issues within hours, not weeks |

## Cons / Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Drift / Error amplification | HIGH | Human review queue, confidence thresholds |
| Hallucination laundering | HIGH | Validate extracted SQL actually works |
| Feedback loops | MEDIUM | Version control, A/B test new knowledge |
| Cost | LOW-MEDIUM | Use Haiku for extraction, sample traces |
| Observability of learning | MEDIUM | Audit log of what was learned and why |
| Stale/conflicting knowledge | MEDIUM | Deduplication, conflict detection |
| PII/sensitive data leakage | HIGH | Scrub traces before LLM processing |

## Critical Anti-Pattern to Avoid

**Unsupervised closed-loop learning:**

```
BAD:  Traces -> LLM -> Knowledge Vault -> Production (no human)
```

This creates compounding errors. One bad extraction becomes "ground truth" that influences future queries, which generates more traces that reinforce the error.

**The fix:**

```
GOOD: Traces -> LLM -> Staging/Review -> Human Approval -> Production
```

## What to Extract

| Trace Signal | Knowledge Artifact | Example |
|--------------|-------------------|---------|
| Successful novel query | `examples/*.yaml` | New NL->SQL mapping |
| SQL error + correction | `learnings/gotchas.md` | "Don't use X, use Y instead" |
| Schema confusion | `instructions/sql_rules.md` | "Table A vs B disambiguation" |
| Repeated similar queries | `examples/patterns.yaml` | Canonical form of common query |
| User correction | `learnings/corrections.md` | "When user says X, they mean Y" |

## High-Signal Trace Filters

Focus extraction on traces that show:
- User corrections ("no, I meant...")
- SQL errors followed by success
- Retry patterns that eventually succeeded
- Explicit user feedback (thumbs up/down)
- Novel query patterns not in existing examples

## Implementation Phases

### Phase 1: Manual/Semi-Automated (Quick Win)

Start with a manual approach to understand patterns before automating:

```bash
# Weekly: Generate learning candidates for review
python extract_learnings.py --since "7 days ago" > candidates.md

# Human reviews candidates.md, approves good ones
# Approved items get added to knowledge vault
```

This gives learning signal without automation risk.

### Phase 2: Background Worker with Review Queue

```python
class KnowledgeExtractor:
    
    def process_traces(self, since: datetime):
        traces = self.otel_store.get_traces(since=since)
        
        for trace in traces:
            # 1. Filter for high-signal traces
            if not self.is_interesting(trace):
                continue
            
            # 2. Extract candidate learnings
            candidates = self.extract_with_llm(trace)
            
            # 3. Validate (critical!)
            for candidate in candidates:
                if candidate.type == "example":
                    # Actually run the SQL to verify it works
                    if not self.validate_sql(candidate.sql):
                        continue
                
                # 4. Check for duplicates/conflicts
                if self.conflicts_with_existing(candidate):
                    self.flag_for_review(candidate, reason="conflict")
                    continue
                
                # 5. Route based on confidence
                if candidate.confidence > 0.9 and self.is_low_risk(candidate):
                    self.auto_approve(candidate)  # Optional
                else:
                    self.queue_for_review(candidate)
    
    def is_interesting(self, trace) -> bool:
        """Focus on high-signal traces"""
        return any([
            trace.had_user_correction,
            trace.had_sql_error,
            trace.had_retry_success,
            trace.had_explicit_feedback,
            trace.query_was_novel,
        ])
```

### Phase 3: Full Automation (with safeguards)

Only after Phase 2 proves stable:
- Auto-approve low-risk, high-confidence extractions
- Human review for edge cases and conflicts
- Continuous monitoring for drift
- Rollback capability

## Safeguards Checklist

For this to be a valid pattern (not anti-pattern):

- [ ] Human review (at least initially, can relax over time)
- [ ] Validate extracted SQL actually executes
- [ ] Rollback/versioning on the knowledge vault
- [ ] Selective trace processing (high-signal only)
- [ ] Monitor for drift (track knowledge vault changes over time)
- [ ] PII scrubbing before LLM processing
- [ ] Audit log of what was learned and why
- [ ] Conflict detection with existing knowledge

## Integration Points

### OTel Trace Store
- Current: Console HTTP exporter collects spans locally
- Needed: Persistent trace storage (SQLite, PostgreSQL, or dedicated like Jaeger)

### Knowledge Vault
- Location: `packages/resources/dbmeta_app/providers/{provider}/`
- Artifacts: `examples/`, `learnings/`, `instructions/`

### Review Queue
- Could be: GitHub PRs, Slack messages, dedicated UI
- Needs: Approve/reject workflow, audit trail

## Open Questions

1. **Trace retention**: How long to keep traces? Storage vs learning value tradeoff.
2. **Extraction frequency**: Real-time vs batch (hourly/daily)?
3. **Multi-tenant isolation**: Per-provider knowledge vaults or shared learnings?
4. **Confidence calibration**: How to tune auto-approve thresholds?
5. **Cost budget**: LLM calls per trace, sampling strategy?

## Related Work

- [LangSmith Annotation Queues](https://docs.smith.langchain.com/)
- [Braintrust Learning from Production](https://www.braintrust.dev/)
- [Databricks AI/BI Genie](https://www.databricks.com/product/ai-bi)
