"""schedule_manage executor — agents can create and manage background schedules."""
import logging
from sqlalchemy import select

logger = logging.getLogger(__name__)


async def _get_org_id(agent_id: str | None, chat_id: str) -> str | None:
    from src.core.database import AsyncSessionLocal
    from src.models.agent import Agent
    from src.models.chat import Chat
    from src.models.project import Project
    from src.models.org import OrgMember

    async with AsyncSessionLocal() as db:
        if agent_id:
            r = await db.execute(select(Agent).where(Agent.id == agent_id))
            ag = r.scalar_one_or_none()
            if ag and ag.org_id:
                return ag.org_id
        r2 = await db.execute(select(Chat).where(Chat.id == chat_id))
        chat = r2.scalar_one_or_none()
        if chat and chat.project_id:
            r3 = await db.execute(select(Project).where(Project.id == chat.project_id))
            proj = r3.unique().scalar_one_or_none()
            if proj:
                return proj.org_id
        if chat and chat.user_id:
            r4 = await db.execute(select(OrgMember).where(OrgMember.user_id == chat.user_id).limit(1))
            om = r4.scalar_one_or_none()
            if om:
                return om.org_id
    return None


async def _resolve_agent_id(name_or_id: str | None, db) -> str | None:
    if not name_or_id:
        return None
    from src.models.agent import Agent
    try:
        import uuid
        uuid.UUID(name_or_id)
        r = await db.execute(select(Agent).where(Agent.id == name_or_id))
        if r.scalar_one_or_none():
            return name_or_id
    except (ValueError, AttributeError):
        pass
    from sqlalchemy import func
    r = await db.execute(select(Agent).where(func.lower(Agent.name) == name_or_id.lower()))
    ag = r.scalar_one_or_none()
    return ag.id if ag else None


