import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
BACKEND = "http://127.0.0.1:8001"
REPO_URL = sys.argv[1] if len(sys.argv) > 1 else "https://github.com/pallets/click"


def check_health() -> dict:
    response = requests.get(f"{BACKEND}/api/health", timeout=15)
    response.raise_for_status()
    return response.json()


def check_backend_api() -> dict:
    started = time.time()
    response = requests.post(f"{BACKEND}/api/explain", json={"repo_url": REPO_URL}, timeout=900)
    elapsed = round(time.time() - started, 1)
    if response.status_code != 200:
        raise SystemExit(f"backend failed: HTTP {response.status_code} {response.text[:500]}")
    data = response.json()
    print(
        f"backend ok: {data['project_name']} | files={data['files_analysed']} | model={data['model_used']} | {elapsed}s"
    )
    print(f"explanation chars={len(data['explanation'])}")
    return data


def check_frontend() -> None:
    sys.path.insert(0, str(ROOT))
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "frontend" / "app.py"), default_timeout=300)
    at.run()
    if at.exception:
        raise SystemExit(f"frontend failed to start: {at.exception}")
    at.text_input(key="repo_url").set_value(REPO_URL)
    at.button(key="explain_button").click()
    at.run(timeout=600)
    if at.exception:
        raise SystemExit(f"frontend crashed: {at.exception}")
    body = "\n".join(markdown.value for markdown in at.markdown)
    if "Project Overview" not in body:
        raise SystemExit(f"frontend did not render an explanation: {body[:400]}")
    print(f"frontend ok: rendered {len(body)} chars of markdown")


def main() -> None:
    health = check_health()
    print(
        f"health: status={health['status']} git={health['git_available']} ollama={health['ollama_available']} models={health['available_models']}"
    )
    check_backend_api()
    check_frontend()
    print("ALL SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
