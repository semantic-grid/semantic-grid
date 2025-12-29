# Milvus for Semantic Table Selection

## Overview

This document outlines a proposed architecture for using Milvus vector search to enable semantic table selection in the query generation pipeline. This would reduce token usage, improve response times, and enhance query quality by intelligently selecting relevant tables based on user intent.

## Current State

### Existing Milvus Usage

Milvus is currently used in db-meta for semantic search over query examples:

**Location**: `apps/db-meta/dbmeta_app/prompt_items/db_struct.py`

```python
def get_relevant_examples(
    user_query: str,
    collection_name: str = "query_examples",
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """Retrieve semantically similar query examples from Milvus."""
    
    # Generate embedding for user query
    query_embedding = get_embedding(user_query)
    
    # Search Milvus collection
    search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}}
    results = milvus_client.search(
        collection_name=collection_name,
        data=[query_embedding],
        anns_field="embedding",
        search_params=search_params,
        limit=top_k,
        output_fields=["sql", "description", "tables"],
    )
    
    return results
```

**Benefits Observed**:
- Provides contextually relevant SQL examples
- Reduces need for exhaustive example lists
- Improves LLM understanding of query patterns

## Proposed Architecture: Semantic Table Selection

### Problem Statement

Current approach includes all available tables in the prompt, leading to:
- **High token usage**: 50-100K tokens for large schemas
- **Slower LLM responses**: More context to process
- **Reduced quality**: Relevant tables buried in noise
- **Cost inefficiency**: Paying for unused schema descriptions

### Proposed Solution

Use Milvus to semantically index table metadata and select only relevant tables based on user query.

### Architecture Components

#### 1. Table Metadata Indexing

**Collection Schema**:
```python
table_metadata_schema = {
    "collection_name": "table_metadata",
    "fields": [
        {"name": "table_id", "dtype": DataType.VARCHAR, "max_length": 255, "is_primary": True},
        {"name": "embedding", "dtype": DataType.FLOAT_VECTOR, "dim": 1536},  # OpenAI ada-002
        {"name": "catalog", "dtype": DataType.VARCHAR, "max_length": 100},
        {"name": "schema", "dtype": DataType.VARCHAR, "max_length": 100},
        {"name": "table_name", "dtype": DataType.VARCHAR, "max_length": 100},
        {"name": "description", "dtype": DataType.VARCHAR, "max_length": 2000},
        {"name": "column_names", "dtype": DataType.JSON},  # List of column names
        {"name": "key_concepts", "dtype": DataType.JSON},  # Extracted semantic concepts
        {"name": "row_count", "dtype": DataType.INT64},
        {"name": "last_updated", "dtype": DataType.INT64},  # Unix timestamp
    ]
}
```

**Embedding Strategy**:
```python
def create_table_embedding_text(table_metadata: dict) -> str:
    """
    Create rich text representation for embedding.
    Combines multiple signals for better semantic matching.
    """
    parts = []
    
    # Table identification
    parts.append(f"Table: {table_metadata['fully_qualified_name']}")
    
    # Description from YAML
    if table_metadata.get('description'):
        parts.append(f"Description: {table_metadata['description']}")
    
    # Column information
    if table_metadata.get('columns'):
        column_desc = ", ".join([
            f"{col['name']} ({col.get('type', 'unknown')})"
            for col in table_metadata['columns']
        ])
        parts.append(f"Columns: {column_desc}")
    
    # Key concepts from YAML
    if table_metadata.get('key_concepts'):
        parts.append(f"Key concepts: {', '.join(table_metadata['key_concepts'])}")
    
    # Example use cases
    if table_metadata.get('use_cases'):
        parts.append(f"Use cases: {'; '.join(table_metadata['use_cases'])}")
    
    return "\n".join(parts)
```

#### 2. Query-Time Table Selection

**Implementation in `db_struct.py`**:
```python
def select_relevant_tables(
    user_query: str,
    profile: str,
    max_tables: int = 10,
    confidence_threshold: float = 0.7,
    always_include: list[str] | None = None,
) -> list[str]:
    """
    Select relevant tables for a user query using semantic search.
    
    Args:
        user_query: Natural language user request
        profile: Database profile (e.g., 'wh_v2')
        max_tables: Maximum tables to return
        confidence_threshold: Minimum similarity score (0-1)
        always_include: Tables to always include (e.g., frequently used tables)
    
    Returns:
        List of fully-qualified table names
    """
    # Generate embedding for user query
    query_embedding = get_embedding(user_query)
    
    # Search Milvus for relevant tables
    search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}}
    results = milvus_client.search(
        collection_name=f"table_metadata_{profile}",
        data=[query_embedding],
        anns_field="embedding",
        search_params=search_params,
        limit=max_tables * 2,  # Get more candidates for filtering
        output_fields=["table_id", "catalog", "schema", "table_name", "description"],
    )
    
    # Filter by confidence threshold
    selected_tables = []
    for hit in results[0]:
        if hit.distance >= confidence_threshold:
            table_fqn = f"{hit.entity.get('catalog')}.{hit.entity.get('schema')}.{hit.entity.get('table_name')}"
            selected_tables.append(table_fqn)
        
        if len(selected_tables) >= max_tables:
            break
    
    # Always include specified tables
    if always_include:
        for table in always_include:
            if table not in selected_tables:
                selected_tables.append(table)
    
    # Fallback: if no tables meet threshold, return top 5
    if not selected_tables:
        selected_tables = [
            f"{hit.entity.get('catalog')}.{hit.entity.get('schema')}.{hit.entity.get('table_name')}"
            for hit in results[0][:5]
        ]
    
    return selected_tables
```

