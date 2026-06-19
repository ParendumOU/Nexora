# Agent System

## Agent Types

| Type | Role | Default Skills |
|------|------|---------------|
| `project_manager` | Decomposes tasks, delegates to sub-agents, aggregates results | task_decompose, agent_spawn, summarize |
| `developer` | Writes and runs code in Docker sandbox | bash, write_file, read_file, git, web_search |
| `qa_engineer` | Tests code, reviews PRs, writes test cases | bash, read_file, web_search |
| `researcher` | Web research, reads docs, summarizes | web_search, read_url, summarize |
| `designer` | UI mockups, design feedback | web_search, image_generate |
| `devops` | CI/CD, infrastructure, deployment scripts | bash, write_file, git |
| `custom` | User-defined role | User-selected skills |

## Agent Configuration (Soul)

Each agent has a "soul" — a structured configuration:

```json
{
  "name": "Alex",
  "type": "developer",
  "soul": {
    "personality": "methodical, detail-oriented, prefers TypeScript",
    "expertise": ["React", "FastAPI", "PostgreSQL"],
    "communication_style": "concise, uses code examples"
  },
  "system_prompt": "You are Alex, a senior full-stack developer...",
  "skills": ["bash", "write_file", "read_file", "git", "web_search"],
  "model_pref": "claude",       // preferred provider
  "temperature": 0.3,
  "max_tokens": 8192,
  "flow_config": {}              // React Flow node positions (visual editor)
}
```

## Skills (Tool Definitions)

Skills are assignable capabilities backed by LangChain tools:

| Skill | Description | Requires |
|-------|-------------|---------|
| `bash` | Execute shell commands in Docker sandbox | sandbox |
| `write_file` | Create/update files in workspace | sandbox |
| `read_file` | Read files from workspace | sandbox |
| `git` | Clone, commit, push to repos | sandbox + git creds |
| `web_search` | Brave/DuckDuckGo web search | API key or scraping |
| `read_url` | Fetch and parse a URL | network |
| `github_read` | Read GitHub repos, issues, PRs | GitHub token |
| `github_write` | Create PRs, comments, branches | GitHub token |
| `gitlab_read` | Read GitLab repos, MRs, issues | GitLab token |
| `gitlab_write` | Create MRs, comments, branches | GitLab token |
| `image_generate` | Generate images via provider | provider support |
| `summarize` | Summarize long content | LLM |
| `agent_spawn` | Create and delegate to a sub-agent | PM only |
| `task_decompose` | Break task into subtasks | PM only |

## Project Manager Agent

The PM Agent is the backbone of Project functionality:

```
User Message → PM Agent
  │
  ├─ Analyze task complexity
  │    ├─ Simple (1 agent, no delegation): respond directly  
  │    └─ Complex (multiple agents needed):
  │         ├─ Decompose into subtasks
  │         ├─ Spawn sub-agents as needed
  │         │    ├─ Developer: "Implement feature X"
  │         │    ├─ QA: "Write tests for X"
  │         │    └─ Researcher: "Find docs for library Y"
  │         ├─ Monitor progress (parallel where possible)
  │         └─ Aggregate + summarize results
  │
  └─ Report back to User in real-time
```

### PM Rate-Limit Awareness

Before spawning a sub-agent, the PM checks the provider chain health:
```python
available_providers = await router.get_available_providers(chain_id)
if len(available_providers) == 0:
    # Queue the sub-agent task instead of spawning immediately
    await task_queue.enqueue(subtask, retry_after=60)
else:
    await agent_pool.spawn(subtask, providers=available_providers)
```

## Visual Agent Builder (Frontend)

The Agent Builder uses React Flow for visual configuration:

- **Nodes**: Agent cards showing name, type, soul preview, skill badges
- **Edges**: Delegation relationships (PM → Developer, PM → QA)
- **Sidebar**: Configuration panel for selected agent
- **Canvas**: Drag-and-drop arrangement
- **Save**: Serializes flow_config JSON + agent configs to backend

### Node Types
- **Entry node**: User input (fixed, cannot delete)
- **Agent node**: Configurable agent (click to edit soul + skills)
- **Output node**: Final response (fixed, cannot delete)
- **Tool node**: Skill visualization (decorative, shows what each agent can do)

## Agent Memory

Each agent has access to:
1. **Thread memory**: Full conversation history within the current chat
2. **Project memory**: Persistent facts extracted from project conversations
3. **User context**: Who the user is, their preferences, tech stack
4. **Workspace files**: Files written to the project's Docker workspace

Memory is extracted after each significant interaction using a lightweight LLM pass.
