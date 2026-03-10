#!/usr/bin/env python3
"""Stress test: generate 500 synthetic files and test tidyup scan against them."""

from __future__ import annotations

import argparse
import io
import random
import shutil
import struct
import subprocess
import sys
import time
import zipfile
import zlib
from pathlib import Path

# ---------------------------------------------------------------------------
# Word pools for realistic filenames
# ---------------------------------------------------------------------------
FIRST_NAMES = ["alice", "bob", "charlie", "dana", "eve", "frank", "grace", "hector"]
NOUNS = [
    "report",
    "invoice",
    "summary",
    "analysis",
    "budget",
    "proposal",
    "contract",
    "memo",
    "schedule",
    "meeting",
    "presentation",
    "backup",
    "export",
    "log",
    "manifest",
    "receipt",
    "statement",
    "transcript",
]
ADJECTIVES = ["final", "draft", "updated", "old", "new", "revised", "internal", "external"]
PROJECTS = ["atlas", "phoenix", "nova", "titan", "mercury", "helios", "orion", "vega"]

# ---------------------------------------------------------------------------
# Text content pools
# ---------------------------------------------------------------------------
TEXT_PARAGRAPHS = [
    "Meeting notes from the weekly standup. Action items: update the dashboard, "
    "review Q3 projections, schedule follow-up with marketing team.",
    "TODO:\n- Fix login page CSS\n- Add unit tests for payment module\n- Deploy staging build\n"
    "- Update API documentation",
    "Expense report for March 2025. Travel: $1,240.00. Meals: $180.50. "
    "Hotel: $890.00. Total: $2,310.50.",
    "Dear team,\n\nPlease find attached the quarterly sales figures. "
    "Revenue is up 12% compared to last quarter. Key drivers include...",
    "Project timeline:\n  Phase 1 (Jan-Mar): Research & Discovery\n"
    "  Phase 2 (Apr-Jun): Design & Prototyping\n  Phase 3 (Jul-Sep): Development",
    "System changelog v2.4.1:\n- Fixed memory leak in worker pool\n"
    "- Added retry logic for API timeouts\n- Upgraded TLS to 1.3",
    "Interview notes — Candidate: Jane D.\nStrengths: distributed systems, Go, Kubernetes.\n"
    "Areas to probe: frontend experience, team leadership.",
    "Brainstorm ideas for Q4 campaign:\n1. Social media video series\n"
    "2. Email drip campaign\n3. Partner co-marketing\n4. Webinar series",
    "Server inventory:\n  web-01: 16 vCPU, 64 GB RAM, us-east-1\n"
    "  db-01: 8 vCPU, 128 GB RAM, us-east-1\n  cache-01: 4 vCPU, 32 GB RAM",
    "Release checklist:\n[ ] All tests pass\n[ ] CHANGELOG updated\n"
    "[ ] Version bumped\n[ ] Docker image built\n[ ] Deployed to staging",
    "Customer feedback summary (Feb 2025):\n- 78% satisfaction score\n"
    "- Top complaint: slow page loads\n- Most requested feature: dark mode",
    "Onboarding guide:\n1. Set up SSH keys\n2. Clone the mono-repo\n"
    "3. Run bootstrap.sh\n4. Read CONTRIBUTING.md\n5. Join #dev-general",
    "Architecture decision record: ADR-042\nTitle: Migrate to event-driven architecture\n"
    "Status: Accepted\nContext: Current request-response model...",
    "Weekly metrics:\n  DAU: 24,500 (+3%)\n  Signups: 1,120\n  Churn: 2.1%\n  MRR: $48,200",
    "Legal disclaimer: This document is confidential and intended solely for "
    "the use of the individual or entity to whom it is addressed.",
]