**Integration with Prompt Assembly**:
```python
def get_prompt_bundle(
    profile: str,
    user_query: str | None = None,
    use_semantic_selection: bool = True,
    **kwargs,
) -> dict:
    """
    Get prompt bundle with optional semantic table selection.
    """
    if use_semantic_selection and user_query:
        # Use Milvus to select relevant tables
        relevant_tables = select_relevant_tables(
            user_query=user_query,
            profile=profile,
            max_tables=10,
            confidence_threshold=0.7,
        )
        
        # Build schema prompt for selected tables only
        schema_prompt = _build_schema_prompt(
            profile=profile,
            include_tables=relevant_tables,
        )
    else:
        # Fallback to all tables
        schema_prompt = _build_schema_prompt(profile=profile)
    
    return {
        "schema": schema_prompt,
        "examples": get_relevant_examples(user_query) if user_query else [],
        "selected_tables": relevant_tables if use_semantic_selection else None,
    }
```

#### 3. Indexing Pipeline

**Initial Population**:
```python
async def index_all_tables(profile: str):
    """Index all tables from a database profile into Milvus."""
    
    # Get all table metadata
    all_tables = await introspect_database_schema(profile)
    
    # Load YAML descriptions
    yaml_metadata = load_schema_descriptions(profile)
    
    # Merge and enrich
    enriched_tables = []
    for table in all_tables:
        fqn = f"{table['catalog']}.{table['schema']}.{table['name']}"
        yaml_meta = yaml_metadata.get(fqn, {})
        
        enriched = {
            **table,
            'description': yaml_meta.get('description', ''),
            'key_concepts': yaml_meta.get('key_concepts', []),
            'use_cases': yaml_meta.get('use_cases', []),
        }
        enriched_tables.append(enriched)
    
    # Create embeddings
    embeddings_batch = []
    entities_batch = []
    
    for table in enriched_tables:
        embedding_text = create_table_embedding_text(table)
        embedding = get_embedding(embedding_text)
        
        entity = {
            'table_id': f"{table['catalog']}.{table['schema']}.{table['name']}",
            'embedding': embedding,
            'catalog': table['catalog'],
            'schema': table['schema'],
            'table_name': table['name'],
            'description': table['description'][:2000],  # Truncate to max length
            'column_names': [col['name'] for col in table.get('columns', [])],
            'key_concepts': table.get('key_concepts', []),
            'row_count': table.get('row_count', 0),
            'last_updated': int(datetime.now().timestamp()),
        }
        
        embeddings_batch.append(embedding)
        entities_batch.append(entity)
    
    # Insert into Milvus
    collection_name = f"table_metadata_{profile}"
    milvus_client.insert(collection_name=collection_name, data=entities_batch)
    
    logger.info(f"Indexed {len(entities_batch)} tables for profile {profile}")
```

**Incremental Updates**:
```python
async def update_table_metadata(profile: str, table_fqn: str):
    """Update a single table's metadata in Milvus (e.g., after YAML change)."""
    
    # Get fresh metadata
    table_metadata = await get_table_metadata(profile, table_fqn)
    
    # Create embedding
    embedding_text = create_table_embedding_text(table_metadata)
    embedding = get_embedding(embedding_text)
    
    # Update in Milvus
    collection_name = f"table_metadata_{profile}"
    milvus_client.delete(
        collection_name=collection_name,
        filter=f'table_id == "{table_fqn}"'
    )
    milvus_client.insert(
        collection_name=collection_name,
        data=[{
            'table_id': table_fqn,
            'embedding': embedding,
            # ... other fields
        }]
    )
```

## Benefits vs Challenges

### Benefits

