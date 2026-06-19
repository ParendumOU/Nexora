# JSON Validate

Validate JSON string. Optionally check against JSON Schema.

## Parameters
- `json` (string, required): JSON string to validate
- `schema` (object, optional): JSON Schema to validate against

## Returns
```json
{ "valid": true, "errors": [] }
```

On failure:
```json
{ "valid": false, "errors": ["$.name: required property missing"] }
```
