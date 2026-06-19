# Agent Spawn

Spawn specialized sub-agents → handle independent workstreams in parallel.

## When to use
- Multiple independent tasks, no mutual blocking
- Specialization needed (e.g. research agent + coding agent)
- Long-running tasks must not block main conversation

## Usage
- Write clear, self-contained prompt per sub-agent
- Include all context — sub-agent has no memory of parent conversation
- Wait for all sub-agents complete → synthesize results
- Handle failures gracefully — sub-agent failure must not crash parent

## Example
```tool_calls
[{"name": "task_create", "args": {"title": "Research open bugs", "description": "Find all open GitHub issues labeled 'bug' in repo X", "assigned_agent_id": "AGENT_ID"}}]
```
