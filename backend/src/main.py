from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from src.core.config import get_settings

from src.api.routers import auth, users, providers, agents, projects, chats, tasks, logs, skills, mcp_servers, tools, personas, git_credentials, git_proxy, orgs, seeds, issues, integrations, usage, model_profiles, provider_types, memories, memory_notes as memory_notes_router, teams, schedules as schedules_router, board as board_router, knowledge_bases as knowledge_bases_router
from src.api.routers.agents import public_router as agents_public_router
from src.api.routers import ws as ws_router
from src.api.routers import user_api_keys, notifications, user_backup
from src.api.routers import webhook_rules as webhook_rules_router
from src.api.routers import custom_webhook as custom_webhook_router
from src.api.routers import agent_messages as agent_messages_router
from src.api.routers import proposals as proposals_router
from src.api.routers import plans as plans_router
from src.api.routers import totp as totp_router
from src.api.routers import search as search_router
from src.api.routers import marketplace as marketplace_router
from src.api.routers import system as system_router
from src.api.routers import tool_envs as tool_envs_router
from src.api.routers import env_vars as env_vars_router
from src.api.routers import cli_hooks as cli_hooks_router
from src.api.routers import oauth as oauth_router
from src.api.routers import device as device_router
from src.api.routers import platform_backup as platform_backup_router
from src.api.routers import goals as goals_router
from src.api.routers import approvals as approvals_router
from src.api.routers import outcomes as outcomes_router
from src.api.routers import org_roles as org_roles_router
from src.integrations import github, gitlab

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Unique identifier for this container boot — shared across both uvicorn workers
# because they share the same parent process (PID 1) whose start time is stable.
try:
    with open("/proc/1/stat") as _f:
        _CONTAINER_EPOCH = _f.read().split()[21]
except Exception:
    import uuid as _uuid
    _CONTAINER_EPOCH = _uuid.uuid4().hex


@asynccontextmanager
async def lifespan(app: FastAPI):
    from src.core.lifespan.database import startup_database
    from src.core.lifespan.redis_warmup import startup_redis
    from src.core.lifespan.seeds import startup_seeds
    from src.core.lifespan.scheduler import startup_scheduler
    from src.core.lifespan.telegram import startup_telegram
    from src.core.lifespan.shutdown import shutdown_all

    settings = get_settings()
    logger.info(f"Starting Nexora ({settings.environment})")

    await startup_database()
    await startup_redis()
    await startup_seeds()
    await startup_scheduler()
    await startup_telegram(_CONTAINER_EPOCH)
    yield
    await shutdown_all()


def create_app() -> FastAPI:
    settings = get_settings()

    _dev = settings.environment != "production"
    app = FastAPI(
        title="Nexora API",
        version="0.1.0",
        description="AI-powered agentic platform for development teams",
        docs_url="/api/docs" if _dev else None,
        redoc_url="/api/redoc" if _dev else None,
        openapi_url="/api/openapi.json" if _dev else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
    )

    # API routers
    prefix = "/api"
    app.include_router(auth.router, prefix=prefix)
    app.include_router(totp_router.router, prefix=prefix)
    app.include_router(search_router.router, prefix=prefix)
    app.include_router(marketplace_router.router, prefix=prefix)
    app.include_router(users.router, prefix=prefix)
    app.include_router(user_api_keys.router, prefix=prefix)
    app.include_router(user_backup.router, prefix=prefix)
    app.include_router(notifications.router, prefix=prefix)
    app.include_router(providers.router, prefix=prefix)
    app.include_router(agents.router, prefix=prefix)
    app.include_router(agents_public_router, prefix=prefix)
    app.include_router(projects.router, prefix=prefix)
    app.include_router(chats.router, prefix=prefix)
    app.include_router(tasks.router, prefix=prefix)
    app.include_router(logs.router, prefix=prefix)
    app.include_router(skills.router, prefix=prefix)
    app.include_router(mcp_servers.router, prefix=prefix)
    app.include_router(tools.router, prefix=prefix)
    app.include_router(personas.router, prefix=prefix)
    app.include_router(git_credentials.router, prefix=prefix)
    app.include_router(git_proxy.router, prefix=prefix)
    app.include_router(orgs.router, prefix=prefix)
    app.include_router(seeds.router, prefix=prefix)
    app.include_router(issues.router, prefix=prefix)
    app.include_router(integrations.router, prefix=prefix)
    app.include_router(usage.router, prefix=prefix)
    app.include_router(model_profiles.router, prefix=prefix)
    app.include_router(provider_types.router, prefix=prefix)
    app.include_router(memories.router)
    app.include_router(memory_notes_router.router)
    app.include_router(teams.router, prefix=prefix)
    app.include_router(schedules_router.router, prefix=prefix)
    app.include_router(board_router.router, prefix=prefix)
    app.include_router(webhook_rules_router.router, prefix=prefix)
    app.include_router(custom_webhook_router.router, prefix=prefix)
    app.include_router(agent_messages_router.router, prefix=prefix)
    app.include_router(proposals_router.router, prefix=prefix)
    app.include_router(plans_router.router, prefix=prefix)
    app.include_router(knowledge_bases_router.router, prefix=prefix)
    app.include_router(system_router.router, prefix=prefix)
    app.include_router(tool_envs_router.router, prefix=prefix)
    app.include_router(env_vars_router.router, prefix=prefix)
    app.include_router(cli_hooks_router.router, prefix=prefix)
    app.include_router(oauth_router.router, prefix=prefix)
    app.include_router(device_router.router, prefix=prefix)
    app.include_router(platform_backup_router.router, prefix=prefix)
    app.include_router(goals_router.router, prefix=prefix)
    app.include_router(approvals_router.router, prefix=prefix)
    app.include_router(outcomes_router.router, prefix=prefix)
    app.include_router(org_roles_router.router, prefix=prefix)

    # WebSocket
    app.include_router(ws_router.router)

    # Integrations
    app.include_router(github.router, prefix=prefix)
    app.include_router(gitlab.router, prefix=prefix)

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "0.1.0"}

    return app


app = create_app()