CODE_SNIPPETS: dict[str, list[str]] = {
    ".py": [
        "def calculate_tax(income: float, rate: float = 0.25) -> float:\n"
        '    """Calculate tax on income."""\n    return round(income * rate, 2)\n',
        "import logging\n\nlog = logging.getLogger(__name__)\n\n\n"
        "class DataProcessor:\n    def __init__(self, config: dict) -> None:\n"
        "        self.config = config\n        self._cache: dict = {}\n\n"
        "    def process(self, data: list) -> list:\n"
        '        log.info("Processing %d items", len(data))\n'
        "        return [self._transform(item) for item in data]\n",
        "from pathlib import Path\n\n\ndef read_csv(path: Path) -> list[dict]:\n"
        "    lines = path.read_text().splitlines()\n"
        '    headers = lines[0].split(",")\n'
        '    return [dict(zip(headers, row.split(","))) for row in lines[1:]]\n',
        "import asyncio\n\n\nasync def fetch_data(url: str) -> bytes:\n"
        '    reader, writer = await asyncio.open_connection("example.com", 443)\n'
        '    writer.write(b"GET / HTTP/1.1\\r\\n\\r\\n")\n'
        "    data = await reader.read(4096)\n    writer.close()\n    return data\n",
        "from dataclasses import dataclass\n\n\n@dataclass\nclass User:\n"
        "    name: str\n    email: str\n    age: int\n\n"
        "    @property\n    def is_adult(self) -> bool:\n        return self.age >= 18\n",
    ],
    ".js": [
        "function debounce(fn, delay) {\n  let timer;\n  return (...args) => {\n"
        "    clearTimeout(timer);\n    timer = setTimeout(() => fn(...args), delay);\n  };\n}\n",
        "const fetchData = async (url) => {\n  const res = await fetch(url);\n"
        "  if (!res.ok) throw new Error(`HTTP ${res.status}`);\n  return res.json();\n};\n",
        "class EventEmitter {\n  constructor() { this.listeners = {}; }\n"
        "  on(event, fn) { (this.listeners[event] ||= []).push(fn); }\n"
        "  emit(event, ...args) { (this.listeners[event] || []).forEach(fn => fn(...args)); }\n}\n",
        "const pipe = (...fns) => (x) => fns.reduce((acc, fn) => fn(acc), x);\n\n"
        "const double = (n) => n * 2;\nconst addOne = (n) => n + 1;\n"
        "const transform = pipe(double, addOne);\n",
    ],
    ".html": [
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n  <meta charset="UTF-8">\n'
        '  <title>Dashboard</title>\n  <link rel="stylesheet" href="styles.css">\n'
        "</head>\n<body>\n  <header><h1>Analytics Dashboard</h1></header>\n"
        '  <main id="app"></main>\n  <script src="app.js"></script>\n</body>\n</html>\n',
        "<!DOCTYPE html>\n<html>\n<head><title>Login</title></head>\n<body>\n"
        '  <form action="/login" method="POST">\n    <label>Email</label>\n'
        '    <input type="email" name="email" required>\n    <label>Password</label>\n'
        '    <input type="password" name="password" required>\n'
        '    <button type="submit">Sign In</button>\n  </form>\n</body>\n</html>\n',
    ],
    ".css": [
        ":root {\n  --primary: #3b82f6;\n  --bg: #f8fafc;\n}\n\n"
        "body {\n  font-family: system-ui, sans-serif;\n  background: var(--bg);\n"
        "  margin: 0;\n  padding: 2rem;\n}\n\n"
        ".card {\n  border-radius: 8px;\n  box-shadow: 0 1px 3px rgba(0,0,0,.1);\n"
        "  padding: 1.5rem;\n}\n",
        ".grid {\n  display: grid;\n"
        "  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));\n  gap: 1rem;\n}\n"
        ".btn { padding: .5rem 1rem; border: none; border-radius: 4px; cursor: pointer; }\n"
        ".btn-primary { background: var(--primary); color: white; }\n",
    ],
    ".sh": [
        '#!/usr/bin/env bash\nset -euo pipefail\n\necho "Deploying to production..."\n'
        "docker build -t myapp:latest .\n"
        "docker push registry.example.com/myapp:latest\n"
        'kubectl rollout restart deployment/myapp\necho "Done."\n',
        "#!/bin/bash\n# Backup script\nDATE=$(date +%Y%m%d)\n"
        'BACKUP_DIR="/backups/$DATE"\nmkdir -p "$BACKUP_DIR"\n'
        'pg_dump mydb | gzip > "$BACKUP_DIR/mydb.sql.gz"\n'
        'echo "Backup complete: $BACKUP_DIR"\n',
    ],
    ".sql": [
        "CREATE TABLE users (\n  id SERIAL PRIMARY KEY,\n"
        "  email VARCHAR(255) UNIQUE NOT NULL,\n"
        "  name VARCHAR(100) NOT NULL,\n"
        "  created_at TIMESTAMP DEFAULT NOW()\n);\n\n"
        "CREATE INDEX idx_users_email ON users(email);\n",
        "SELECT\n  u.name,\n  COUNT(o.id) AS order_count,\n"
        "  SUM(o.total) AS total_spent\nFROM users u\n"
        "JOIN orders o ON o.user_id = u.id\n"
        "WHERE o.created_at >= NOW() - INTERVAL '30 days'\n"
        "GROUP BY u.name\nORDER BY total_spent DESC\nLIMIT 20;\n",
    ],
}

