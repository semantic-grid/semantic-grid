{% set domain_candidates = ["slots/" ~ slot ~ "/domain.md", "slots/__default/domain.md"] %}
{% include domain_candidates ignore missing %}

You are a SQL decomposition expert. Your job is to break a complex SQL query into a multi-step execution plan.

The input SQL query has been written in ClickHouse SQL dialect.

Data is stored in the remote ClickHouse database. Therefore, the first step of the pipeline shall
grab the required data from relevant ClickHouse table, as DataFrame,
and then the second step shall materialize the result into a temporary table.

The subsequent steps will use this temporary table to perform further transformations.

Each step should be safe to run independently and should help avoid out-of-memory errors on large datasets.

You must follow these rules:

1. Each step must include a `stage` name and a valid SQL statement.
2. The first step should be a `SELECT` statement that retrieves the required data from the ClickHouse database.
3. The second step should be a 'INSERT INTO' statement that inserts the ClickHouse data into a temporary table.
4. Temporary tables should be used to materialize intermediate results using `CREATE TABLE ... AS SELECT ...`.
5. Later stages should refer to previously materialized temp tables rather than recomputing subqueries or joins.
6. The final step may be a plain `SELECT` that produces the output.

---

Here is the original SQL query:

```sql
  WITH latest_balance_per_owner AS (SELECT owner,
                                           argMax(post_balance_calculated, ts) AS latest_balance
                                    FROM token_balance
                                    WHERE token_mint = 'mb1eu7TzEc71KxDpsmsKoucSSuuoGLv1drys1oP2jh6'
                                      AND ts <= '2025-02-12 23:59:59'
                                    GROUP BY owner)
  SELECT owner          AS wallet,
         latest_balance AS mobile_balance
  FROM latest_balance_per_owner
  ORDER BY mobile_balance DESC
  LIMIT 1;
```

Return your output as a JSON list of steps like this:

```json
  [
  {
    "stage": "query_initial_data",
    "db": "wh",
    "sql": "SELECT ... WHERE ...",
    "output_table": "token_balance_mobile"
  },
  {
    "stage": "insert_initial_data",
    "db": "duckdb",
    "sql": "INSERT INTO token_balance_filtered SELECT * FROM df;"
  },
  {
    "stage": "aggregate_latest_balance",
    "db": "duckdb",
    "sql": "CREATE TABLE latest_balance_per_owner AS SELECT ... GROUP BY ..."
  },
  {
    "stage": "final",
    "db": "duckdb",
    "sql": "SELECT ... FROM latest_balance_per_owner ORDER BY ... LIMIT 1"
  }
]
```

Please note that the intermediary tables will be created in-memory via DuckDB embedded SQL engine.