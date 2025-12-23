# Schema Relevance: Hybrid Search for Table Selection

## Problem Statement

When users reference tables by name patterns (e.g., "iceberg table"), the current semantic-only search fails to include the relevant table schema in the prompt, leading to:

1. **Missing schema** - Table excluded from "Database Schema Reference" section
2. **Hallucinated columns** - LLM invents column names from context clues in instructions
3. **Confident but wrong plans** - Plan summary says "all columns" but lists only 8 of 50+ actual columns

### Example Failure

**User request:** "list 1000 entries in iceberg table with all columns"

**Expected:** Schema for `iceberg.radius.wifi_qm_v2` included in prompt (50+ columns)

**Actual:** Table ranked outside top 10 by semantic search, excluded from prompt. LLM hallucinated 8 columns from instruction context.

## Root Cause Analysis

### Current Flow

```
User: "list 1000 entries in iceberg table"
    ↓
OpenAI embedding of query
    ↓
Milvus vector search (cosine similarity)
    ↓
Top 10 tables by semantic similarity
    ↓
iceberg.radius.wifi_qm_v2 NOT in top 10
    ↓
Schema excluded → hallucination
```

### Why Semantic Search Fails

1. **"iceberg" is a catalog name, not a semantic term**
   - Table embedding: `"Table iceberg.radius.wifi_qm_v2. Contains Wi-Fi Quality Metrics..."`
   - The word "iceberg" is a namespace prefix, not a descriptive concept

2. **Vector similarity optimizes for meaning, not keywords**
   - OpenAI embeddings interpret "iceberg" as frozen water/lettuce
   - No semantic connection to "Wi-Fi Quality Metrics"

3. **48 tables compete for top 10 slots**
   - Generic terms like "list entries" may match other tables better

## Proposed Solution: Hybrid Search

Combine keyword matching with semantic search for robust table selection.

### Phase 1: Keyword Boost (Quick Win)

Add keyword pre-filter before semantic search:

```python
# apps/db-meta/dbmeta_app/vector_db/milvus.py

def get_keyword_matched_tables(
    query: str, 
    all_tables: list[str],
    min_token_length: int = 3
) -> set[str]:
    """
    Force-include tables whose name parts appear in query.
    
    Matches on catalog, schema, or table name components.
    Example: "iceberg table" matches "iceberg.radius.wifi_qm_v2"
    """
    query_lower = query.lower()
    query_tokens = set(query_lower.split())
    matched = set()
    
    for table in all_tables:
        # Split table name into parts: iceberg.radius.wifi_qm_v2 → [iceberg, radius, wifi_qm_v2, wifi, qm, v2]
        name_parts = table.lower().replace(".", " ").replace("_", " ").split()
        
        for part in name_parts:
            if len(part) >= min_token_length and part in query_tokens:
                matched.add(table)
                break
    
    return matched


def search_relevant_tables_hybrid(
    query: str,
    profile: str,
    top_k: int = 10,
    client: Optional[str] = None,
    env: Optional[str] = None,
) -> list[TableMatch]:
    """
    Hybrid search: keyword matches + semantic search.
    
    1. Find tables with name parts matching query tokens
    2. Run semantic search for remaining slots
    3. Merge results (keyword matches first)
    """
    # Get all table names for keyword matching
    all_tables = get_all_table_names(profile, client, env)
    
    # Phase 1: Keyword matches (always included)
    keyword_matches = get_keyword_matched_tables(query, all_tables)
    
    # Phase 2: Semantic search for remaining slots
    semantic_k = max(top_k - len(keyword_matches), 5)
    semantic_matches = search_relevant_tables(
        query=query,
        profile=profile,
        top_k=semantic_k + len(keyword_matches),  # fetch extra to filter
        client=client,
        env=env,
    )
    
    # Phase 3: Merge (keyword first, then semantic, deduped)
    result = []
    seen = set()
    
    # Add keyword matches with boosted score
    for table_name in keyword_matches:
        if table_name not in seen:
            # Find in semantic results for metadata, or create stub
            match = next((m for m in semantic_matches if m.table_name == table_name), None)
            if match:
                match.score = 1.0  # Boost keyword matches
                result.append(match)
            else:
                result.append(TableMatch(
                    table_name=table_name,
                    description="",
                    columns={},
                    score=1.0
                ))
            seen.add(table_name)
    
    # Add semantic matches to fill remaining slots
    for match in semantic_matches:
        if match.table_name not in seen and len(result) < top_k:
            result.append(match)
            seen.add(match.table_name)
    
    return result[:top_k]
```

### Phase 2: BM25 Integration (Robust Solution)

Add proper BM25 scoring for better keyword relevance:

