"""Shared helpers to browse GitHub / GitLab repos via a stored credential."""
import asyncio
import httpx
from src.core.security import decrypt
from src.models.git_credential import GitCredential


def _map_github_repo(r: dict, group_name: str, group_type: str) -> dict:
    return {
        "id": str(r["id"]),
        "name": r["name"],
        "full_name": r["full_name"],
        "web_url": r["html_url"],
        "description": r.get("description") or "",
        "is_private": r["private"],
        "default_branch": r.get("default_branch") or "main",
        "group": group_name,
        "group_type": group_type,
    }


def _map_gitlab_repo(p: dict, group_name: str, group_type: str) -> dict:
    return {
        "id": str(p["id"]),
        "name": p["name"],
        "full_name": p["path_with_namespace"],
        "web_url": p["web_url"],
        "description": p.get("description") or "",
        "is_private": p.get("visibility") != "public",
        "default_branch": p.get("default_branch") or "main",
        "group": group_name,
        "group_type": group_type,
    }


async def _fetch_org_name(client: httpx.AsyncClient, login: str, headers: dict) -> str:
    try:
        r = await client.get(f"https://api.github.com/orgs/{login}", headers=headers, timeout=10)
        if r.status_code == 200:
            return r.json().get("name") or login
    except Exception:
        pass
    return login


async def fetch_github_tree(token: str) -> list[dict]:
    """Return grouped tree [{id, type, name, avatar_url, repos, subgroups}] for GitHub."""
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    async with httpx.AsyncClient(timeout=20) as client:
        user_resp = await client.get("https://api.github.com/user", headers=headers)
        if user_resp.status_code == 401:
            raise ValueError("GitHub token invalid or expired")
        user_resp.raise_for_status()
        user = user_resp.json()
        display_name = user.get("name") or user["login"]

        repos_resp = await client.get(
            "https://api.github.com/user/repos?type=owner&per_page=100&sort=updated",
            headers=headers,
        )
        user_repos = repos_resp.json() if repos_resp.status_code == 200 else []

        orgs_resp = await client.get("https://api.github.com/user/orgs?per_page=100", headers=headers)
        orgs = orgs_resp.json() if orgs_resp.status_code == 200 else []
        if not isinstance(orgs, list):
            orgs = []

        # fetch org display names + repos concurrently
        async def _load_org(org: dict) -> dict | None:
            if not isinstance(org, dict):
                return None
            login = org["login"]
            org_name = await _fetch_org_name(client, login, headers)
            org_repos_resp = await client.get(
                f"https://api.github.com/orgs/{login}/repos?per_page=100&sort=updated",
                headers=headers,
            )
            org_repos = org_repos_resp.json() if org_repos_resp.status_code == 200 else []
            return {
                "id": f"org_{org['id']}",
                "type": "org",
                "name": org_name,
                "avatar_url": org.get("avatar_url"),
                "repos": [_map_github_repo(r, org_name, "org") for r in org_repos if isinstance(r, dict)],
                "subgroups": [],
            }

        org_tasks = [_load_org(o) for o in orgs]
        org_results = await asyncio.gather(*org_tasks, return_exceptions=True)

        groups = [
            {
                "id": f"user_{user['login']}",
                "type": "user",
                "name": display_name,
                "avatar_url": user.get("avatar_url"),
                "repos": [_map_github_repo(r, display_name, "user") for r in user_repos if isinstance(r, dict)],
                "subgroups": [],
            }
        ]
        for result in org_results:
            if isinstance(result, dict):
                groups.append(result)

        return groups