CONFIG_TEMPLATES: dict[str, list[str]] = {
    ".yaml": [
        "server:\n  host: 0.0.0.0\n  port: 8080\n  workers: 4\n\n"
        "database:\n  url: postgres://localhost:5432/mydb\n  pool_size: 10\n\n"
        "logging:\n  level: info\n  format: json\n",
        "name: my-project\nversion: 1.2.0\n\ndependencies:\n"
        "  - requests>=2.28\n  - pydantic>=2.0\n\nscripts:\n"
        "  test: pytest tests/ -v\n  lint: ruff check .\n",
    ],
    ".toml": [
        '[project]\nname = "myapp"\nversion = "0.1.0"\n'
        'requires-python = ">=3.12"\n\n[build-system]\n'
        'requires = ["setuptools"]\nbuild-backend = "setuptools.build_meta"\n',
        '[tool.ruff]\nline-length = 100\ntarget-version = "py312"\n\n'
        '[tool.ruff.lint]\nselect = ["E", "W", "F", "I", "UP"]\n',
    ],
    ".ini": [
        "[DEFAULT]\ndebug = false\nlog_level = WARNING\n\n"
        "[database]\nhost = localhost\nport = 5432\nname = production\n\n"
        "[cache]\nbackend = redis\nttl = 3600\n",
    ],
    ".log": [
        "2025-03-01 08:15:22 INFO  Server started on port 8080\n"
        "2025-03-01 08:15:23 INFO  Connected to database\n"
        "2025-03-01 08:16:01 WARN  Slow query detected (1.2s): SELECT * FROM orders\n"
        "2025-03-01 08:17:45 ERROR Connection pool exhausted, retrying...\n"
        "2025-03-01 08:17:46 INFO  Connection recovered\n"
        "2025-03-01 08:20:00 INFO  Health check OK\n",
        "2025-03-09 14:00:01 INFO  Cron job started: cleanup_old_sessions\n"
        "2025-03-09 14:00:03 INFO  Deleted 142 expired sessions\n"
        "2025-03-09 14:00:03 INFO  Cron job completed in 2.1s\n",
    ],
    ".conf": [
        "worker_processes auto;\nevents { worker_connections 1024; }\n\n"
        "http {\n  server {\n    listen 80;\n    server_name example.com;\n"
        "    location / { proxy_pass http://localhost:8080; }\n  }\n}\n",
    ],
}

# ---------------------------------------------------------------------------
# Minimal valid binary file generators
# ---------------------------------------------------------------------------


def _make_png(rng: random.Random) -> bytes:
    """Minimal valid 1x1 transparent PNG."""
    # PNG signature
    sig = b"\x89PNG\r\n\x1a\n"

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)  # 1x1 RGB
    raw_data = zlib.compress(b"\x00" + bytes([rng.randint(0, 255) for _ in range(3)]))
    return sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", raw_data) + _chunk(b"IEND", b"")


def _make_jpg(rng: random.Random) -> bytes:
    """Minimal JFIF header + padding + EOI."""
    header = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    padding = bytes(rng.randint(0, 255) for _ in range(rng.randint(200, 500)))
    return header + padding + b"\xff\xd9"


def _make_gif(rng: random.Random) -> bytes:
    """Minimal GIF89a."""
    header = b"GIF89a"
    # Logical screen descriptor: 1x1, no GCT
    lsd = struct.pack("<HH", 1, 1) + b"\x00\x00\x00"
    # Image descriptor + minimal LZW
    img = b"\x2c" + struct.pack("<HHHH", 0, 0, 1, 1) + b"\x00"
    lzw = b"\x02\x02\x4c\x01\x00"
    return header + lsd + img + lzw + b"\x3b"


