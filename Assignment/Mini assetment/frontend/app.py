import os
import time

import requests
import streamlit as st

API_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8001").rstrip("/")

st.set_page_config(
    page_title="GitHub Repo Explainer",
    page_icon=":books:",
    layout="wide",
)


def fetch_health() -> dict | None:
    try:
        response = requests.get(f"{API_URL}/api/health", timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None


def explain_repo(repo_url: str, model: str | None) -> dict:
    payload = {"repo_url": repo_url}
    if model:
        payload["model"] = model
    response = requests.post(f"{API_URL}/api/explain", json=payload, timeout=1200)
    try:
        data = response.json()
    except ValueError:
        data = {"detail": response.text[:500]}
    if response.status_code != 200:
        detail = data.get("detail", "Unknown error")
        if isinstance(detail, list):
            detail = "; ".join(str(item) for item in detail)
        raise RuntimeError(str(detail))
    return data


with st.sidebar:
    st.title("GitHub Repo Explainer")
    st.caption("")
    API_URL = st.text_input("Backend URL", value=API_URL, key="backend_url").rstrip("/")
    health = fetch_health()
    if health is None:
        st.error(f"Backend at {API_URL} is not reachable. Start it with scripts/run.ps1")
        models = []
        default_model = None
    else:
        if health["status"] == "ok":
            st.success("Backend and Ollama are ready")
        else:
            st.warning("Backend is running, but one dependency is missing")
        st.write("Git:", "available" if health["git_available"] else "missing")
        st.write(
            "Ollama:",
            "available" if health["ollama_available"] else f"not reachable ({health['ollama_host']})",
        )
        models = health["available_models"]
        default_model = health["default_model"]

st.title("Explain this GitHub Repository")
st.write("Paste a public GitHub repository URL and the local LLM will explain what the code does in simple language.")

repo_url = st.text_input(
    "GitHub repository URL",
    placeholder="https://github.com/username/repository",
    label_visibility="collapsed",
    key="repo_url",
)

model_options = ["Auto (server default)"] + models if models else ["Auto (server default)"]
model_choice = st.selectbox("Local model", model_options) if models else None
selected_model = None
if model_choice and model_choice != "Auto (server default)":
    selected_model = model_choice

run = st.button(
    "Explain this repository",
    type="primary",
    use_container_width=True,
    key="explain_button",
)

if run:
    if not repo_url.strip():
        st.error("Please enter a GitHub repository URL.")
    elif health is None:
        st.error("The backend is not running, so the repository cannot be explained.")
    else:
        started = time.time()
        with st.spinner(
            "Cloning the repository, reading the source code and asking the local LLM. This can take a minute or two on CPU..."
        ):
            try:
                result = explain_repo(repo_url.strip(), selected_model)
            except RuntimeError as exc:
                st.error(str(exc))
                st.stop()
            except requests.RequestException as exc:
                st.error(f"Could not reach the backend: {exc}")
                st.stop()

        st.session_state["result"] = result
        st.session_state["frontend_elapsed"] = round(time.time() - started, 2)

result = st.session_state.get("result")
if result:
    st.divider()
    header_left, header_right = st.columns([4, 1])
    header_left.subheader(f"{result['project_name']} — what the code does")
    header_right.caption(
        f"model: {result['model_used']}\n\nfiles: {result['files_analysed']}\n\n{result['elapsed_seconds']}s"
    )

    st.markdown(result["explanation"])

    with st.expander(f"Source files analysed ({result['files_analysed']})"):
        languages = ", ".join(f"{name} ({count})" for name, count in result["languages"].items())
        st.write("Detected languages:", languages or "unknown")
        for item in result["files"]:
            st.write(f"- `{item['path']}` — {item['language']}, {item['chars']} chars")
else:
    st.info("Enter a repository URL and press the button to generate an explanation.")