async def fetch_gitlab_tree(token: str, base_url: str) -> list[dict]:
    """Return grouped tree [{id, type, name, full_path, avatar_url, repos, subgroups}] for GitLab."""
    base = base_url.rstrip("/")
    api_base = f"{base}/api/v4"
    headers = {"PRIVATE-TOKEN": token}

    async with httpx.AsyncClient(timeout=20) as client:
        user_resp = await client.get(f"{api_base}/user", headers=headers)
        if user_resp.status_code == 401:
            raise ValueError("GitLab token invalid or expired")
        user_resp.raise_for_status()
        user = user_resp.json()
        user_display = user.get("name") or user.get("username") or str(user["id"])

        personal_resp = await client.get(
            f"{api_base}/projects?owned=true&per_page=100&order_by=last_activity_at",
            headers=headers,
        )
        personal_projects = personal_resp.json() if personal_resp.status_code == 200 else []
        personal_projects = [
            p for p in personal_projects
            if isinstance(p, dict) and p.get("namespace", {}).get("kind") == "user"
        ]

        groups_resp = await client.get(
            f"{api_base}/groups?per_page=100&min_access_level=10&top_level_only=true",
            headers=headers,
        )
        groups_data = groups_resp.json() if groups_resp.status_code == 200 else []
        if not isinstance(groups_data, list):
            groups_data = []

        result = []
        if personal_projects:
            result.append({
                "id": f"user_{user['id']}",
                "type": "user",
                "name": user_display,
                "full_path": user.get("username", ""),
                "avatar_url": user.get("avatar_url"),
                "repos": [_map_gitlab_repo(p, user_display, "user") for p in personal_projects],
                "subgroups": [],
            })

        async def _load_group(group: dict) -> dict | None:
            if not isinstance(group, dict):
                return None
            group_display = group.get("name") or group.get("path", "")
            proj_resp = await client.get(
                f"{api_base}/groups/{group['id']}/projects"
                "?per_page=100&include_subgroups=false&order_by=last_activity_at",
                headers=headers,
            )
            projects = proj_resp.json() if proj_resp.status_code == 200 else []

            sub_resp = await client.get(
                f"{api_base}/groups/{group['id']}/subgroups?per_page=100",
                headers=headers,
            )
            subgroups_data = sub_resp.json() if sub_resp.status_code == 200 else []

            async def _load_subgroup(sg: dict) -> dict | None:
                if not isinstance(sg, dict):
                    return None
                sg_display = sg.get("name") or sg.get("path", "")
                sg_proj_resp = await client.get(
                    f"{api_base}/groups/{sg['id']}/projects?per_page=100&order_by=last_activity_at",
                    headers=headers,
                )
                sg_projects = sg_proj_resp.json() if sg_proj_resp.status_code == 200 else []
                return {
                    "id": f"group_{sg['id']}",
                    "type": "subgroup",
                    "name": sg_display,
                    "full_path": sg.get("full_path", sg_display),
                    "repos": [_map_gitlab_repo(p, sg_display, "subgroup") for p in sg_projects if isinstance(p, dict)],
                    "subgroups": [],
                }

            sg_tasks = [_load_subgroup(sg) for sg in (subgroups_data if isinstance(subgroups_data, list) else [])]
            sg_results = await asyncio.gather(*sg_tasks, return_exceptions=True)
            subgroups = [r for r in sg_results if isinstance(r, dict)]

            return {
                "id": f"group_{group['id']}",
                "type": "group",
                "name": group_display,
                "full_path": group.get("full_path", group_display),
                "avatar_url": group.get("avatar_url"),
                "repos": [_map_gitlab_repo(p, group_display, "group") for p in projects if isinstance(p, dict)],
                "subgroups": subgroups,
            }

        group_tasks = [_load_group(g) for g in groups_data]
        group_results = await asyncio.gather(*group_tasks, return_exceptions=True)
        for r in group_results:
            if isinstance(r, dict):
                result.append(r)

        return result


def flatten_repos(tree: list[dict]) -> list[dict]:
    """Convert tree structure to flat list of repos (for agent consumption)."""
    flat: list[dict] = []

    def walk(nodes: list[dict]) -> None:
        for node in nodes:
            flat.extend(node.get("repos", []))
            if node.get("subgroups"):
                walk(node["subgroups"])

    walk(tree)
    return flat


async def fetch_repos_for_credential(cred: GitCredential) -> list[dict]:
    """Return flat repo list for a GitCredential ORM instance."""
    try:
        token = decrypt(cred.token)
    except Exception:
        token = cred.token

    if cred.provider == "github":
        tree = await fetch_github_tree(token)
    elif cred.provider == "gitlab":
        tree = await fetch_gitlab_tree(token, cred.base_url or "https://gitlab.com")
    else:
        raise ValueError(f"Unsupported provider: {cred.provider}")

    return flatten_repos(tree)