def _make_svg(rng: random.Random) -> bytes:
    """Simple SVG rectangle."""
    r, g, b = rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">\n'
        f'  <rect width="100" height="100" fill="rgb({r},{g},{b})"/>\n'
        f"</svg>\n"
    )
    return svg.encode()


def _make_zip(rng: random.Random, name: str) -> bytes:
    """Valid ZIP with a small text file inside."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        inner_name = f"content_{rng.randint(1000, 9999)}.txt"
        zf.writestr(inner_name, f"Archive: {name}\nGenerated for stress test.\n")
    return buf.getvalue()


def _make_mp3(rng: random.Random) -> bytes:
    """ID3v2 header + padding."""
    header = b"ID3\x04\x00\x00\x00\x00\x00\x00"
    return header + bytes(rng.randint(0, 255) for _ in range(rng.randint(500, 2000)))


def _make_mp4(rng: random.Random) -> bytes:
    """ftyp box header + padding."""
    ftyp = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
    return ftyp + bytes(rng.randint(0, 255) for _ in range(rng.randint(500, 2000)))


def _magic_bytes_stub(magic: bytes, rng: random.Random, size: int = 1024) -> bytes:
    """Magic bytes + zero padding to given size."""
    return magic + b"\x00" * (size - len(magic))


# ---------------------------------------------------------------------------
# File generation
# ---------------------------------------------------------------------------

# Category definitions: (ext, weight, content_fn_key)
CATEGORIES: list[tuple[str, list[tuple[str, int]]]] = [
    ("documents", [(".pdf", 30), (".txt", 30), (".md", 20)]),
    ("spreadsheets", [(".csv", 20), (".json", 12), (".xml", 8)]),
    ("images", [(".png", 25), (".jpg", 25), (".gif", 10), (".svg", 10)]),
    ("code", [(".py", 15), (".js", 10), (".html", 8), (".css", 7), (".sh", 5), (".sql", 5)]),
    ("media", [(".mp3", 15), (".mp4", 15)]),
    ("archives", [(".zip", 25)]),
    ("installers", [(".dmg", 10), (".pkg", 10)]),
    ("config", [(".yaml", 10), (".toml", 8), (".ini", 5), (".log", 7), (".conf", 5)]),
    ("misc", [(".docx", 6), (".exe", 5), (".iso", 5), (".woff", 4)]),
]

# Subdirectory structure with approximate file counts
SUBDIRS: list[tuple[str, int]] = [
    ("Projects", 30),
    ("Projects/2024", 15),
    ("Screenshots", 25),
    ("Work/Reports", 20),
    ("Old Downloads", 25),
    ("misc", 20),
    ("temp", 15),
]


def _filename_for_ext(ext: str, rng: random.Random, idx: int) -> str:
    """Generate a realistic filename for the given extension."""
    year = rng.choice([2023, 2024, 2025])
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    q = rng.choice(["Q1", "Q2", "Q3", "Q4"])
    name = rng.choice(NOUNS)
    adj = rng.choice(ADJECTIVES)
    person = rng.choice(FIRST_NAMES)
    project = rng.choice(PROJECTS)

    templates: dict[str, list[str]] = {
        ".pdf": [
            f"{name}-{q}-{year}.pdf",
            f"{adj}-{name}-{person}.pdf",
            f"tax-return-{year}.pdf",
            f"{project}-proposal-v{rng.randint(1, 5)}.pdf",
        ],
        ".txt": [
            f"notes-{year}-{month:02d}-{day:02d}.txt",
            f"{name}-{adj}.txt",
            f"todo-{person}.txt",
            f"readme-{project}.txt",
        ],
        ".md": [
            f"README-{project}.md",
            f"{name}-notes.md",
            f"changelog-v{rng.randint(1, 9)}.md",
            f"meeting-{year}-{month:02d}.md",
        ],
        ".csv": [
            f"sales-{q}-{year}.csv",
            f"users-export-{year}{month:02d}.csv",
            f"{project}-metrics.csv",
        ],
        ".json": [
            f"config-{project}.json",
            f"data-export-{year}.json",
            f"package-{rng.randint(1, 99)}.json",
        ],
        ".xml": [
            f"feed-{project}.xml",
            f"sitemap-{year}.xml",
            f"manifest-v{rng.randint(1, 5)}.xml",
        ],
        ".png": [
            f"screenshot-{year}-{month:02d}-{day:02d}.png",
            f"logo-{project}.png",
            f"chart-{q}-{name}.png",
            f"photo-{rng.randint(1000, 9999)}.png",
        ],
        ".jpg": [
            f"IMG_{rng.randint(1000, 9999)}.jpg",
            f"photo-{year}-{month:02d}-{day:02d}.jpg",
            f"scan-{name}-{idx}.jpg",
            f"headshot-{person}.jpg",
        ],
        ".gif": [
            f"animation-{rng.randint(1, 50)}.gif",
            "loading-spinner.gif",
            f"banner-{project}.gif",
        ],
        ".svg": [
            f"icon-{name}.svg",
            f"logo-{project}-{adj}.svg",
            f"diagram-{rng.randint(1, 20)}.svg",
        ],
        ".py": [
            f"{name}_{adj}.py",
            f"test_{project}.py",
            f"utils_{rng.randint(1, 10)}.py",
            f"deploy_{project}.py",
        ],
        ".js": [
            f"app-{project}.js",
            f"{name}-handler.js",
            f"utils-{rng.randint(1, 10)}.js",
        ],
        ".html": [
            f"index-{project}.html",
            f"dashboard-{adj}.html",
            f"page-{rng.randint(1, 20)}.html",
        ],
        ".css": [
            f"styles-{project}.css",
            f"theme-{adj}.css",
            f"components-{rng.randint(1, 5)}.css",
        ],
        ".sh": [
            f"deploy-{project}.sh",
            f"backup-{name}.sh",
            f"setup-{adj}.sh",
        ],
        ".sql": [
            f"migration-{rng.randint(1, 50):03d}.sql",
            f"schema-{project}.sql",
            f"query-{name}.sql",
        ],
        ".mp3": [
            f"podcast-ep{rng.randint(1, 100)}.mp3",
            f"recording-{year}-{month:02d}-{day:02d}.mp3",
            f"voice-memo-{person}.mp3",
        ],
        ".mp4": [
            f"meeting-recording-{year}-{month:02d}.mp4",
            f"demo-{project}-v{rng.randint(1, 5)}.mp4",
            f"tutorial-{name}.mp4",
        ],
        ".zip": [
            f"{project}-backup-{year}{month:02d}.zip",
            f"export-{name}-{q}.zip",
            f"archive-{adj}-{rng.randint(1, 99)}.zip",
        ],
        ".dmg": [
            f"{project}-installer-v{rng.randint(1, 9)}.{rng.randint(0, 9)}.dmg",
            f"setup-{name}.dmg",
        ],
        ".pkg": [
            f"{project}-{rng.randint(1, 5)}.{rng.randint(0, 9)}.pkg",
            f"update-{year}{month:02d}.pkg",
        ],
        ".yaml": [
            f"config-{project}.yaml",
            f"docker-compose-{adj}.yaml",
            "ci-pipeline.yaml",
        ],
        ".toml": [
            f"pyproject-{project}.toml",
            f"config-{adj}.toml",
            f"settings-{rng.randint(1, 5)}.toml",
        ],
        ".ini": [
            f"setup-{project}.ini",
            f"config-{adj}.ini",
        ],
        ".log": [
            f"server-{year}-{month:02d}-{day:02d}.log",
            f"error-{project}.log",
            f"access-{q}.log",
        ],
        ".conf": [
            f"nginx-{project}.conf",
            f"app-{adj}.conf",
        ],
        ".docx": [
            f"{name}-{adj}-{person}.docx",
            f"letter-{year}.docx",
        ],
        ".exe": [
            f"setup-{project}.exe",
            f"installer-v{rng.randint(1, 9)}.exe",
        ],
        ".iso": [
            f"ubuntu-{rng.choice(['22.04', '24.04'])}-desktop.iso",
            f"windows-{rng.randint(10, 11)}.iso",
        ],
        ".woff": [
            f"font-{rng.choice(['inter', 'roboto', 'opensans'])}.woff",
            f"icons-{project}.woff",
        ],
    }

    choices = templates.get(ext, [f"file-{idx}{ext}"])
    return rng.choice(choices)


def _content_for_file(ext: str, name: str, rng: random.Random) -> bytes:
    """Generate realistic content for a file based on its extension."""
    # Text documents
    if ext in (".txt", ".md"):
        return rng.choice(TEXT_PARAGRAPHS).encode()
    if ext == ".pdf":
        return b"%PDF-1.4\n" + rng.choice(TEXT_PARAGRAPHS).encode() + b"\n%%EOF\n"
    if ext == ".csv":
        headers = "date,category,amount,description"
        rows = [
            f"2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d},"
            f"{rng.choice(['sales', 'expense', 'refund'])},"
            f"{rng.uniform(10, 5000):.2f},"
            f"{rng.choice(NOUNS)} {rng.choice(ADJECTIVES)}"
            for _ in range(rng.randint(5, 20))
        ]
        return (headers + "\n" + "\n".join(rows) + "\n").encode()
    if ext == ".json":
        items = ", ".join(
            f'{{"id": {i}, "name": "{rng.choice(NOUNS)}", "value": {rng.randint(1, 100)}}}'
            for i in range(rng.randint(3, 10))
        )
        return f'{{"items": [{items}]}}\n'.encode()
    if ext == ".xml":
        entries = "\n".join(
            f'  <item id="{i}">{rng.choice(NOUNS)}</item>' for i in range(rng.randint(3, 8))
        )
        return f'<?xml version="1.0"?>\n<root>\n{entries}\n</root>\n'.encode()

    # Code files
    if ext in CODE_SNIPPETS:
        return rng.choice(CODE_SNIPPETS[ext]).encode()

    # Config files
    if ext in CONFIG_TEMPLATES:
        return rng.choice(CONFIG_TEMPLATES[ext]).encode()

    # Images
    if ext == ".png":
        return _make_png(rng)
    if ext == ".jpg":
        return _make_jpg(rng)
    if ext == ".gif":
        return _make_gif(rng)
    if ext == ".svg":
        return _make_svg(rng)

    # Archives
    if ext == ".zip":
        return _make_zip(rng, name)

    # Media
    if ext == ".mp3":
        return _make_mp3(rng)
    if ext == ".mp4":
        return _make_mp4(rng)

    # Binary stubs
    magic_map: dict[str, bytes] = {
        ".dmg": b"\x00" * 100,
        ".pkg": b"\x00" * 100,
        ".docx": b"PK\x03\x04",
        ".exe": b"MZ",
        ".iso": b"\x00" * 0x8000 + b"CD001",
        ".woff": b"wOFF",
    }
    if ext in magic_map:
        return _magic_bytes_stub(magic_map[ext], rng)

    return b"\x00" * 100


def generate_files(target_dir: Path, count: int, seed: int) -> float:
    """Generate synthetic test files. Returns generation time in seconds."""
    rng = random.Random(seed)
    t0 = time.monotonic()

    target_dir.mkdir(parents=True, exist_ok=True)

    # Build the extension pool based on weights
    ext_pool: list[str] = []
    for _cat, items in CATEGORIES:
        for ext, weight in items:
            ext_pool.extend([ext] * weight)

    # Reserve slots for duplicates (last ~30 files)
    num_duplicates = min(30, count // 15)
    num_unique = count - num_duplicates

    # Create subdirectory structure
    subdirs = [(target_dir / d, n) for d, n in SUBDIRS]
    for d, _ in subdirs:
        d.mkdir(parents=True, exist_ok=True)

    # Decide which files go into subdirs (~30% of unique files)
    subdir_slots: list[Path] = []
    for d, n in subdirs:
        adjusted = min(n, int(n * num_unique / 500))
        subdir_slots.extend([d] * adjusted)
    rng.shuffle(subdir_slots)

    generated_files: list[Path] = []
    used_names: set[str] = set()

    for i in range(num_unique):
        ext = rng.choice(ext_pool)
        # Generate unique filename
        for _attempt in range(20):
            name = _filename_for_ext(ext, rng, i)
            if name not in used_names:
                break
        else:
            name = f"file-{i}-{rng.randint(1000, 9999)}{ext}"
        used_names.add(name)

        # Pick directory
        directory = subdir_slots[i] if subdir_slots and i < len(subdir_slots) else target_dir

        path = directory / name
        # Handle collisions within subdirs
        if path.exists():
            stem = path.stem
            path = directory / f"{stem}-{rng.randint(100, 999)}{ext}"

        content = _content_for_file(ext, name, rng)
        path.write_bytes(content)
        generated_files.append(path)

    # Create duplicates: copy random files with variant names
    if generated_files and num_duplicates > 0:
        sources = rng.sample(generated_files, min(num_duplicates // 2, len(generated_files)))
        dup_count = 0
        for src in sources:
            if dup_count >= num_duplicates:
                break
            # Create 1-2 duplicates per source
            for suffix in ["Copy of {}", "{} (1)"]:
                if dup_count >= num_duplicates:
                    break
                dup_name = suffix.format(src.stem) + src.suffix
                dup_path = target_dir / dup_name
                if not dup_path.exists():
                    shutil.copy2(src, dup_path)
                    dup_count += 1

    elapsed = time.monotonic() - t0
    return elapsed


# ---------------------------------------------------------------------------
# Benchmark execution
# ---------------------------------------------------------------------------


def _count_files(target_dir: Path) -> int:
    """Count all non-hidden files recursively."""
    return sum(
        1
        for p in target_dir.rglob("*")
        if p.is_file() and not any(part.startswith(".") for part in p.parts)
    )


def run_stress_test(target_dir: Path, model: str, keep: bool) -> None:
    """Run the stress test against the generated files."""
    file_count = _count_files(target_dir)
    print(f"\nStress test: {file_count} files in {target_dir}\n")

    # Find tidyup executable — check venv first, then PATH
    project_root = Path(__file__).resolve().parent.parent
    venv_cmd = project_root / "venv" / "bin" / "tidyup"
    if venv_cmd.is_file():
        tidyup_cmd = str(venv_cmd)
    else:
        tidyup_cmd = shutil.which("tidyup")
    if not tidyup_cmd:
        print("ERROR: 'tidyup' not found in PATH or venv. Install with: pip install -e '.[dev]'")
        sys.exit(1)

    # Test 1: Full scan (dry-run) — exercises parallel organizer
    print("=" * 60)
    print("Test 1: tidyup scan --dry-run (parallel flow)")
    print("=" * 60)
    t0 = time.monotonic()
    result = subprocess.run(
        [tidyup_cmd, "--model", model, "scan", str(target_dir), "--dry-run"],
        capture_output=False,
        text=True,
    )
    scan_time = time.monotonic() - t0
    print(f"\nScan completed in {scan_time:.1f}s (exit code: {result.returncode})")

    # Summary
    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"  Files generated:    {file_count}")
    print(f"  Scan (dry-run):     {scan_time:.1f}s")
    print(f"  Model:              {model}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stress-test tidyup with a large synthetic file set.",
    )
    parser.add_argument("--count", type=int, default=500, help="Number of files (default: 500)")
    parser.add_argument("--model", default="gemma3:4b", help="Ollama model (default: gemma3:4b)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    parser.add_argument("--keep", action="store_true", help="Keep generated files after test")
    parser.add_argument(
        "--generate-only", action="store_true", help="Only generate files, skip test"
    )
    parser.add_argument("--dir", type=Path, help="Use existing dir instead of generating files")
    args = parser.parse_args()

    # Determine target directory
    project_root = Path(__file__).resolve().parent.parent
    default_dir = project_root / "stress_test_data"

    if args.dir:
        target_dir = args.dir.resolve()
        if not target_dir.is_dir():
            print(f"ERROR: {target_dir} is not a directory")
            sys.exit(1)
        generated = False
    else:
        target_dir = default_dir
        print(f"Generating {args.count} files (seed={args.seed}) in {target_dir}/ ...")
        gen_time = generate_files(target_dir, args.count, args.seed)
        file_count = _count_files(target_dir)
        print(f"Generated {file_count} files in {gen_time:.2f}s")
        generated = True

    if args.generate_only:
        print(f"\nFiles ready at: {target_dir}")
        return

    try:
        run_stress_test(target_dir, args.model, args.keep)
    finally:
        if generated and not args.keep:
            print(f"\nCleaning up {target_dir}/ ...")
            shutil.rmtree(target_dir, ignore_errors=True)
            print("Done.")
        elif args.keep or not generated:
            print(f"\nFiles preserved at: {target_dir}")


if __name__ == "__main__":
    main()