def _sched_dict(s) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "description": s.description,
        "cron_expr": s.cron_expr,
        "interval_minutes": s.interval_minutes,
        "agent_id": s.agent_id,
        "prompt": s.prompt,
        "is_active": s.is_active,
        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
        "created_at": s.created_at.isoformat(),
    }


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    from src.core.database import AsyncSessionLocal
    from src.models.schedule import Schedule, ScheduleRun

    action = args.get("action", "")
    if not action:
        return {"error": "Missing required field: action"}

    org_id = await _get_org_id(agent_id, chat_id)
    if not org_id:
        return {"error": "Could not determine org_id from context"}

    if action == "list":
        async with AsyncSessionLocal() as db:
            r = await db.execute(
                select(Schedule)
                .where(Schedule.org_id == org_id)
                .order_by(Schedule.created_at.desc())
            )
            schedules = r.scalars().all()
        return {"data": [_sched_dict(s) for s in schedules]}

    if action == "get":
        schedule_id = args.get("schedule_id")
        if not schedule_id:
            return {"error": "Missing required field: schedule_id"}
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Schedule).where(Schedule.id == schedule_id, Schedule.org_id == org_id))
            s = r.scalar_one_or_none()
        if not s:
            return {"error": f"Schedule {schedule_id} not found"}
        return {"data": _sched_dict(s)}

    if action == "create":
        name = args.get("name")
        prompt = args.get("prompt")
        cron_expr = args.get("cron_expr")
        interval_minutes = args.get("interval_minutes")
        if not name or not prompt:
            return {"error": "Missing required fields: name, prompt"}
        if not cron_expr and not interval_minutes:
            return {"error": "Provide either cron_expr or interval_minutes"}
        if cron_expr and interval_minutes:
            return {"error": "Provide either cron_expr or interval_minutes, not both"}

        import uuid
        async with AsyncSessionLocal() as db:
            resolved_agent = await _resolve_agent_id(args.get("agent_name") or args.get("agent_id"), db)
            s = Schedule(
                id=str(uuid.uuid4()),
                org_id=org_id,
                name=name,
                description=args.get("description"),
                cron_expr=cron_expr,
                interval_minutes=int(interval_minutes) if interval_minutes else None,
                agent_id=resolved_agent,
                prompt=prompt,
                is_active=False,
            )
            db.add(s)
            await db.commit()
            await db.refresh(s)
        logger.info(f"[schedule_manage] agent {agent_name} created schedule {s.id} ({name!r})")
        return {"data": {**_sched_dict(s), "message": f"Schedule '{name}' created. Use action='activate' to start it."}}

    if action == "update":
        schedule_id = args.get("schedule_id")
        if not schedule_id:
            return {"error": "Missing required field: schedule_id"}
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Schedule).where(Schedule.id == schedule_id, Schedule.org_id == org_id))
            s = r.scalar_one_or_none()
            if not s:
                return {"error": f"Schedule {schedule_id} not found"}
            for field in ("name", "description", "cron_expr", "interval_minutes", "prompt"):
                if field in args and args[field] is not None:
                    setattr(s, field, args[field])
            if "agent_name" in args or "agent_id" in args:
                s.agent_id = await _resolve_agent_id(args.get("agent_name") or args.get("agent_id"), db)
            if s.is_active:
                from src.services.scheduler import unschedule_job, schedule_job
                unschedule_job(s.id)
                await schedule_job(s.id, s.cron_expr, s.interval_minutes)
            await db.commit()
            await db.refresh(s)
        return {"data": _sched_dict(s)}

    if action == "activate":
        schedule_id = args.get("schedule_id")
        if not schedule_id:
            return {"error": "Missing required field: schedule_id"}
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Schedule).where(Schedule.id == schedule_id, Schedule.org_id == org_id))
            s = r.scalar_one_or_none()
            if not s:
                return {"error": f"Schedule {schedule_id} not found"}
            from src.services.scheduler import schedule_job
            await schedule_job(s.id, s.cron_expr, s.interval_minutes)
            s.is_active = True
            await db.commit()
            await db.refresh(s)
        return {"data": {**_sched_dict(s), "message": f"Schedule '{s.name}' is now active."}}

    if action == "deactivate":
        schedule_id = args.get("schedule_id")
        if not schedule_id:
            return {"error": "Missing required field: schedule_id"}
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Schedule).where(Schedule.id == schedule_id, Schedule.org_id == org_id))
            s = r.scalar_one_or_none()
            if not s:
                return {"error": f"Schedule {schedule_id} not found"}
            from src.services.scheduler import unschedule_job
            unschedule_job(s.id)
            s.is_active = False
            s.next_run_at = None
            await db.commit()
            await db.refresh(s)
        return {"data": {**_sched_dict(s), "message": f"Schedule '{s.name}' deactivated."}}

    if action == "trigger":
        schedule_id = args.get("schedule_id")
        if not schedule_id:
            return {"error": "Missing required field: schedule_id"}
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Schedule).where(Schedule.id == schedule_id, Schedule.org_id == org_id))
            if not r.scalar_one_or_none():
                return {"error": f"Schedule {schedule_id} not found"}
        from src.services.schedule_runner import run_schedule
        run_id = await run_schedule(schedule_id, triggered_by="agent")
        return {"data": {"run_id": run_id, "message": "Schedule triggered. Run is executing in the background."}}

    if action == "runs":
        schedule_id = args.get("schedule_id")
        if not schedule_id:
            return {"error": "Missing required field: schedule_id"}
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Schedule).where(Schedule.id == schedule_id, Schedule.org_id == org_id))
            if not r.scalar_one_or_none():
                return {"error": f"Schedule {schedule_id} not found"}
            r2 = await db.execute(
                select(ScheduleRun)
                .where(ScheduleRun.schedule_id == schedule_id)
                .order_by(ScheduleRun.created_at.desc())
                .limit(20)
            )
            runs = r2.scalars().all()
        return {"data": [
            {
                "id": run.id,
                "status": run.status,
                "triggered_by": run.triggered_by,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "output": (run.output or "")[:200],
                "error": run.error,
            }
            for run in runs
        ]}

    if action == "delete":
        schedule_id = args.get("schedule_id")
        if not schedule_id:
            return {"error": "Missing required field: schedule_id"}
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Schedule).where(Schedule.id == schedule_id, Schedule.org_id == org_id))
            s = r.scalar_one_or_none()
            if not s:
                return {"error": f"Schedule {schedule_id} not found"}
            if s.is_active:
                from src.services.scheduler import unschedule_job
                unschedule_job(s.id)
            name = s.name
            await db.delete(s)
            await db.commit()
        return {"data": {"message": f"Schedule '{name}' deleted."}}

    return {"error": f"Unknown action: {action!r}. Valid actions: create, list, get, update, activate, deactivate, trigger, runs, delete"}
