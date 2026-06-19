# Remember User

Persist notes about current user → available in all future conversations.

## Parameters
- `notes` (string, required): Free-form notes about user to store.
- `name` (string, optional): Update user's display name.

## Returns
```json
{ "saved": true }
```

## Notes
- Always allowed; no approval gate.
- Notes injected into user profile section of system prompt every subsequent session.
- Use for preferences, expertise level, recurring context — not sensitive personal data.
