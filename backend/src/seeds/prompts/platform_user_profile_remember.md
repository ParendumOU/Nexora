Use `remember_user` to persist genuinely new facts about this user — role, location/timezone, preferences, ongoing projects, important context. Skip greetings, small talk, and anything with no new information.

Patch ONE fact at a time with a stable `key` (e.g. `role`, `timezone`, `current_project`) and its `value`:
- `op="upsert"` to add or replace a single fact — this NEVER erases the user's other facts.
- `op="append"` to extend an existing fact's value.
- `op="remove"` to forget a fact that is no longer true.

Reuse existing keys when updating the same attribute so values stay current instead of duplicating. Put general free-text notes under the `freeform` key. Do not dump the whole profile in one call — record discrete facts.
