#!/usr/bin/env python3
"""Generate monochrome GitHub stats SVGs into assets/."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
USERNAME = os.environ.get("GH_USERNAME", "navopw")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
# Owned originally / still yours but under another org
EXTRA_STAR_REPOS = ("askrella/whatsapp-chatgpt",)

QUERY = """
query($login: String!) {
  user(login: $login) {
    followers { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, first: 100) {
      totalCount
      nodes {
        stargazerCount
        forkCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      contributionCalendar { totalContributions }
    }
    pullRequests { totalCount }
    issues { totalCount }
  }
}
"""

REPO_STARS_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    stargazerCount
  }
}
"""


def gh_graphql(query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "navopw-profile-stats",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        payload = json.loads(resp.read().decode())
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]


def fmt(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".rstrip("0").rstrip(".")
    if n >= 1_000:
        v = f"{n / 1_000:.1f}".rstrip("0").rstrip(".")
        return f"{v}k"
    return str(n)


def esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def stats_svg(stats: dict) -> str:
    rows = [
        ("Stars", stats["stars"]),
        ("Commits (year)", stats["commits"]),
        ("Pull Requests", stats["prs"]),
        ("Issues", stats["issues"]),
        ("Contributions (year)", stats["contribs"]),
    ]
    height = 48 + len(rows) * 28 + 20
    width = 360
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">',
        f"<title>{esc(USERNAME)}'s GitHub Stats</title>",
        f'<rect width="{width}" height="{height}" rx="8" fill="#111111"/>',
        f'<text x="24" y="34" fill="#ffffff" font-family="Segoe UI, Ubuntu, Sans-Serif" font-size="16" font-weight="600">{esc(USERNAME)}\'s GitHub Stats</text>',
    ]
    y = 68
    for label, value in rows:
        lines.append(
            f'<text x="24" y="{y}" fill="#c9c9c9" font-family="Segoe UI, Ubuntu, Sans-Serif" font-size="13">{esc(label)}</text>'
        )
        lines.append(
            f'<text x="{width - 24}" y="{y}" fill="#ffffff" font-family="Segoe UI, Ubuntu, Sans-Serif" font-size="13" font-weight="600" text-anchor="end">{esc(fmt(value))}</text>'
        )
        y += 28
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def langs_svg(langs: list[tuple[str, int, str]]) -> str:
    total = sum(size for _, size, _ in langs) or 1
    width = 360
    bar_w = width - 48
    height = 48 + 36 + len(langs) * 26 + 16
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">',
        "<title>Top Languages</title>",
        f'<rect width="{width}" height="{height}" rx="8" fill="#111111"/>',
        '<text x="24" y="34" fill="#ffffff" font-family="Segoe UI, Ubuntu, Sans-Serif" font-size="16" font-weight="600">Top Languages</text>',
        f'<rect x="24" y="52" width="{bar_w}" height="10" rx="5" fill="#222222"/>',
    ]
    x = 24.0
    for name, size, color in langs:
        w = bar_w * (size / total)
        fill = color if color else "#888888"
        lines.append(
            f'<rect x="{x:.2f}" y="52" width="{max(w, 0):.2f}" height="10" fill="{esc(fill)}"/>'
        )
        x += w
    # round ends by overlaying rounded track is enough; segments are fine
    y = 88
    for name, size, color in langs:
        pct = size / total * 100
        fill = color if color else "#888888"
        lines.append(f'<circle cx="30" cy="{y - 4}" r="5" fill="{esc(fill)}"/>')
        lines.append(
            f'<text x="44" y="{y}" fill="#c9c9c9" font-family="Segoe UI, Ubuntu, Sans-Serif" font-size="13">{esc(name)}</text>'
        )
        lines.append(
            f'<text x="{width - 24}" y="{y}" fill="#ffffff" font-family="Segoe UI, Ubuntu, Sans-Serif" font-size="13" font-weight="600" text-anchor="end">{pct:.1f}%</text>'
        )
        y += 26
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def resolve_token() -> str:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    if token:
        return token
    try:
        return subprocess.check_output(["gh", "auth", "token"], text=True).strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise SystemExit("GH_TOKEN / GITHUB_TOKEN required") from exc


def main() -> None:
    global TOKEN
    TOKEN = resolve_token()

    data = gh_graphql(QUERY, {"login": USERNAME})["user"]
    stars = sum(n["stargazerCount"] for n in data["repositories"]["nodes"])
    extra_stars: dict[str, int] = {}
    for full_name in EXTRA_STAR_REPOS:
        owner, name = full_name.split("/", 1)
        repo = gh_graphql(REPO_STARS_QUERY, {"owner": owner, "name": name})[
            "repository"
        ]
        if repo is None:
            continue
        extra_stars[full_name] = repo["stargazerCount"]
        stars += repo["stargazerCount"]
    lang_sizes: dict[str, int] = defaultdict(int)
    lang_colors: dict[str, str] = {}
    for repo in data["repositories"]["nodes"]:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            lang_sizes[name] += edge["size"]
            lang_colors[name] = edge["node"]["color"] or "#888888"

    top = sorted(lang_sizes.items(), key=lambda kv: kv[1], reverse=True)[:6]
    langs = [(name, size, lang_colors.get(name, "#888888")) for name, size in top]

    cc = data["contributionsCollection"]
    stats = {
        "stars": stars,
        "commits": cc["totalCommitContributions"],
        "prs": data["pullRequests"]["totalCount"],
        "issues": data["issues"]["totalCount"],
        "contribs": cc["contributionCalendar"]["totalContributions"],
        "followers": data["followers"]["totalCount"],
        "repos": data["repositories"]["totalCount"],
    }

    ASSETS.mkdir(parents=True, exist_ok=True)
    (ASSETS / "stats.svg").write_text(stats_svg(stats))
    (ASSETS / "top-langs.svg").write_text(langs_svg(langs))

    # keep prose numbers roughly in sync hint for humans
    print(
        json.dumps(
            {
                "stars": stats["stars"],
                "extra_stars": extra_stars,
                "followers": stats["followers"],
                "repos": stats["repos"],
                "contribs_year": stats["contribs"],
                "top_langs": [n for n, _, _ in langs],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
