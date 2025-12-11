{% set domain_candidates = ["slots/" ~ slot ~ "/domain.md", "slots/__default/domain.md"] %}
{% include domain_candidates ignore missing %}

---

Here's the data you've requested on the previous step, in CSV format: {{ response_data }}

Please use the data to generate structured response.

Response should be formatted as follows:

- ***labels***: list of series names,
  like `['series_a','series_b']`
- ***rows***: list of lists of data,
  like `[['series_a_0','series_a_1',...],[series_b_0,...]]`
- ***intro***: any generated text preceding the CSV data block,
  including how you understood the user question
  and what assumptions have been made,
- ***outro***: any generated text following the CSV data block,
  including disclaimers, notes, other comments.

At the end of ***outro*** section please suggest to user possible relevant follow-on questions, starting with:
`Do you want me to...`, `Would you like to...` or similar.

Instead of formatting the supplied csv data, insert CSV-formatted data (```csv ...```)
in the relevant part of your response.

---

Here are additional Solana tokens address-to-name mappings for the results; if matched, please include human-readable
names
in parentheses after the address, as references: {{ db_ref_prompt_items }}

---

Please take into account that current time is {{ current_datetime }}.