async def fetch_tree_for_credential(cred: GitCredential) -> list[dict]:
    """Return nested tree structure for a GitCredential ORM instance."""
    try:
        token = decrypt(cred.token)
    except Exception:
        token = cred.token

    if cred.provider == "github":
        return await fetch_github_tree(token)
    elif cred.provider == "gitlab":
        return await fetch_gitlab_tree(token, cred.base_url or "https://gitlab.com")
    else:
        raise ValueError(f"Unsupported provider: {cred.provider}")


# ── Lazy / incremental loading ────────────────────────────────────────────────
# Node ID conventions (stable between root and expand calls):
#   GitHub:  gh_user_{login}   gh_org_{login}
#   GitLab:  gl_user_{id}      gl_group_{id}   (subgroups also use gl_group_)

def _make_stub(node_id: str, ntype: str, name: str, **extra) -> dict:
    return {"id": node_id, "type": ntype, "name": name,
            "repos": [], "subgroups": [], "children_loaded": False, **extra}


async def _github_root_nodes(token: str) -> list[dict]:
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    async with httpx.AsyncClient(timeout=20) as client:
        user_resp = await client.get("https://api.github.com/user", headers=headers)
        if user_resp.status_code == 401:
            raise ValueError("GitHub token invalid or expired")
        user_resp.raise_for_status()
        user = user_resp.json()
        display_name = user.get("name") or user["login"]

        orgs_resp = await client.get("https://api.github.com/user/orgs?per_page=100", headers=headers)
        orgs_raw = [o for o in (orgs_resp.json() if orgs_resp.status_code == 200 else []) if isinstance(o, dict)]

        async def _org_display(login: str) -> str:
            try:
                r = await client.get(f"https://api.github.com/orgs/{login}", headers=headers, timeout=10)
                if r.status_code == 200:
                    return r.json().get("name") or login
            except Exception:
                pass
            return login

        org_names = await asyncio.gather(*[_org_display(o["login"]) for o in orgs_raw], return_exceptions=True)

        nodes = [_make_stub(f"gh_user_{user['login']}", "user", display_name, avatar_url=user.get("avatar_url"))]
        for i, org in enumerate(orgs_raw):
            name = org_names[i] if not isinstance(org_names[i], Exception) else org["login"]
            nodes.append(_make_stub(f"gh_org_{org['login']}", "org", str(name), avatar_url=org.get("avatar_url")))
        return nodes


async def _github_expand_node(token: str, node_id: str) -> dict:
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    async with httpx.AsyncClient(timeout=20) as client:
        if node_id.startswith("gh_user_"):
            login = node_id[len("gh_user_"):]
            resp = await client.get(
                "https://api.github.com/user/repos?type=owner&per_page=100&sort=updated", headers=headers
            )
            repos_data = resp.json() if resp.status_code == 200 else []
            group_name, group_type = login, "user"
        elif node_id.startswith("gh_org_"):
            login = node_id[len("gh_org_"):]
            resp = await client.get(
                f"https://api.github.com/orgs/{login}/repos?per_page=100&sort=updated", headers=headers
            )
            repos_data = resp.json() if resp.status_code == 200 else []
            group_name, group_type = login, "org"
        else:
            return {"repos": [], "subgroups": []}

        if not isinstance(repos_data, list):
            repos_data = []
        return {
            "repos": [_map_github_repo(r, group_name, group_type) for r in repos_data if isinstance(r, dict)],
            "subgroups": [],
        }


async def _gitlab_root_nodes(token: str, base_url: str) -> list[dict]:
    base = base_url.rstrip("/")
    api_base = f"{base}/api/v4"
    headers = {"PRIVATE-TOKEN": token}

    async with httpx.AsyncClient(timeout=20) as client:
        user_resp = await client.get(f"{api_base}/user", headers=headers)
        if user_resp.status_code == 401:
            raise ValueError("GitLab token invalid or expired")
        user_resp.raise_for_status()
        user = user_resp.json()
        user_display = user.get("name") or user.get("username") or str(user["id"])

        groups_resp = await client.get(
            f"{api_base}/groups?per_page=100&min_access_level=10&top_level_only=true", headers=headers
        )
        groups_data = [g for g in (groups_resp.json() if groups_resp.status_code == 200 else []) if isinstance(g, dict)]

        nodes = [_make_stub(
            f"gl_user_{user['id']}", "user", user_display,
            full_path=user.get("username", ""), avatar_url=user.get("avatar_url"),
        )]
        for group in groups_data:
            nodes.append(_make_stub(
                f"gl_group_{group['id']}", "group",
                group.get("name") or group.get("path", ""),
                full_path=group.get("full_path", ""),
                avatar_url=group.get("avatar_url"),
            ))
        return nodes


