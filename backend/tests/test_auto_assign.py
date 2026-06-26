"""Deterministic auto-assignment of unassigned tasks by capability (model-agnostic routing).

No LLM: a task with no agent should be routed to the best-fit specialist by skill/tool/role
overlap, with a capable-"doer" fallback, and orchestrator-type agents are never targeted.
"""
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from src.models.agent import Agent
from src.services.agent_tools.task_helpers import _match_agent_to_task

ORG = "org-aa"


async def _seed(factory):
    async with factory() as s:
        s.add(Agent(id="infra", org_id=ORG, name="Infrastructure Manager", agent_type="devops",
                    description="DevOps: docker, deploy, git", is_active=True,
                    tools=["shell_run", "file_write", "git_local", "docker_ps"], skills=[]))
        s.add(Agent(id="research", org_id=ORG, name="KB Researcher", agent_type="assistant",
                    description="research and knowledge lookups", is_active=True,
                    tools=["knowledge_search", "read_url"], skills=[]))
        s.add(Agent(id="pm", org_id=ORG, name="Project Manager", agent_type="project_manager",
                    description="plans and delegates docker git deploy everything", is_active=True,
                    tools=["task_create"], skills=[]))
        await s.commit()


@pytest.mark.asyncio
async def test_matches_by_capability(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await _seed(factory)
    async with factory() as db:
        # docker/deploy/git work → infra (overlap), never the PM (orchestrator type excluded)
        aid = await _match_agent_to_task(db, ORG, "Dockerize and deploy", "set up docker compose and push to git")
        assert aid == "infra"
        # research-flavored work → researcher
        aid2 = await _match_agent_to_task(db, ORG, "Research competitors", "knowledge lookups and read_url sources")
        assert aid2 == "research"
    async with factory() as s:
        await s.execute(Agent.__table__.delete())
        await s.commit()


@pytest.mark.asyncio
async def test_no_keyword_match_falls_back_to_doer(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await _seed(factory)
    async with factory() as db:
        # gibberish with no capability overlap → the most build-capable agent (infra has the doer tools)
        aid = await _match_agent_to_task(db, ORG, "zzqq", "wxyv plover frobnitz")
        assert aid == "infra"
    async with factory() as s:
        await s.execute(Agent.__table__.delete())
        await s.commit()


@pytest.mark.asyncio
async def test_excludes_caller_and_orchestrators(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        # only a PM (orchestrator) + the caller exist → no valid target
        s.add(Agent(id="pm2", org_id=ORG, name="PM", agent_type="project_manager",
                    description="docker git", is_active=True, tools=["task_create"], skills=[]))
        s.add(Agent(id="caller", org_id=ORG, name="Caller", agent_type="custom",
                    description="docker git", is_active=True, tools=["file_write"], skills=[]))
        await s.commit()
    async with factory() as db:
        aid = await _match_agent_to_task(db, ORG, "docker", "git deploy", exclude_id="caller")
        assert aid is None  # PM excluded by type, caller excluded explicitly
    async with factory() as s:
        await s.execute(Agent.__table__.delete())
        await s.commit()


@pytest.mark.asyncio
async def test_no_org_returns_none(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        assert await _match_agent_to_task(db, None, "anything", "x") is None
