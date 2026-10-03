import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import config

CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".kt",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".swift",
    ".m",
    ".mm",
    ".scala",
    ".sh",
    ".bash",
    ".ps1",
    ".sql",
    ".html",
    ".css",
    ".scss",
    ".vue",
    ".svelte",
    ".dart",
    ".r",
    ".jl",
    ".lua",
    ".pl",
    ".ex",
    ".exs",
    ".hs",
    ".ml",
    ".clj",
    ".groovy",
    ".asm",
    ".sol",
}

CONFIG_FILENAMES = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "setup.cfg",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "cargo.toml",
    "go.mod",
    "gemfile",
    "composer.json",
    "makefile",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "pipfile",
    "environment.yml",
    "tsconfig.json",
    ".env.example",
    "manage.py",
}

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "vendor",
    "venv",
    ".venv",
    "env",
    ".env",
    "__pycache__",
    "dist",
    "build",
    "target",
    "out",
    ".next",
    ".nuxt",
    ".idea",
    ".vscode",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".eggs",
    "eggs",
    "site-packages",
    "coverage",
    ".gradle",
    ".terraform",
    "bower_components",
    "Pods",
    "DerivedData",
    ".dart_tool",
    ".stack-work",
    "third_party",
    "assets",
    "static",
    "public",
    "images",
    "img",
    "fonts",
    "docs",
    "examples",
}

SKIP_FILENAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "cargo.lock",
    "gemfile.lock",
    "composer.lock",
    "pipfile.lock",
}

BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".svg",
    ".webp",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".7z",
    ".rar",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    ".dat",
    ".class",
    ".jar",
    ".war",
    ".pyc",
    ".pyo",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp3",
    ".mp4",
    ".avi",
    ".mov",
    ".wav",
    ".sqlite",
    ".db",
    ".pkl",
    ".pt",
    ".onnx",
    ".whl",
    ".nupkg",
    ".deb",
    ".rpm",
    ".iso",
    ".img",
    ".parquet",
    ".feather",
}

LANGUAGE_BY_EXTENSION = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".kt": "Kotlin",
    ".c": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".h": "C/C++",
    ".hpp": "C/C++",
    ".cs": "C#",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".m": "Objective-C",
    ".scala": "Scala",
    ".sh": "Shell",
    ".bash": "Shell",
    ".ps1": "PowerShell",
    ".sql": "SQL",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".dart": "Dart",
    ".r": "R",
    ".jl": "Julia",
    ".lua": "Lua",
    ".pl": "Perl",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".hs": "Haskell",
    ".ml": "OCaml",
    ".clj": "Clojure",
    ".json": "JSON",
    ".xml": "XML",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".toml": "TOML",
    ".md": "Markdown",
    ".txt": "Text",
}


class RepositoryError(Exception):
    pass


class CloneError(RepositoryError):
    pass


class ExtractionError(RepositoryError):
    pass


@dataclass
class ExtractedRepo:
    name: str
    url: str
    path: Path
    files: list[dict] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)
    total_files_seen: int = 0

    @property
    def file_list(self) -> list[str]:
        return [f["path"] for f in self.files]

    def build_corpus(self) -> str:
        parts = []
        for item in self.files:
            header = f"--- FILE: {item['path']} ---"
            parts.append(f"{header}\n{item['content']}\n")
        return "\n".join(parts)


def normalize_repo_url(url: str) -> str:
    cleaned = url.strip().rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    parts = cleaned.split("github.com/")[-1].split("/")
    if len(parts) < 2:
        raise CloneError(f"Could not read owner/repository from URL: {url}")
    owner, repo = parts[0], parts[1]
    return f"https://github.com/{owner}/{repo}", f"{owner}/{repo}"


def clone_repository(url: str, dest_root: Path | None = None) -> Path:
    git_ok, git_info = config.configure_git()
    if not git_ok:
        raise CloneError(
            f"Git is not available ({git_info}). Install Git or run scripts/setup.ps1 to bundle the portable MinGit."
        )
    import git

    clone_url, slug = normalize_repo_url(url)
    dest_root = Path(dest_root) if dest_root else config.REPOS_DIR
    dest_root.mkdir(parents=True, exist_ok=True)
    target = dest_root / f"{slug.replace('/', '__')}_{int(time.time())}"
    config.safe_rmtree(target)
    try:
        git.Repo.clone_from(clone_url, target, depth=1)
    except git.exc.GitError as exc:
        config.safe_rmtree(target)
        raise CloneError(friendly_clone_error(clone_url, exc)) from exc
    return target


def friendly_clone_error(clone_url: str, exc: Exception) -> str:
    text = str(exc)
    lowered = text.lower()
    if "authentication failed" in lowered or "invalid username" in lowered or "could not read username" in lowered:
        return f"Repository {clone_url} was not found on GitHub, or it is a private repository."
    if "could not resolve host" in lowered or "unable to access" in lowered:
        return f"Could not reach GitHub while cloning {clone_url}. Check the internet connection."
    if "not a valid" in lowered or "repository not found" in lowered:
        return f"Repository {clone_url} does not exist."
    tail = text.strip().splitlines()[-1] if text.strip() else "unknown git error"
    return f"Failed to clone {clone_url}: {tail}"


