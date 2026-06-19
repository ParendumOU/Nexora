# Platform Management

## Services

| Service | Filter | Role |
|---|---|---|
| `backend` | `name=backend` | FastAPI API |
| `frontend` | `name=frontend` | Next.js UI |
| `nginx` | `name=nginx` | Reverse proxy |
| `postgres` | `name=postgres` | PostgreSQL |
| `redis` | `name=redis` | Cache/pub-sub |

## File paths (backend container)

| Path | Contents |
|---|---|
| `/app` | Backend source root |
| `/app/src/api/routers/` | Route handlers |
| `/app/src/models/` | SQLAlchemy models |
| `/app/src/skills_data/` | Skill seeds |
| `/app/src/main.py` | Entry point |
| `/workspace-root/AgenticChats/frontend/` | Frontend root |
| `/workspace-root/AgenticChats/frontend/src/app/` | Next.js routes |
| `/workspace-root/AgenticChats/frontend/src/components/` | React components |
| `/workspace-root/AgenticChats/frontend/src/lib/api.ts` | API client |

`/workspace-root` = volume mount of parent dir.

## Restart services

Docker socket at `/var/run/docker.sock`. Use `shell_run`.

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# frontend — safe
docker ps --filter "name=frontend" --format "{{.Names}}" | xargs docker restart

# nginx — brief drop
docker ps --filter "name=nginx" --format "{{.Names}}" | xargs docker restart

# backend — drops all WebSocket sessions. Confirm with user first.
docker ps --filter "name=backend" --format "{{.Names}}" | xargs docker restart
```

## Hot-reload

- **Backend (dev)**: Uvicorn `--reload`. Any `.py` save under `/app/src/` → auto-reload ~1s.
- **Frontend (dev)**: Next.js HMR. Any `.tsx`/`.ts`/`.css` save → instant refresh.
- **Production**: Restart required after edits.

## Logs

```bash
docker ps --filter "name=backend" --format "{{.Names}}" | xargs -I{} docker logs --tail 100 {}
docker ps --filter "name=frontend" --format "{{.Names}}" | xargs -I{} docker logs --tail 100 {}
docker ps --filter "name=nginx" --format "{{.Names}}" | xargs -I{} docker logs --tail 20 --follow {}
```

## DB inspection

```bash
PGPASSWORD=$POSTGRES_PASSWORD psql -h postgres -U $POSTGRES_USER -d $POSTGRES_DB \
  -c "SELECT id, name, slug FROM organizations ORDER BY created_at;"
```

## Editing rules

- `file_read` before editing.
- Edit only `/app/src/` or `/workspace-root/AgenticChats/frontend/src/`.
- Targeted edits only.
- After backend edit: state if hot-reload suffices or restart needed.
- After frontend edit: state if HMR applies or rebuild needed.
- Never edit migrations or `__pycache__`.
