#!/usr/bin/env python3
"""Builds the auto-updated parts of the profile README.

* assets/stats-{dark,light}.svg  - stats card in GitHub's own colours
* README.md  STACK section       - tech stack detected from your repositories
* README.md  ACTIVITY section    - recent public activity

Runs in GitHub Actions (see .github/workflows/update-readme.yml).
Local test without network:  python scripts/build_profile.py --mock scripts/mock.json
"""
import base64, datetime as dt, html, json, os, re, sys, urllib.error, urllib.request
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = json.load(open(os.path.join(ROOT, "profile.json")))
USER = CFG["username"]
API = "https://api.github.com"
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

# --------------------------------------------------------------------------- API
def call(url, body=None):
    h = {"Accept": "application/vnd.github+json", "User-Agent": "profile-readme-builder",
         "X-GitHub-Api-Version": "2022-11-28"}
    if TOKEN:
        h["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(url, json.dumps(body).encode() if body else None, h)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def try_call(url):
    try:
        return call(url)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return None

QUERY = """
query($login: String!, $privacy: RepositoryPrivacy) {
  user(login: $login) {
    createdAt
    followers { totalCount }
    pullRequests { totalCount }
    issues { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: $privacy,
                 orderBy: {field: PUSHED_AT, direction: DESC}) {
      totalCount
      nodes {
        name stargazerCount forkCount isArchived
        defaultBranchRef { name }
        languages(first: 20, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
        repositoryTopics(first: 20) { nodes { topic { name } } }
      }
    }
    contributionsCollection {
      totalCommitContributions restrictedContributionsCount
      totalPullRequestContributions totalIssueContributions
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}"""

MANIFESTS = re.compile(r"(^|/)(package\.json|requirements\.txt|pyproject\.toml|Pipfile|pom\.xml|"
                       r"build\.gradle(\.kts)?|composer\.json|pubspec\.yaml|Gemfile|go\.mod|Cargo\.toml)$")

def fetch():
    res = call(API + "/graphql", {"query": QUERY, "variables": {
        "login": USER, "privacy": None if CFG.get("include_private") else "PUBLIC"}})
    if res.get("errors"):
        sys.exit(f"GraphQL error: {res['errors']}")
    user = res["data"]["user"]
    files = {}
    for repo in user["repositories"]["nodes"]:
        branch = (repo.get("defaultBranchRef") or {}).get("name")
        if not branch:
            continue
        tree = try_call(f"{API}/repos/{USER}/{repo['name']}/git/trees/{branch}?recursive=1") or {}
        paths = [t["path"] for t in tree.get("tree", []) if t.get("type") == "blob"]
        paths = [p for p in paths if "node_modules/" not in p and "vendor/" not in p]
        contents = {}
        for p in [p for p in paths if MANIFESTS.search(p)][:8]:
            blob = try_call(f"{API}/repos/{USER}/{repo['name']}/contents/{p}?ref={branch}")
            if blob and blob.get("encoding") == "base64":
                contents[p] = base64.b64decode(blob["content"]).decode("utf-8", "replace")
        files[repo["name"]] = {"paths": paths, "contents": contents}
    events = try_call(f"{API}/users/{USER}/events/public?per_page=60") or []
    return {"user": user, "files": files, "events": events}

# ------------------------------------------------------------------- stack detection
LANG_ICON = {
    "JavaScript": "js", "TypeScript": "ts", "Python": "py", "Java": "java", "C": "c", "C++": "cpp",
    "C#": "cs", "Go": "go", "Rust": "rust", "PHP": "php", "Ruby": "ruby", "Kotlin": "kotlin",
    "Swift": "swift", "Dart": "dart", "HTML": "html", "CSS": "css", "SCSS": "sass", "Sass": "sass",
    "Shell": "bash", "PowerShell": "powershell", "R": "r", "Lua": "lua", "Scala": "scala",
    "Haskell": "haskell", "Elixir": "elixir", "Solidity": "solidity", "TeX": "latex", "MATLAB": "matlab",
    "Vue": "vue", "Svelte": "svelte", "Jupyter Notebook": "py",
    "Clojure": "clojure", "Perl": "perl", "Julia": "julia", "Zig": "zig", "Nim": "nim",
}
FILE_RULES = [  # (regex on file path, icon)
    (r"(^|/)Dockerfile$|(^|/)(docker-)?compose\.ya?ml$", "docker"),
    (r"^\.github/workflows/.+\.ya?ml$", "githubactions"),
    (r"(^|/)firebase\.json$", "firebase"), (r"(^|/)vercel\.json$", "vercel"),
    (r"(^|/)netlify\.toml$", "netlify"), (r"(^|/)tailwind\.config\.\w+$", "tailwind"),
    (r"(^|/)vite\.config\.\w+$", "vite"), (r"(^|/)next\.config\.\w+$", "nextjs"),
    (r"(^|/)angular\.json$", "angular"), (r"(^|/)pubspec\.yaml$", "flutter"),
    (r"(^|/)pom\.xml$", "maven"), (r"(^|/)build\.gradle(\.kts)?$", "gradle"),
    (r"(^|/)schema\.prisma$", "prisma"), (r"(^|/)nginx\.conf$", "nginx"),
    (r"(^|/)manage\.py$", "django"), (r"(^|/)svelte\.config\.\w+$", "svelte"),
    (r"(^|/)package\.json$", "nodejs"), (r"(^|/)webpack\.config\.\w+$", "webpack"),
    (r"(^|/)k8s/|(^|/)kustomization\.ya?ml$", "kubernetes"),
    (r"\.ipynb$", "py"), (r"(^|/)AndroidManifest\.xml$", "androidstudio"),
]
DEP_RULES = {  # dependency name (lowercase, exact or prefix*) -> icon
    "react": "react", "react-dom": "react", "react-native": "react", "next": "nextjs", "vue": "vue",
    "nuxt": "nuxtjs", "svelte": "svelte", "@angular/core": "angular", "express": "express",
    "@nestjs/core": "nestjs", "tailwindcss": "tailwind", "bootstrap": "bootstrap", "sass": "sass",
    "redux": "redux", "@reduxjs/toolkit": "redux", "mongoose": "mongodb", "mongodb": "mongodb",
    "mysql": "mysql", "mysql2": "mysql", "pg": "postgres", "sqlite3": "sqlite", "better-sqlite3": "sqlite",
    "redis": "redis", "ioredis": "redis", "prisma": "prisma", "@prisma/client": "prisma",
    "firebase": "firebase", "firebase-admin": "firebase", "@supabase/supabase-js": "supabase",
    "three": "threejs", "vite": "vite", "webpack": "webpack", "jest": "jest", "graphql": "graphql",
    "electron": "electron", "jquery": "jquery", "typescript": "ts", "@mui/material": "materialui",
    "socket.io": "nodejs",
    # python
    "django": "django", "flask": "flask", "fastapi": "fastapi", "tensorflow": "tensorflow",
    "torch": "pytorch", "scikit-learn": "sklearn", "opencv-python": "opencv", "psycopg2": "postgres",
    "psycopg2-binary": "postgres", "pymongo": "mongodb", "mysql-connector-python": "mysql",
    "pymysql": "mysql", "selenium": "selenium",
    # php / ruby / other
    "laravel/framework": "laravel", "rails": "rails",
}
TEXT_RULES = [  # substring inside pom.xml / build.gradle / pubspec etc.
    ("spring-boot", "spring"), ("mysql-connector", "mysql"), ("postgresql", "postgres"),
    ("mongodb", "mongodb"), ("hibernate", "hibernate"), ("firebase", "firebase"),
    ("junit", "java"),
]
TOPIC_ALIAS = {"reactjs": "react", "nodejs": "nodejs", "node": "nodejs", "javascript": "js",
               "typescript": "ts", "python": "py", "python3": "py", "nextjs": "nextjs",
               "tailwindcss": "tailwind", "expressjs": "express", "mongodb": "mongodb",
               "mysql": "mysql", "postgresql": "postgres", "firebase": "firebase", "docker": "docker",
               "flutter": "flutter", "springboot": "spring", "spring-boot": "spring", "laravel": "laravel",
               "django": "django", "flask": "flask", "aws": "aws", "azure": "azure", "gcp": "gcp",
               "figma": "figma", "kotlin": "kotlin", "android": "androidstudio", "vue": "vue",
               "vuejs": "vue", "angular": "angular", "redux": "redux", "graphql": "graphql",
               "arduino": "arduino", "unity": "unity", "linux": "linux", "supabase": "supabase"}

GROUPS = [
    ("Languages", None),
    ("Frameworks & libraries", {"react", "nextjs", "vue", "nuxtjs", "svelte", "angular", "express",
        "nestjs", "tailwind", "bootstrap", "sass", "redux", "threejs", "jquery", "electron", "materialui",
        "django", "flask", "fastapi", "tensorflow", "pytorch", "sklearn", "opencv", "spring", "hibernate",
        "laravel", "rails", "flutter", "nodejs", "graphql", "jest", "selenium", "unity", "arduino"}),
    ("Databases & cloud", {"mysql", "postgres", "mongodb", "sqlite", "redis", "prisma", "firebase",
        "supabase", "aws", "azure", "gcp", "vercel", "netlify", "docker", "kubernetes", "nginx",
        "githubactions"}),
    ("Tools", None),  # everything else
]
LANG_ICONS = set(LANG_ICON.values())

def detect_stack(data):
    lang_bytes, used = Counter(), Counter()
    for repo in data["user"]["repositories"]["nodes"]:
        icons = set()
        for e in repo["languages"]["edges"]:
            if e["node"]["name"] in LANG_ICON:
                lang_bytes[LANG_ICON[e["node"]["name"]]] += e["size"]
        for t in repo["repositoryTopics"]["nodes"]:
            name = t["topic"]["name"].lower()
            if name in TOPIC_ALIAS:
                icons.add(TOPIC_ALIAS[name])
        f = data["files"].get(repo["name"], {})
        for p in f.get("paths", []):
            for rx, icon in FILE_RULES:
                if re.search(rx, p):
                    icons.add(icon)
        for p, text in f.get("contents", {}).items():
            deps = set()
            if p.endswith(".json"):
                try:
                    j = json.loads(text)
                    for k in ("dependencies", "devDependencies", "require", "peerDependencies"):
                        deps |= {d.lower() for d in (j.get(k) or {})}
                except ValueError:
                    pass
            else:
                for line in text.splitlines():
                    m = re.match(r"\s*['\"]?([A-Za-z0-9_.\-/]+)", line)
                    if m and not line.strip().startswith("#"):
                        deps.add(m.group(1).lower())
                low = text.lower()
                for needle, icon in TEXT_RULES:
                    if needle in low:
                        icons.add(icon)
            icons |= {DEP_RULES[d] for d in deps if d in DEP_RULES}
        for i in icons:
            used[i] += 1
    hide = set(CFG.get("hide_stack", []))
    langs = [i for i, _ in lang_bytes.most_common() if i not in hide]
    other = [i for i, _ in sorted(used.items(), key=lambda kv: (-kv[1], kv[0]))
             if i not in hide and i not in langs and i not in LANG_ICONS]
    langs += [i for i in used if i in LANG_ICONS and i not in langs and i not in hide]
    for extra in CFG.get("extra_stack", []):
        if extra not in other and extra not in langs and extra not in hide:
            other.append(extra)
    if CFG.get("divide_stack", False):
        out = []
        for title, members in GROUPS:
            if title == "Languages":
                items = langs
            elif members is None:
                taken = set().union(*(m for _, m in GROUPS if m))
                items = [i for i in other if i not in taken]
            else:
                items = [i for i in other if i in members]
            if items:
                out.append((title, items))
        return out
    else:
        combined = []
        for i in langs + other:
            if i not in combined and i not in hide:
                combined.append(i)
        return combined

def stack_md(groups):
    if not groups:
        return "_Nothing detected yet._"
    if isinstance(groups, list) and groups and isinstance(groups[0], tuple):
        rows = []
        for title, items in groups:
            ids = ",".join(items)
            enc_ids = "%2C".join(items)
            rows.append(
                f"<b>{title}</b><br/>\n"
                f'<picture><source media="(prefers-color-scheme: dark)" srcset="https://skillicons.dev/icons?i={enc_ids}&amp;theme=dark" />'
                f'<img alt="{html.escape(ids)}" src="https://skillicons.dev/icons?i={ids}&amp;theme=light" /></picture>')
        return "\n<br/><br/>\n".join(rows)
    else:
        per_line = 14
        chunks = [groups[i:i + per_line] for i in range(0, len(groups), per_line)]
        lines = []
        for chunk in chunks:
            raw_ids = ",".join(chunk)
            enc_ids = "%2C".join(chunk)
            lines.append(
                f'<picture>'
                f'<source media="(prefers-color-scheme: dark)" srcset="https://skillicons.dev/icons?i={enc_ids}&amp;theme=dark" />'
                f'<img alt="{html.escape(raw_ids)}" src="https://skillicons.dev/icons?i={raw_ids}&amp;theme=light" />'
                f'</picture>'
            )
        return "<br/>\n".join(lines)

# ------------------------------------------------------------------------- stats
def streaks(days):
    counts = [d["contributionCount"] for d in days]
    longest = run = 0
    for c in counts:
        run = run + 1 if c else 0
        longest = max(longest, run)
    cur, i = 0, len(counts) - 1
    if i >= 0 and counts[i] == 0:  # today not counted yet -> don't break the streak
        i -= 1
    while i >= 0 and counts[i]:
        cur += 1
        i -= 1
    return cur, longest

def compute_stats(data):
    u = data["user"]
    cc = u["contributionsCollection"]
    days = [d for w in cc["contributionCalendar"]["weeks"] for d in w["contributionDays"]]
    today = dt.date.today().isoformat()
    days = [d for d in days if d["date"] <= today]
    cur, longest = streaks(days)
    repos = u["repositories"]["nodes"]
    excl = set(CFG.get("exclude_languages", []))
    size, color = Counter(), {}
    for r in repos:
        for e in r["languages"]["edges"]:
            n = e["node"]["name"]
            if n not in excl:
                size[n] += e["size"]
                color[n] = e["node"]["color"] or "#8b949e"
    total = sum(size.values()) or 1
    langs = [(n, s / total * 100, color[n]) for n, s in size.most_common(8)]
    rest = 100 - sum(p for _, p, _ in langs)
    if rest > 0.05 and len(size) > 8:
        langs.append(("Other", rest, None))
    return {
        "metrics": [
            ("Contributions", cc["contributionCalendar"]["totalContributions"], "past year"),
            ("Commits", cc["totalCommitContributions"] + cc["restrictedContributionsCount"], "past year"),
            ("Pull requests", u["pullRequests"]["totalCount"], "all time"),
            ("Issues", u["issues"]["totalCount"], "all time"),
            ("Repositories", u["repositories"]["totalCount"], "public" if not CFG.get("include_private") else "owned"),
            ("Stars earned", sum(r["stargazerCount"] for r in repos), "all time"),
            ("Current streak", cur, "days"),
            ("Longest streak", longest, "days · past year"),
        ],
        "langs": langs,
    }

# Primer (GitHub's design system) colour tokens
THEMES = {
    "dark":  {"bg": "#0d1117", "border": "#3d444d", "fg": "#f0f6fc", "muted": "#9198a1",
              "other": "#656c76", "gap": "#0d1117"},
    "light": {"bg": "#ffffff", "border": "#d1d9e0", "fg": "#1f2328", "muted": "#59636e",
              "other": "#c8d1da", "gap": "#ffffff"},
}
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans',Helvetica,Arial,sans-serif"

def fmt(n):
    return f"{n/1000:.1f}k".replace(".0k", "k") if n >= 10000 else f"{n:,}"

def stats_svg(stats, theme):
    t = THEMES[theme]
    W, pad, cols = 800, 24, 4
    cw = (W - 2 * pad) / cols
    out = []
    y = pad
    for idx, (label, value, sub) in enumerate(stats["metrics"]):
        col, row = idx % cols, idx // cols
        x = pad + col * cw
        yy = y + row * 76
        out.append(f'<text x="{x:.0f}" y="{yy+14}" class="lbl">{html.escape(label)}</text>')
        out.append(f'<text x="{x:.0f}" y="{yy+44}" class="num">{fmt(value)}</text>')
        out.append(f'<text x="{x:.0f}" y="{yy+62}" class="sub">{html.escape(sub)}</text>')
    rows = (len(stats["metrics"]) + cols - 1) // cols
    y += rows * 76 + 8
    out.append(f'<line x1="{pad}" x2="{W-pad}" y1="{y}" y2="{y}" stroke="{t["border"]}" />')
    y += 28
    out.append(f'<text x="{pad}" y="{y}" class="h">Most used languages</text>')
    y += 16
    # language bar (GitHub repo-sidebar style)
    bw = W - 2 * pad
    out.append(f'<clipPath id="bar"><rect x="{pad}" y="{y}" width="{bw}" height="8" rx="4" /></clipPath><g clip-path="url(#bar)">')
    x = pad
    for name, pct, col in stats["langs"]:
        w = bw * pct / 100
        out.append(f'<rect x="{x:.2f}" y="{y}" width="{w:.2f}" height="8" fill="{col or t["other"]}" />')
        x += w
    # 2px separators between segments
    x = pad
    for name, pct, col in stats["langs"][:-1]:
        x += bw * pct / 100
        out.append(f'<rect x="{x-1:.2f}" y="{y}" width="2" height="8" fill="{t["gap"]}" />')
    out.append("</g>")
    y += 32
    lcols = 4
    lw = bw / lcols
    for i, (name, pct, col) in enumerate(stats["langs"]):
        cx = pad + (i % lcols) * lw
        cy = y + (i // lcols) * 24
        nm = name if len(name) <= 18 else name[:17] + "…"
        out.append(f'<circle cx="{cx+4:.0f}" cy="{cy-4}" r="4" fill="{col or t["other"]}" />')
        out.append(f'<text x="{cx+14:.0f}" y="{cy}" class="lang"><tspan class="b">{html.escape(nm)}</tspan>'
                   f'<tspan class="sub" dx="6">{pct:.1f}%</tspan></text>')
    H = y + ((len(stats["langs"]) - 1) // lcols) * 24 + pad - 4
    if not stats["langs"]:
        H = y
    style = (f".lbl{{font:600 13px {FONT};fill:{t['muted']}}}"
             f".num{{font:600 26px {FONT};fill:{t['fg']}}}"
             f".sub{{font:400 12px {FONT};fill:{t['muted']}}}"
             f".h{{font:600 14px {FONT};fill:{t['fg']}}}"
             f".lang{{font:400 12px {FONT};fill:{t['fg']}}}.b{{font-weight:600}}")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
            f'role="img" aria-label="GitHub stats for {USER}"><style>{style}</style>'
            f'<rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" rx="6" fill="{t["bg"]}" stroke="{t["border"]}" />'
            + "".join(out) + "</svg>\n")

# ---------------------------------------------------------------------- activity
def lucide(name, size=14):
    dark = f"https://api.iconify.design/lucide/{name}.svg?color=%23a78bfa"
    light = f"https://api.iconify.design/lucide/{name}.svg?color=%237c3aed"
    return f'<picture><source media="(prefers-color-scheme: dark)" srcset="{dark}" /><img src="{light}" width="{size}" height="{size}" align="center" /></picture>'

def activity_md(events):
    lines, seen = [], set()
    for e in events:
        repo = e.get("repo", {}).get("name", "")
        if not repo:
            continue
        link = f"[{repo}](https://github.com/{repo})"
        p, typ = e.get("payload", {}), e.get("type", "")
        created_at = e.get("created_at", "")[:10]
        try:
            d = dt.datetime.strptime(created_at, "%Y-%m-%d")
            when = f"{d.strftime('%b')} {d.day}"
        except Exception:
            when = ""
        when_str = f" <sub>· {when}</sub>" if when else ""

        if typ == "PushEvent":
            key = ("push", repo, created_at)
            if key in seen:
                continue
            seen.add(key)
            same = [x for x in events if x.get("type") == "PushEvent" and x.get("repo", {}).get("name") == repo
                    and x.get("created_at", "")[:10] == created_at]
            sizes = [x.get("payload", {}).get("size") for x in same]
            n = sum(s for s in sizes if isinstance(s, int)) if any(isinstance(s, int) for s in sizes) else None
            text = f"{lucide('git-commit')} Pushed {n} commit{'s' if n != 1 else ''} to {link}" if n else f"{lucide('git-commit')} Pushed to {link}"
        elif typ == "CreateEvent" and p.get("ref_type") == "repository":
            text = f"{lucide('folder-plus')} Created repository {link}"
        elif typ == "PullRequestEvent" and p.get("action") in ("opened", "closed", "merged"):
            pr = p.get("pull_request") or {}
            action = p.get("action")
            if action == "closed" and not pr.get("merged"):
                continue
            is_merged = (action == "merged" or pr.get("merged"))
            verb = "Merged" if is_merged else "Opened"
            icon = "git-merge" if is_merged else "git-pull-request"
            pr_num = pr.get("number") or p.get("number") or ""
            key = ("pr", repo, pr_num, verb)
            if key in seen:
                continue
            seen.add(key)
            pr_url = pr.get("html_url") or f"https://github.com/{repo}/pull/{pr_num}"
            text = f"{lucide(icon)} {verb} PR [#{pr_num}]({pr_url}) in {link}"
        elif typ == "IssuesEvent" and p.get("action") in ("opened", "closed"):
            iss = p.get("issue") or {}
            action = p.get("action")
            is_closed = (action == "closed")
            verb = "Closed" if is_closed else "Opened"
            icon = "check-circle-2" if is_closed else "alert-circle"
            iss_num = iss.get("number") or p.get("number") or ""
            key = ("issue", repo, iss_num, verb)
            if key in seen:
                continue
            seen.add(key)
            iss_url = iss.get("html_url") or f"https://github.com/{repo}/issues/{iss_num}"
            text = f"{lucide(icon)} {verb} issue [#{iss_num}]({iss_url}) in {link}"
        elif typ == "ReleaseEvent" and p.get("action") == "published":
            rel = p.get("release") or {}
            tag = rel.get("tag_name") or "release"
            rel_url = rel.get("html_url") or f"https://github.com/{repo}/releases/tag/{tag}"
            text = f"{lucide('tag')} Released [`{tag}`]({rel_url}) in {link}"
        elif typ == "WatchEvent":
            text = f"{lucide('star')} Starred {link}"
        elif typ == "ForkEvent":
            text = f"{lucide('git-fork')} Forked {link}"
        elif typ == "PublicEvent":
            text = f"{lucide('globe')} Made {link} public"
        else:
            continue
        lines.append(f"- {text}{when_str}")
        if len(lines) >= CFG.get("activity_lines", 6):
            break
    return "\n".join(lines) or "_No recent public activity._"

# -------------------------------------------------------------------------- main
def replace_section(text, name, body):
    pat = re.compile(rf"(<!--{name}:START-->)(.*?)(<!--{name}:END-->)", re.S)
    if not pat.search(text):
        sys.exit(f"README is missing the <!--{name}:START--> / <!--{name}:END--> markers")
    return pat.sub(lambda m: f"{m.group(1)}\n{body}\n{m.group(3)}", text)

def main():
    if "--mock" in sys.argv:
        data = json.load(open(sys.argv[sys.argv.index("--mock") + 1]))
    else:
        data = fetch()
    stats = compute_stats(data)
    os.makedirs(os.path.join(ROOT, "assets"), exist_ok=True)
    for theme in THEMES:
        with open(os.path.join(ROOT, "assets", f"stats-{theme}.svg"), "w") as f:
            f.write(stats_svg(stats, theme))
    path = os.path.join(ROOT, "README.md")
    readme = open(path, encoding="utf-8").read()
    readme = replace_section(readme, "STACK", stack_md(detect_stack(data)))
    readme = replace_section(readme, "ACTIVITY", activity_md(data["events"]))
    open(path, "w", encoding="utf-8").write(readme)
    print("profile updated")

if __name__ == "__main__":
    main()
