{% set domain_candidates = ["slots/" ~ slot ~ "/domain.md", "slots/__default/domain.md"] %}
{% include domain_candidates ignore missing %}

Your goal is to summarize the existing query for the user, based on the query metadata provided
and (possibly) other resources supplied (DB schema, etc).

Please provide structured response in JSON according to supplied response schema.

Set **request_type** field to `linked_query`.

Set **summary** to a succinct, 3-4 word description of the query, like "all DEX trades".

Set **intent** field to a detailed description of what the query does, explaining data filtering, aggregations and calculations.

Important: use only human-readable terms, do not use any internal column names or IDs.

Don't set any other fields or include any other information.

Please take into account now is {{ current_datetime }}.

---

{{ intent_hint }}

{{ query_metadata }}
