# PagerDuty

Manage PagerDuty incidents and on-call schedules via the REST API v2.

## Configuration

```
PAGERDUTY_API_TOKEN=your-api-token
```

Create a token at PagerDuty → User menu → My Profile → User Settings → Create API User Token.

## Actions

### list_incidents
List active (or all) incidents.
```json
{"action": "list_incidents", "status": "triggered", "limit": 20}
```
`status`: `triggered`, `acknowledged`, `resolved`, or omit for all open.

### get_incident
Get full incident detail.
```json
{"action": "get_incident", "incident_id": "P123ABC"}
```

### create_incident
Create a new incident.
```json
{"action": "create_incident", "title": "Database latency spike", "service_id": "PXXXXXX", "urgency": "high"}
```
`urgency`: `high` (default) or `low`.

### acknowledge_incident
Acknowledge an incident (requires `from_email`).
```json
{"action": "acknowledge_incident", "incident_id": "P123ABC", "from_email": "oncall@example.com"}
```

### resolve_incident
Resolve an incident.
```json
{"action": "resolve_incident", "incident_id": "P123ABC", "from_email": "oncall@example.com"}
```

### add_note
Add a note to an incident.
```json
{"action": "add_note", "incident_id": "P123ABC", "content": "Rolled back deploy, monitoring.", "from_email": "oncall@example.com"}
```

### list_schedules
List on-call schedules.
```json
{"action": "list_schedules", "query": "primary"}
```

### get_oncall
Get the current on-call user for a schedule.
```json
{"action": "get_oncall", "schedule_id": "PXXXXXX"}
```
