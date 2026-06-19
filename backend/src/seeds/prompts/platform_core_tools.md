`task_create`  title* | description | assigned_agent_id | parent_id | position | continue_chat_id | model_profile_id
  → `continue_chat_id`: resume existing sub-chat (same agent + related work only; never unrelated tasks)
`task_update`  task_id* | status (pending|in_progress|completed|failed|blocked) | output
`task_delete`  task_id*
`log_entry`    message* | level (debug|info|warn|error) | task_id — progress/outcomes only; never on chitchat
`remember_user` notes* | name — new facts about user (name/role/prefs/projects); not on greetings
`memory_manage` action* (save|read|delete) | scope (agent|project) | content | type | tags | priority | search | limit | memory_id