```python
# New dependency: pip install rank-bm25
from rank_bm25 import BM25Okapi

class TableSearchIndex:
    """Hybrid search index combining BM25 and vector similarity."""
    
    def __init__(self, table_records: list[dict]):
        # Build BM25 index
        self.table_names = [r["table_name"] for r in table_records]
        corpus = [self._tokenize(r["searchable_text"]) for r in table_records]
        self.bm25 = BM25Okapi(corpus)
    
    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text for BM25."""
        return text.lower().replace(".", " ").replace("_", " ").split()
    
    def search_bm25(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Return top_k tables by BM25 score."""
        query_tokens = self._tokenize(query)
        scores = self.bm25.get_scores(query_tokens)
        
        # Get top_k indices
        top_indices = sorted(
            range(len(scores)), 
            key=lambda i: scores[i], 
            reverse=True
        )[:top_k]
        
        return [(self.table_names[i], scores[i]) for i in top_indices]


def search_relevant_tables_hybrid_v2(
    query: str,
    profile: str,
    top_k: int = 10,
    bm25_weight: float = 0.3,
    vector_weight: float = 0.7,
    client: Optional[str] = None,
    env: Optional[str] = None,
) -> list[TableMatch]:
    """
    Hybrid search with weighted BM25 + vector scores.
    """
    # BM25 search
    bm25_results = bm25_index.search_bm25(query, top_k=top_k * 2)
    bm25_scores = {name: score for name, score in bm25_results}
    
    # Normalize BM25 scores to 0-1 range
    max_bm25 = max(bm25_scores.values()) if bm25_scores else 1
    bm25_scores = {k: v / max_bm25 for k, v in bm25_scores.items()}
    
    # Vector search
    vector_results = search_relevant_tables(query, profile, top_k=top_k * 2, client=client, env=env)
    vector_scores = {m.table_name: m.score for m in vector_results}
    
    # Combine scores
    all_tables = set(bm25_scores.keys()) | set(vector_scores.keys())
    combined = []
    
    for table in all_tables:
        bm25_s = bm25_scores.get(table, 0)
        vector_s = vector_scores.get(table, 0)
        combined_score = bm25_weight * bm25_s + vector_weight * vector_s
        
        # Get metadata from vector results
        match = next((m for m in vector_results if m.table_name == table), None)
        combined.append(TableMatch(
            table_name=table,
            description=match.description if match else "",
            columns=match.columns if match else {},
            score=combined_score
        ))
    
    # Sort by combined score
    combined.sort(key=lambda m: m.score, reverse=True)
    return combined[:top_k]
```

## Implementation Plan

### Step 1: Add Keyword Boost (Phase 1)

**Files to modify:**
- `apps/db-meta/dbmeta_app/vector_db/milvus.py`
  - Add `get_keyword_matched_tables()`
  - Add `get_all_table_names()` helper
  - Modify `search_relevant_tables()` to use hybrid approach

**Effort:** ~1 hour

### Step 2: Add Tests

**Files to create:**
- `apps/db-meta/tests/test_hybrid_search.py`
  - Test keyword matching: "iceberg table" → `iceberg.radius.wifi_qm_v2`
  - Test partial matches: "wifi hotspots" → `wifi_hotspots`, `wifi_hotspots_history`
  - Test semantic fallback: vague queries still work

**Effort:** ~30 minutes

### Step 3: Add BM25 Integration (Phase 2)

**Files to modify:**
- `apps/db-meta/pyproject.toml` - Add `rank-bm25` dependency
- `apps/db-meta/dbmeta_app/vector_db/milvus.py` - Add BM25 index and hybrid scoring
- `apps/db-meta/dbmeta_app/etl/load.py` - Build BM25 index during ETL

**Effort:** ~2 hours

### Step 4: Add Configuration

**Files to modify:**
- `apps/db-meta/dbmeta_app/config.py`
  - Add `search_bm25_weight: float = 0.3`
  - Add `search_vector_weight: float = 0.7`
  - Add `search_keyword_boost: bool = True`

**Effort:** ~30 minutes

## Test Cases

| Query | Expected Match | Why |
|-------|---------------|-----|
| "iceberg table" | `iceberg.radius.wifi_qm_v2` | Keyword "iceberg" in table name |
| "wifi hotspots" | `wifi_hotspots`, `wifi_hotspots_history` | Keyword "wifi", "hotspots" |
| "radius data" | `iceberg.radius.wifi_qm_v2` | Keyword "radius" in schema |
| "show me subscriber usage" | `subs`, `cdr_agg_day` | Semantic match |
| "list all boosted hexes" | `boosted_hexes` | Both keyword and semantic |

## Success Criteria

1. Query "iceberg table" returns `iceberg.radius.wifi_qm_v2` in top 10
2. No regression on existing semantic queries
3. Plan `columns_referenced` matches actual table schema
4. No hallucinated column names in generated SQL

## Rollback Plan

Feature flag to disable hybrid search:
```python
if settings.search_hybrid_enabled:
    return search_relevant_tables_hybrid(...)
else:
    return search_relevant_tables(...)  # Original behavior
```

## Related Documents

- `docs/plans/phase2-granular-schema-exploration.md` - Schema retrieval improvements
- `docs/future/db-meta-v2-architecture.md` - Overall db-meta vision