| Benefit | Impact | Estimated Improvement |
|---------|--------|----------------------|
| **Token Reduction** | Lower costs, faster responses | 10x reduction (5K tokens vs 50K) |
| **Response Quality** | LLM focuses on relevant context | 20-30% better table selection |
| **Latency** | Faster LLM processing | 2-3x faster for large schemas |
| **Scalability** | Handles 1000+ table databases | Linear vs exponential cost growth |
| **Multi-tenancy** | Client-specific table sets | Easy isolation and customization |

### Challenges

| Challenge | Mitigation Strategy |
|-----------|---------------------|
| **Embedding Quality** | Rich embedding text with descriptions, columns, concepts |
| **Cold Start** | Pre-populate collections on startup, cache embeddings |
| **Multi-table Queries** | Hybrid approach with always-include tables |
| **False Negatives** | Low confidence threshold (0.6-0.7), fallback to top-N |
| **Maintenance** | Automated re-indexing on YAML updates |
| **Cost** | Embedding cost amortized (one-time per table update) |

## Recommended Strategy: Hybrid Approach

### Configuration-Based Selection

```yaml
# In schema_description.yaml
table_selection:
  strategy: hybrid  # Options: semantic, all, whitelist
  
  # Always include these tables (core/frequently used)
  always_include:
    - ct.public.enriched_trades
    - ct.public.enriched_transfers
  
  # Semantic search configuration
  semantic:
    enabled: true
    max_tables: 10
    confidence_threshold: 0.7
  
  # Whitelist override (if specified, ignore semantic)
  whitelist:
    - ct.public.*  # All tables in ct.public schema
```

### Implementation

```python
def get_tables_for_query(
    profile: str,
    user_query: str,
    config: dict,
) -> list[str]:
    """
    Determine which tables to include based on configuration.
    """
    strategy = config.get('table_selection', {}).get('strategy', 'all')
    
    if strategy == 'whitelist':
        # Use explicit whitelist
        return expand_whitelist(config['table_selection']['whitelist'])
    
    elif strategy == 'semantic':
        # Use Milvus semantic search
        semantic_config = config['table_selection']['semantic']
        return select_relevant_tables(
            user_query=user_query,
            profile=profile,
            max_tables=semantic_config['max_tables'],
            confidence_threshold=semantic_config['confidence_threshold'],
            always_include=config['table_selection'].get('always_include', []),
        )
    
    elif strategy == 'hybrid':
        # Combine semantic with always_include
        always_include = config['table_selection'].get('always_include', [])
        semantic_tables = select_relevant_tables(
            user_query=user_query,
            profile=profile,
            max_tables=8,  # Leave room for always_include
            confidence_threshold=0.7,
            always_include=always_include,
        )
        return semantic_tables
    
    else:  # 'all'
        # Return all available tables (current behavior)
        return get_all_tables(profile)
```

## Implementation Roadmap

### Phase 1: Foundation (1-2 weeks)
- [ ] Create Milvus collection schema for table metadata
- [ ] Implement `create_table_embedding_text()` function
- [ ] Build initial indexing pipeline
- [ ] Test embedding quality with sample queries

### Phase 2: Integration (1 week)
- [ ] Integrate `select_relevant_tables()` into `get_prompt_bundle()`
- [ ] Add configuration support in YAML
- [ ] Implement hybrid strategy with always_include
- [ ] Add logging and metrics

### Phase 3: Optimization (1 week)
- [ ] Tune confidence thresholds based on real queries
- [ ] Implement incremental update mechanism
- [ ] Add caching layer for frequent queries
- [ ] Performance testing and benchmarking

### Phase 4: Production (1 week)
- [ ] Automated re-indexing on schema changes
- [ ] Monitoring and alerting
- [ ] Documentation and runbooks
- [ ] Gradual rollout with feature flag

## Metrics to Track

- **Token usage**: Before/after comparison per query
- **Query success rate**: % of queries that generate valid SQL
- **Table selection accuracy**: Manual review of relevance
- **Response latency**: End-to-end query time
- **Milvus query time**: Vector search overhead
- **Cost reduction**: $ saved on LLM API calls

## Future Enhancements

1. **Column-level selection**: Embed individual columns for fine-grained relevance
2. **Query history feedback**: Re-rank based on which tables were actually used
3. **Multi-vector search**: Separate embeddings for table structure vs business meaning
4. **A/B testing framework**: Compare semantic vs traditional approaches
5. **Auto-tuning**: ML model to optimize confidence thresholds

## References

- Milvus documentation: https://milvus.io/docs
- Current implementation: `apps/db-meta/dbmeta_app/prompt_items/db_struct.py:850-900`
- OpenAI embeddings: `text-embedding-ada-002` (1536 dimensions)
- Related: Query example search (already implemented)

---

**Status**: Proposed for future implementation  
**Priority**: Medium (after Redis caching, before advanced query features)  
**Estimated Effort**: 4-5 weeks full implementation  
**Dependencies**: Existing Milvus setup, OpenAI API access
