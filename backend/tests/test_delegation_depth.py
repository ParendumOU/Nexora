"""Unified sub-delegation depth (GitLab #228).

Both the CLI spawn path and the sub-agent executor now gate on the same
ancestry-based `delegation_depth`; `_count_hops` is its cycle-safe core.
"""
from src.services.sub_agent.spawn import _count_hops


def _parent_of(parent_map):
    return lambda cid: parent_map.get(cid)


def test_root_is_zero():
    assert _count_hops("root", _parent_of({"root": None})) == 0
    assert _count_hops("root", _parent_of({})) == 0


def test_counts_hops_to_root():
    pmap = {"c3": "c2", "c2": "c1", "c1": None}
    assert _count_hops("c3", _parent_of(pmap)) == 2
    assert _count_hops("c2", _parent_of(pmap)) == 1
    assert _count_hops("c1", _parent_of(pmap)) == 0


def test_cycle_is_guarded():
    # a→b→a must terminate (not loop forever); it counts a→b→a then stops on revisit
    pmap = {"a": "b", "b": "a"}
    assert _count_hops("a", _parent_of(pmap)) == 2


def test_max_hops_cap():
    # a long chain is bounded by max_hops
    pmap = {str(i): str(i + 1) for i in range(50)}
    assert _count_hops("0", _parent_of(pmap), max_hops=10) == 10


def test_spawn_and_executor_share_one_function():
    # The unification: the executor gates on spawn.delegation_depth, not its own walk.
    import inspect
    from src.services.sub_agent import executor
    src = inspect.getsource(executor._execute_sub_agent_task)
    assert "delegation_depth" in src
