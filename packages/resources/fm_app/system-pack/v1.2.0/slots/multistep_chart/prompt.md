{% set domain_candidates = ["slots/" ~ slot ~ "/domain.md", "slots/__default/domain.md"] %}
{% include domain_candidates ignore missing %}

---

Given the following data, generate structured response
to be used by ***plotly dash** python module.

Response should be returned as follows:

- ***labels***: list of series names,
  like `['series_a','series_b']`
- ***rows***: list of lists of data,
  like `[['series_a_0','series_a_1',...],[series_b_0,...]]`
- ***intro***: any generated text preceding the CSV data block, including how you understood the user question
  and what assumptions have been made,
- ***outro***: any generated text following the CSV data block, including disclaimers, notes, other comments.
  At the end of ***outro*** section please suggest to user possible relevant follow-on questions, starting with:
  `Do you want me to...`, `Would you like to...` or similar.

---

Use the following data in CSV format: {{ chart_data }}

---

Please take into account that current time is {{ current_datetime }}.

