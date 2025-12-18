{% set domain_candidates = ["slots/" ~ slot ~ "/domain.md", "slots/__default/domain.md"] %}
{% include domain_candidates ignore missing %}

Please generate SQL request (wrap it into ```sql```). Please provide assumptions as SQL comments.

Please return ready to execute request - all additional text has to be valid ClickHouse SQL comments.

Please always limit the number of rows (no more than 100 rows max).

---

Please take into account now is {{ current_datetime }}.