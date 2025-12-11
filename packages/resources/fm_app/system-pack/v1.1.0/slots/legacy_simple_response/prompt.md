{% set domain_candidates = ["slots/" ~ slot ~ "/domain.md", "slots/__default/domain.md"] %}
{% include domain_candidates ignore missing %}

Please generate final response to original user input.

If there is no data needed please prepare polite response that we have not necessary data.

---

Please take into account now is {{ current_datetime }}.