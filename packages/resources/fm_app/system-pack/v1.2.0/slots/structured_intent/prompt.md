{% set domain_candidates = ["slots/" ~ slot ~ "/domain.md", "slots/__default/domain.md"] %}
{% include domain_candidates ignore missing %}

{% include "slots/structured_intent/prefix.md" %}

---

At this first step, we need to make sure that we understand the user's request correctly,
and if this request could be answered using general knowledge
or indeed requires us to query the specialized database before responding.

To do that, generate a sufficiently detailed, yet succinct, responses to the following questions
that will help us to decide if we need to generate SQL to query our DB or not.

If some details are missing (like time span, number of records to be returned,
or definitions of terms) define/complete them yourself using best case logic.

Do not make any assumptions about the database structure, type, name of columns etc.
The goal is to evolve this prompt into a brief, detailed statement
that has everything necessary to write an SQL query.

The output will be used as the new prompt to an LLM, so make it brief.
Limit answer just to the distilled and augmented prompt statement.

Don't provide any additional reasoning, bullet points or summaries of improvements.

Please provide structured response in JSON format:

- **user_intent** field, human-readable description of the user's intent, as understood by you,
- **summary** field, a succinct, 3-4 word summary of the user's request,
- **time** field, a moment or time span of the request, if applicable (NULL otherwise),
- **time_confidence** field, a confidence level of the **time** field (0 to 10, 10=highest),
- **domain** field, a multiple choice selection of the following:
  "token", "balance", "transaction", "instruction", "price", "transfer",
- **domain_confidence** field, a confidence level of the **domain** field (0 to 10, 10=highest),
- **named_entities** field, an array of strings representing parts of user request
  which could be relevant to domain, such as names of tokens or exchanges addresses of wallets, etc.
- **named_entities_confidence** field, a confidence level of the **named_entities** field (0 to 10, 10=highest)

If you can answer user's request without
additional data please return the answer in **response_to_user** filed.

If you need any additional data from user please put the question to the **additional_data_request** field
(only if you are completely unclear about the intent or any of the parameters).

Please take into account that current time is {{ current_datetime }}.

---

{% include "slots/structured_intent/suffix.md" %}