async def _gitlab_expand_node(token: str, node_id: str, base_url: str) -> dict:
    base = base_url.rstrip("/")
    api_base = f"{base}/api/v4"
    headers = {"PRIVATE-TOKEN": token}

    async with httpx.AsyncClient(timeout=20) as client:
        if node_id.startswith("gl_user_"):
            user_resp, personal_resp = await asyncio.gather(
                client.get(f"{api_base}/user", headers=headers),
                client.get(f"{api_base}/projects?owned=true&per_page=100&order_by=last_activity_at", headers=headers),
                return_exceptions=True,
            )
            user = user_resp.json() if isinstance(user_resp, httpx.Response) and user_resp.status_code == 200 else {}
            user_display = user.get("name") or user.get("username") or "me"
            projects_raw = personal_resp.json() if isinstance(personal_resp, httpx.Response) and personal_resp.status_code == 200 else []
            personal = [p for p in projects_raw if isinstance(p, dict) and p.get("namespace", {}).get("kind") == "user"]
            return {"repos": [_map_gitlab_repo(p, user_display, "user") for p in personal], "subgroups": []}

        elif node_id.startswith("gl_group_"):
            group_id = node_id[len("gl_group_"):]
            group_info_resp, proj_resp, sub_resp = await asyncio.gather(
                client.get(f"{api_base}/groups/{group_id}", headers=headers),
                client.get(
                    f"{api_base}/groups/{group_id}/projects"
                    "?per_page=100&include_subgroups=false&order_by=last_activity_at",
                    headers=headers,
                ),
                client.get(f"{api_base}/groups/{group_id}/subgroups?per_page=100", headers=headers),
                return_exceptions=True,
            )
            group_display = group_id
            if isinstance(group_info_resp, httpx.Response) and group_info_resp.status_code == 200:
                gd = group_info_resp.json()
                group_display = gd.get("name") or gd.get("path", group_id)

            projects = proj_resp.json() if isinstance(proj_resp, httpx.Response) and proj_resp.status_code == 200 else []
            subgroups_data = sub_resp.json() if isinstance(sub_resp, httpx.Response) and sub_resp.status_code == 200 else []

            return {
                "repos": [_map_gitlab_repo(p, group_display, "group") for p in projects if isinstance(p, dict)],
                "subgroups": [
                    _make_stub(
                        f"gl_group_{sg['id']}", "subgroup",
                        sg.get("name") or sg.get("path", ""),
                        full_path=sg.get("full_path", ""),
                    )
                    for sg in subgroups_data if isinstance(sg, dict)
                ],
            }

        return {"repos": [], "subgroups": []}


async def fetch_root_nodes_for_credential(cred: GitCredential) -> list[dict]:
    """Return top-level group stubs (no repos) for lazy tree loading."""
    try:
        token = decrypt(cred.token)
    except Exception:
        token = cred.token
    if cred.provider == "github":
        return await _github_root_nodes(token)
    elif cred.provider == "gitlab":
        return await _gitlab_root_nodes(token, cred.base_url or "https://gitlab.com")
    raise ValueError(f"Unsupported provider: {cred.provider}")


async def fetch_node_children_for_credential(cred: GitCredential, node_id: str) -> dict:
    """Return repos + subgroup stubs for one lazy-expand step."""
    try:
        token = decrypt(cred.token)
    except Exception:
        token = cred.token
    if cred.provider == "github":
        return await _github_expand_node(token, node_id)
    elif cred.provider == "gitlab":
        return await _gitlab_expand_node(token, node_id, cred.base_url or "https://gitlab.com")
    raise ValueError(f"Unsupported provider: {cred.provider}")
