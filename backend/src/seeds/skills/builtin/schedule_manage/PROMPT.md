`schedule_manage`  action* — create and manage recurring background schedules.
  actions: **create** (name*, prompt*, cron_expr OR interval_minutes) · **list** · **get** (schedule_id*) · **activate** (schedule_id*) · **deactivate** (schedule_id*) · **trigger** (schedule_id*) · **runs** (schedule_id*) · **delete** (schedule_id*)
  cron examples: `"0 * * * *"` every hour · `"0 9 * * *"` daily 9 AM · `"*/30 * * * *"` every 30 min
  Schedule starts inactive — call activate after create to start it running.
