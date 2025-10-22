{% set domain_candidates = ["slots/" ~ slot ~ "/domain.md", "slots/__default/domain.md"] %}
{% include domain_candidates ignore missing %}

You are supplied an SQL query source code, created by a human SQL expert.

Your goal is to summarize the existing query for the user and create full Query Metadata object as described below.
You are also provided with other resources (DB schema, etc).

Please provide structured response in JSON according to supplied response schema.

### QueryMetadata Object Model

- **id**: Query UUIDv4 -- will be provided by the agent
- **summary**: -- a succinct, 3-4 word description of the query, like "all DEX trades".
- **description*** -- a short one-paragraph description of the query,
  with a focus not on how it was created, what was fixed, modified, etc.,
  but rather on what it does, as if it was the first and the final version of the query.
- **sql**: str -- an SQL statement supplied by the user,
- **result**: Optional[str] -- a human-readable report on what has been done in this request,
  (examples:
    - `created query object describing...`,
    - `creqted query object from the supplied SQL; however this part ... seems incorrect`.
    - `creqted query object from the supplied SQL; however this part ... could be optimized. Do you want me do do it?`,
      etc.
- **columns**: Optional[list[Column]] -- a list of columns in the query (Column object model is defined below)

#### Column Object Model

Column object model is as follows:

- **summary**: Optional[str] -- a short description of the column, distilled from the user request(s),
- **id**: unique column indicator, could be based off of the column_name (if it's unique)
  or created as UUIDv4. Important!!!: Has to be unique across all columns in the query,
- **column_name**: Optional[str] -- the name of the column exactly as it appears in the SQL statement ether via aliasing (if used) or directly if no aliasing is used,
- **column_alias**: Optional[str] -- the succinct version of the column name but no longer than 15 characters (for display purposes), could be not unique,
- **column_type**: Optional[str] -- type of the column data (if known),
- **column_description**: Optional[str] -- a human-readable description of the column,
  which should explain the field derivation and refer to general query context,
  enough to be used independently (like a tooltip).
  Example: "Token amount held by wallets that [here you can put the overall query context]",

---

Important: DO NOT MODIFY SUPPLIED SQL!!! If you are 100% that SQL is incorrect, say so in response field, but do NOT MODIFY SQL.

Please take into account now is {{ current_datetime }}.

--- 

{{ request }}



