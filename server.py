"""
Intigriti MCP Server.

Run with:
  uv run server.py
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from auth import OtpRequired, load_token, password_login, store_bearer_token, store_pat
from cache import clear_programs_cache, find_cached_program, load_programs_cache, save_programs_cache
from client import ForbiddenError, IntigritiClient, NotAuthenticatedError, NotFoundError

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("intigriti")

AUTH_ERROR = (
    "Not authenticated. Call authenticate with pat/access_token, set INTIGRITI_PAT "
    "or INTIGRITI_TOKEN, or refresh your expired token."
)

CONFIDENTIALITY = {
    1: "Invite only",
    2: "Application",
    3: "Registered",
    4: "Public",
}


def _client() -> IntigritiClient:
    token = load_token()
    if not token:
        raise ValueError(AUTH_ERROR)
    return IntigritiClient(token)


def _enum_value(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("value") or value.get("name") or value.get("id") or "N/A")
    return str(value) if value is not None else "N/A"


def _enum_id(value: Any) -> int | None:
    if isinstance(value, dict):
        try:
            return int(value.get("id"))
        except (TypeError, ValueError):
            return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _money(value: Any) -> str:
    if not isinstance(value, dict):
        return "N/A"
    amount = value.get("value")
    currency = value.get("currency", "")
    if amount is None:
        return "N/A"
    return f"{amount} {currency}".strip()


def _program_visibility(program: dict[str, Any]) -> str:
    conf = program.get("confidentialityLevel")
    conf_id = _enum_id(conf)
    if conf_id in CONFIDENTIALITY:
        return CONFIDENTIALITY[conf_id]
    return _enum_value(conf)


def _is_private(program: dict[str, Any]) -> bool:
    return _enum_id(program.get("confidentialityLevel")) in {1, 2, 3}


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


async def _fetch_programs(
    status_id: int | None = None,
    type_id: int | None = None,
    following: bool | None = None,
    all_pages: bool = True,
    update_cache: bool = True,
) -> list[dict[str, Any]]:
    client = _client()
    async with client:
        programs = await client.get_programs(
            status_id=status_id,
            type_id=type_id,
            following=following,
            all_pages=all_pages,
        )
    if update_cache and all_pages and status_id is None and type_id is None and following is None:
        save_programs_cache(programs)
    return programs


async def _resolve_program_id(identifier: str) -> tuple[str, dict[str, Any] | None]:
    identifier = identifier.strip()
    if not identifier:
        raise ValueError("program_id, handle, or name is required.")

    cached = find_cached_program(identifier)
    exact = [
        p for p in cached
        if identifier.lower() in {str(p.get("id", "")).lower(), str(p.get("handle", "")).lower()}
    ]
    if exact:
        return str(exact[0]["id"]), exact[0]
    if len(cached) == 1:
        return str(cached[0]["id"]), cached[0]

    programs = await _fetch_programs(update_cache=True)
    matches = [
        p for p in programs
        if identifier.lower() in {
            str(p.get("id", "")).lower(),
            str(p.get("handle", "")).lower(),
            str(p.get("name", "")).lower(),
        }
    ]
    if not matches:
        lowered = identifier.lower()
        matches = [p for p in programs if lowered in str(p.get("name", "")).lower() or lowered in str(p.get("handle", "")).lower()]
    if not matches:
        raise NotFoundError(f"Program '{identifier}' not found.")
    if len(matches) > 1:
        names = ", ".join(f"{p.get('name')} ({p.get('handle')}, {p.get('id')})" for p in matches[:10])
        raise ValueError(f"Multiple programs matched '{identifier}': {names}")
    return str(matches[0]["id"]), matches[0]


def _format_program_line(program: dict[str, Any]) -> str:
    bounty = ""
    min_bounty = _money(program.get("minBounty"))
    max_bounty = _money(program.get("maxBounty"))
    if min_bounty != "N/A" or max_bounty != "N/A":
        bounty = f" | bounty: {min_bounty} - {max_bounty}"
    return (
        f"[{_program_visibility(program)}] {program.get('name', 'N/A')} "
        f"(handle: {program.get('handle', 'N/A')}, id: {program.get('id', 'N/A')}, "
        f"status: {_enum_value(program.get('status'))}, type: {_enum_value(program.get('type'))})"
        f"{bounty}"
    )


def _format_domains(domains: Any) -> str:
    content = domains.get("content") if isinstance(domains, dict) else domains
    if not isinstance(content, list) or not content:
        return "  (none listed)"
    lines = []
    for item in content:
        skills = item.get("requiredSkills") or []
        skill_text = ", ".join(str(s.get("name", s)) if isinstance(s, dict) else str(s) for s in skills)
        desc = str(item.get("description") or "").strip()
        extra = f" | skills: {skill_text}" if skill_text else ""
        if desc:
            extra += f" | {desc}"
        lines.append(
            f"  [{_enum_value(item.get('type'))}] {item.get('endpoint', 'N/A')} "
            f"| tier: {_enum_value(item.get('tier'))}{extra}"
        )
    return "\n".join(lines)


def _format_rules(rules: Any) -> str:
    if not isinstance(rules, dict):
        return "  (none listed)"
    content = rules.get("content") if "content" in rules else rules
    if not isinstance(content, dict):
        return "  (none listed)"
    testing = content.get("testingRequirements") or {}
    parts = [
        f"Safe harbour: {content.get('safeHarbour', 'N/A')}",
    ]
    if testing:
        parts.extend(
            [
                f"Intigriti.me required: {testing.get('intigritiMe', 'N/A')}",
                f"Automated tooling: {testing.get('automatedTooling', 'N/A')}",
                f"User-Agent: {testing.get('userAgent') or 'N/A'}",
                f"Request header: {testing.get('requestHeader') or 'N/A'}",
            ]
        )
    description = str(content.get("description") or "").strip()
    if description:
        parts.extend(["", description])
    attachments = rules.get("attachments") or []
    if attachments:
        parts.extend(["", "Attachments:"])
        parts.extend(f"  - {a.get('url', a)}" if isinstance(a, dict) else f"  - {a}" for a in attachments)
    return "\n".join(parts)


@mcp.tool()
async def authenticate(
    pat: str = "",
    access_token: str = "",
    token: str = "",
    email: str = "",
    password: str = "",
    otp: str = "",
    client_id: str = "",
    client_secret: str = "",
    scope: str = "researcher_external_api offline_access",
) -> str:
    """
    Authenticate and cache the resulting token in ./config/token.json.

    Preferred: pass pat from Intigriti Personal Access Tokens.
    Also supported: pass access_token/token directly, or attempt credential login.

    Args:
        pat: Intigriti researcher API Personal Access Token.
        access_token: Existing bearer token.
        token: Alias for access_token.
        email: Account email for credential login.
        password: Account password for credential login.
        otp: Optional OTP/TOTP code for credential login.
        client_id: Optional OIDC client id when direct credential login requires one.
        client_secret: Optional OIDC client secret.
        scope: OIDC scope for credential login.
    """
    try:
        if pat:
            return store_pat(pat)
        if access_token or token:
            return store_bearer_token(access_token or token, "token")
        if email and password:
            return await password_login(
                email=email,
                password=password,
                otp=otp or None,
                client_id=client_id,
                client_secret=client_secret,
                scope=scope,
            )
        return "Provide pat, access_token/token, or email+password."
    except OtpRequired as e:
        return str(e)
    except ValueError as e:
        return str(e)


@mcp.tool()
async def list_programs(
    all_pages: bool = True,
    private_only: bool = False,
    public_only: bool = False,
    status_id: int = 0,
    type_id: int = 0,
    following: str = "",
    refresh_cache: bool = False,
    raw_json: bool = False,
) -> str:
    """
    List public and private Intigriti programs accessible to the authenticated researcher.

    Args:
        all_pages: Fetch all pages, up to 500 records per page.
        private_only: Show only invite/application/registered programs.
        public_only: Show only public programs.
        status_id: Optional API statusId filter. 3=open, 4=suspended, 5=closing.
        type_id: Optional API typeId filter. 1=bug bounty, 2=hybrid.
        following: Optional "true" or "false" following filter.
        refresh_cache: Force API fetch and update local cache.
        raw_json: Return raw API records as JSON.
    """
    try:
        following_value = None
        if following.strip().lower() in {"true", "1", "yes"}:
            following_value = True
        elif following.strip().lower() in {"false", "0", "no"}:
            following_value = False

        use_cache = not refresh_cache and status_id == 0 and type_id == 0 and following_value is None and all_pages
        programs = load_programs_cache() if use_cache else None
        if programs is None:
            should_update_cache = all_pages and status_id == 0 and type_id == 0 and following_value is None
            programs = await _fetch_programs(
                status_id=status_id or None,
                type_id=type_id or None,
                following=following_value,
                all_pages=all_pages,
                update_cache=should_update_cache,
            )
    except ValueError as e:
        return str(e)
    except NotAuthenticatedError:
        return AUTH_ERROR

    if private_only:
        programs = [p for p in programs if _is_private(p)]
    if public_only:
        programs = [p for p in programs if _enum_id(p.get("confidentialityLevel")) == 4]
    if raw_json:
        return _json(programs)
    if not programs:
        return "No programs found."
    return f"Found {len(programs)} program(s):\n" + "\n".join(_format_program_line(p) for p in programs)


@mcp.tool()
async def search_program(name: str, refresh_if_missing: bool = True, raw_json: bool = False) -> str:
    """
    Search for a program by name, handle, or id. Uses local cache first and only
    calls the API when no cached match is found.

    Args:
        name: Program name, handle, partial name, or UUID.
        refresh_if_missing: Fetch programs from API if the local cache has no match.
        raw_json: Return raw matched records as JSON.
    """
    if not name.strip():
        return "name is required."
    matches = find_cached_program(name)
    source = "cache"
    if not matches and refresh_if_missing:
        try:
            programs = await _fetch_programs(update_cache=True)
        except ValueError as e:
            return str(e)
        except NotAuthenticatedError:
            return AUTH_ERROR
        lowered = name.strip().lower()
        matches = [
            p for p in programs
            if lowered in str(p.get("name", "")).lower()
            or lowered in str(p.get("handle", "")).lower()
            or lowered == str(p.get("id", "")).lower()
        ]
        source = "api"
    if raw_json:
        return _json(matches)
    if not matches:
        return f"No program matched '{name}'."
    return f"Found {len(matches)} match(es) from {source}:\n" + "\n".join(_format_program_line(p) for p in matches)


@mcp.tool()
async def get_program(program: str, raw_json: bool = False) -> str:
    """
    Get full program details, including scopes/domains, rewards, rules of
    engagement, testing requirements, web links, and metadata.

    Args:
        program: Program id, handle, exact name, or unambiguous partial name.
        raw_json: Return raw full API response as JSON.
    """
    try:
        program_id, overview = await _resolve_program_id(program)
        client = _client()
        async with client:
            detail = await client.get(f"/v1/programs/{program_id}")
    except ValueError as e:
        return str(e)
    except NotAuthenticatedError:
        return AUTH_ERROR
    except ForbiddenError:
        return (
            f"Access forbidden for '{program}'. Intigriti may require accepting updated "
            "program terms and conditions in the web UI before details are available."
        )
    except NotFoundError as e:
        return str(e)

    if overview:
        detail.setdefault("_overview", overview)
    if raw_json:
        return _json(detail)

    overview = overview or {}
    domains = detail.get("domains") or {}
    rules = detail.get("rulesOfEngagement") or {}
    domain_version = domains.get("id") if isinstance(domains, dict) else None
    rules_version = rules.get("id") if isinstance(rules, dict) else None
    web_links = detail.get("webLinks") or overview.get("webLinks") or {}

    sections = [
        f"Name       : {detail.get('name', overview.get('name', 'N/A'))}",
        f"Handle     : {detail.get('handle', overview.get('handle', 'N/A'))}",
        f"ID         : {detail.get('id', program_id)}",
        f"Visibility : {_program_visibility(detail or overview)}",
        f"Status     : {_enum_value(detail.get('status') or overview.get('status'))}",
        f"Type       : {_enum_value(detail.get('type') or overview.get('type'))}",
        f"Following  : {detail.get('following', overview.get('following', 'N/A'))}",
        f"Industry   : {detail.get('industry', overview.get('industry', 'N/A'))}",
        f"Min bounty : {_money(overview.get('minBounty'))}",
        f"Max bounty : {_money(overview.get('maxBounty'))}",
        f"Detail URL : {web_links.get('detail', 'N/A')}",
        "",
        f"=== Domains / Scope (version {domain_version or 'N/A'}) ===",
        _format_domains(domains),
        "",
        f"=== Rules of Engagement (version {rules_version or 'N/A'}) ===",
        _format_rules(rules),
    ]
    return "\n".join(sections)


@mcp.tool()
async def get_program_domains(program: str, version_id: str = "", raw_json: bool = False) -> str:
    """
    Get a program domain/scope version. If version_id is omitted, the current
    version from get_program is used.
    """
    try:
        program_id, _ = await _resolve_program_id(program)
        client = _client()
        async with client:
            if not version_id:
                detail = await client.get(f"/v1/programs/{program_id}")
                domains = detail.get("domains") or {}
                version_id = str(domains.get("id") or "")
                if not version_id:
                    return "No domains version id found for this program."
            data = await client.get(f"/v1/programs/{program_id}/domains/{version_id}")
    except ValueError as e:
        return str(e)
    except NotAuthenticatedError:
        return AUTH_ERROR
    except (NotFoundError, ForbiddenError) as e:
        return str(e)
    return _json(data) if raw_json else _format_domains(data.get("domains", data))


@mcp.tool()
async def get_program_rules(program: str, version_id: str = "", raw_json: bool = False) -> str:
    """
    Get a program rules-of-engagement version. If version_id is omitted, the
    current version from get_program is used.
    """
    try:
        program_id, _ = await _resolve_program_id(program)
        client = _client()
        async with client:
            if not version_id:
                detail = await client.get(f"/v1/programs/{program_id}")
                rules = detail.get("rulesOfEngagement") or {}
                version_id = str(rules.get("id") or "")
                if not version_id:
                    return "No rules-of-engagement version id found for this program."
            data = await client.get(f"/v1/programs/{program_id}/rules-of-engagements/{version_id}")
    except ValueError as e:
        return str(e)
    except NotAuthenticatedError:
        return AUTH_ERROR
    except (NotFoundError, ForbiddenError) as e:
        return str(e)
    rules = data.get("rulesOfEngagement", data)
    return _json(data) if raw_json else _format_rules(rules)


@mcp.tool()
async def get_program_activities(
    created_since: int = 0,
    following: str = "",
    all_pages: bool = False,
    raw_json: bool = False,
) -> str:
    """
    Get program activity updates visible to the authenticated researcher.

    Args:
        created_since: Optional Unix timestamp filter.
        following: Optional "true" or "false" following filter.
        all_pages: Fetch all activity pages instead of the latest page.
        raw_json: Return raw activity records as JSON.
    """
    try:
        following_value = None
        if following.strip().lower() in {"true", "1", "yes"}:
            following_value = True
        elif following.strip().lower() in {"false", "0", "no"}:
            following_value = False
        client = _client()
        async with client:
            records = await client.get_records(
                "/v1/programs/activities",
                {"createdSince": created_since or None, "following": following_value},
                all_pages=all_pages,
            )
    except ValueError as e:
        return str(e)
    except NotAuthenticatedError:
        return AUTH_ERROR
    if raw_json:
        return _json(records)
    if not records:
        return "No program activities found."
    lines = []
    for item in records:
        lines.append(
            f"{item.get('programId', 'N/A')} | {_enum_value(item.get('type'))} | "
            f"createdAt: {item.get('createdAt', 'N/A')} | following: {item.get('following', 'N/A')}"
        )
    return f"Found {len(records)} activit(y/ies):\n" + "\n".join(lines)


@mcp.tool()
async def clear_cache() -> str:
    """Clear the local programs cache."""
    clear_programs_cache()
    return "Cleared Intigriti programs cache."


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
