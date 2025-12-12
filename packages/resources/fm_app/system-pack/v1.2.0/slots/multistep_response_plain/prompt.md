{% set domain_candidates = ["slots/" ~ slot ~ "/domain.md", "slots/__default/domain.md"] %}
{% include domain_candidates ignore missing %}

Here's the data you've requested on the previous step, in CSV format: {{ response_data }}

---

Please take into account that current time is {{ current_datetime }}.

