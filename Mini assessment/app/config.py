import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", str(BASE_DIR)))
TOOLS_DIR = Path(os.environ.get("MINIPROJECT_TOOLS", str(LOCALAPPDATA / "miniproject-tools")))
REPOS_DIR = Path(os.environ.get("MINIPROJECT_REPOS_DIR", str(BASE_DIR / "cloned_repos")))

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:1.5b")

MAX_FILES = int(os.environ.get("MAX_FILES", "50"))
MAX_FILE_CHARS = int(os.environ.get("MAX_FILE_CHARS", "4000"))
MAX_TOTAL_CHARS = int(os.environ.get("MAX_TOTAL_CHARS", "26000"))
LLM_TIMEOUT_SECONDS = int(os.environ.get("LLM_TIMEOUT_SECONDS", "900"))
LLM_CONTEXT_TOKENS = int(os.environ.get("LLM_CONTEXT_TOKENS", "8192"))

LLM_BACKEND = os.environ.get("LLM_BACKEND", "auto").strip().lower()
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or os.environ.get("GROQ_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "llama-3.1-8b-instant")

JOB_TTL_SECONDS = int(os.environ.get("JOB_TTL_SECONDS", "3600"))
MAX_JOBS = int(os.environ.get("MAX_JOBS", "20"))

GIT_CANDIDATES = [
    TOOLS_DIR / "MinGit" / "cmd" / "git.exe",
    TOOLS_DIR / "MinGit" / "mingw64" / "bin" / "git.exe",
    TOOLS_DIR / "git" / "cmd" / "git.exe",
]


def _clear_readonly(path: Path) -> None:
    for root, dirnames, filenames in os.walk(path, onerror=lambda _: None):
        for name in filenames + dirnames:
            try:
                os.chmod(Path(root) / name, stat.S_IWRITE | stat.S_IREAD)
            except OSError:
                continue


def safe_rmtree(path: str | Path, attempts: int = 4) -> bool:
    target = Path(path)
    if not target.exists():
        return True
    for attempt in range(attempts):
        try:
            shutil.rmtree(target)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            _clear_readonly(target)
            time.sleep(0.5 * (attempt + 1))
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(target)], capture_output=True)
    else:
        shutil.rmtree(target, ignore_errors=True)
    return not target.exists()


def prepare_repos_dir() -> None:
    if not REPOS_DIR.exists():
        REPOS_DIR.mkdir(parents=True, exist_ok=True)
        return
    for child in REPOS_DIR.iterdir():
        safe_rmtree(child, attempts=2)


def find_git_executable() -> str | None:
    env_git = os.environ.get("GIT_PYTHON_GIT_EXECUTABLE")
    if env_git and Path(env_git).exists():
        return env_git
    for candidate in GIT_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    which = shutil.which("git")
    return which


def configure_git() -> tuple[bool, str]:
    os.environ.setdefault("GIT_TERMINAL_PROMPT", "0")
    os.environ.setdefault("GCM_INTERACTIVE", "never")
    os.environ.setdefault("GIT_ASKPASS", "echo")
    git_path = find_git_executable()
    if not git_path:
        return False, "git executable not found"
    os.environ["GIT_PYTHON_GIT_EXECUTABLE"] = git_path
    try:
        import git
    except ImportError:
        return False, "GitPython is not installed (pip install gitpython)"
    try:
        git.refresh(git_path)
    except (OSError, ValueError) as exc:
        return False, f"git found at {git_path} but GitPython could not use it: {exc}"
    return True, git_path