TEST_DIR_NAMES = {"test", "tests", "testing", "spec", "specs", "__tests__", "testdata", "fixtures"}
SECONDARY_DIR_NAMES = {
    "docs",
    "doc",
    "examples",
    "example",
    "benchmarks",
    "benchmark",
    "scripts",
    "migrations",
    "design",
    "demo",
    "demos",
}
ENTRY_STEMS = {
    "main",
    "app",
    "index",
    "server",
    "cli",
    "manage",
    "__main__",
    "application",
    "run",
    "start",
    "router",
    "views",
}
SECONDARY_STEMS = {
    "changelog",
    "contributing",
    "license",
    "licence",
    "authors",
    "code_of_conduct",
    "history",
    "news",
    "changes",
}
CATEGORY_ORDER = ["readme", "manifest", "entry", "source", "config", "test", "secondary"]
CATEGORY_LIMITS = {"readme": 1, "manifest": 6, "entry": 6, "source": 32, "config": 6, "test": 4, "secondary": 2}
CATEGORY_CHAR_CAPS = {
    "readme": 3000,
    "manifest": 1800,
    "entry": 4000,
    "source": 4000,
    "config": 1500,
    "test": 2500,
    "secondary": 1500,
}


def _is_skippable_dir(name: str) -> bool:
    lowered = name.lower()
    return lowered in SKIP_DIRS or lowered.startswith(".")


def _read_text(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw[:4096]:
        return None
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _language_for(path: Path) -> str:
    return LANGUAGE_BY_EXTENSION.get(
        path.suffix.lower(),
        path.name.rsplit(".", 1)[-1].upper() if path.suffix else "Text",
    )


def _category(path: Path, root: Path) -> str:
    name = path.name.lower()
    stem = path.stem.lower()
    parts = [part.lower() for part in path.relative_to(root).parts[:-1]]
    if name.startswith("readme"):
        return "readme"
    if name in CONFIG_FILENAMES:
        return "manifest"
    if any(part in TEST_DIR_NAMES for part in parts) or stem.startswith("test_") or stem.endswith("_test"):
        return "test"
    if stem in ENTRY_STEMS:
        return "entry"
    if any(part in SECONDARY_DIR_NAMES for part in parts) or stem in SECONDARY_STEMS:
        return "secondary"
    if path.suffix.lower() in CODE_EXTENSIONS:
        return "source"
    return "config"


def os_walk(root: Path):
    import os

    return os.walk(root)


def _collect_candidates(root: Path) -> tuple[list[tuple[Path, str]], int]:
    candidates: list[tuple[Path, str]] = []
    seen = 0
    for current, dirnames, filenames in os_walk(root):
        dirnames[:] = sorted(d for d in dirnames if not _is_skippable_dir(d))
        for filename in sorted(filenames):
            path = Path(current) / filename
            if filename.lower() in SKIP_FILENAMES:
                continue
            suffix = path.suffix.lower()
            if suffix in BINARY_EXTENSIONS:
                continue
            name_lower = filename.lower()
            is_known = name_lower in CONFIG_FILENAMES or name_lower.startswith("readme")
            if (
                suffix not in CODE_EXTENSIONS
                and not is_known
                and suffix not in {".json", ".yml", ".yaml", ".toml", ".xml", ".md"}
            ):
                continue
            try:
                if path.stat().st_size > 400_000:
                    continue
            except OSError:
                continue
            seen += 1
            candidates.append((path, _category(path, root)))
    return candidates, seen


def _choose_files(root: Path) -> tuple[list[tuple[Path, str]], int]:
    candidates, seen = _collect_candidates(root)
    grouped: dict[str, list[tuple[Path, str]]] = {name: [] for name in CATEGORY_ORDER}
    for path, category in candidates:
        grouped[category].append((path, category))

    chosen: list[tuple[Path, str]] = []
    for category in CATEGORY_ORDER:
        bucket = sorted(
            grouped[category], key=lambda item: (len(item[0].relative_to(root).parts), -item[0].stat().st_size)
        )
        for item in bucket[: CATEGORY_LIMITS[category]]:
            if len(chosen) >= config.MAX_FILES:
                return chosen, seen
            chosen.append(item)
    return chosen, seen


def extract_repository(url: str, dest_root: Path | None = None) -> ExtractedRepo:
    root = clone_repository(url, dest_root)
    try:
        _, slug = normalize_repo_url(url)
        repo = ExtractedRepo(name=slug.split("/")[-1], url=url, path=root)
        chosen, seen = _choose_files(root)
        repo.total_files_seen = seen

        total_chars = 0
        for path, category in chosen:
            content = _read_text(path)
            if content is None:
                continue
            cap = min(config.MAX_FILE_CHARS, CATEGORY_CHAR_CAPS[category])
            content = content[:cap]
            if total_chars + len(content) > config.MAX_TOTAL_CHARS:
                if total_chars == 0:
                    content = content[: config.MAX_TOTAL_CHARS]
                else:
                    continue
            total_chars += len(content)
            relative = str(path.relative_to(root)).replace("\\", "/")
            repo.files.append({"path": relative, "content": content, "language": _language_for(path)})
            repo.languages[_language_for(path)] = repo.languages.get(_language_for(path), 0) + 1

        if not repo.files:
            raise ExtractionError("No readable source-code files were found in this repository.")
        return repo
    finally:
        config.safe_rmtree(root)


def languages_summary(files: list[dict]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for item in files:
        summary[item["language"]] = summary.get(item["language"], 0) + 1
    return dict(sorted(summary.items(), key=lambda kv: kv[1], reverse=True))
