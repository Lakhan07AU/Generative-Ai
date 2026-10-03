import requests

from . import config

SYSTEM_PROMPT = (
    "You are a friendly senior software engineer who explains codebases to beginners. "
    "You always answer in simple, plain English and never invent features that are not "
    "supported by the code you were given."
)


class LLMError(Exception):
    pass


def is_ollama_available(host: str | None = None) -> bool:
    try:
        response = requests.get(f"{host or config.OLLAMA_HOST}/api/tags", timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False


def backend(host: str | None = None) -> str:
    if config.LLM_BACKEND in ("ollama", "openai"):
        return config.LLM_BACKEND
    if is_ollama_available(host):
        return "ollama"
    if config.OPENAI_API_KEY:
        return "openai"
    return "none"


def is_available(host: str | None = None) -> bool:
    active = backend(host)
    if active == "ollama":
        return True
    if active == "openai":
        return bool(config.OPENAI_API_KEY)
    return False


def list_models(host: str | None = None) -> list[str]:
    if backend(host) == "openai":
        return [config.OPENAI_MODEL]
    try:
        response = requests.get(f"{host or config.OLLAMA_HOST}/api/tags", timeout=5)
        response.raise_for_status()
        return sorted(model["name"] for model in response.json().get("models", []))
    except (requests.RequestException, ValueError, KeyError):
        return []


def pick_model(preferred: str | None = None, host: str | None = None) -> str:
    if backend(host) == "openai":
        return preferred or config.OPENAI_MODEL
    models = list_models(host)
    if preferred:
        if any(model == preferred or model.split(":")[0] == preferred for model in models):
            return preferred
        raise LLMError(
            f"Model '{preferred}' is not available in Ollama. Installed models: {', '.join(models) or 'none'}. "
            f"Run: ollama pull {preferred}"
        )
    for candidate in (
        config.DEFAULT_MODEL,
        "qwen2.5:1.5b",
        "qwen2.5:0.5b",
        "phi3:mini",
        "llama3.2:1b",
        "gemma2:2b",
    ):
        if candidate in models:
            return candidate
    if models:
        return models[0]
    raise LLMError(f"No models are installed in Ollama. Run: ollama pull {config.DEFAULT_MODEL}")


def generate(
    prompt: str,
    model: str | None = None,
    system: str = SYSTEM_PROMPT,
    host: str | None = None,
    temperature: float = 0.2,
    num_predict: int = 900,
    repeat_penalty: float = 1.15,
) -> tuple[str, str]:
    active = backend(host)
    if active == "openai":
        return _generate_openai(prompt, model=model, system=system, temperature=temperature, num_predict=num_predict)
    if active == "none":
        raise LLMError(
            f"No LLM is available: Ollama is not reachable at {config.OLLAMA_HOST} and OPENAI_API_KEY is not set. "
            "Start Ollama ('ollama serve') or set OPENAI_API_KEY (free key: https://console.groq.com/keys)."
        )
    return _generate_ollama(
        prompt,
        model=model,
        system=system,
        host=host,
        temperature=temperature,
        num_predict=num_predict,
        repeat_penalty=repeat_penalty,
    )


def _generate_openai(
    prompt: str,
    model: str | None,
    system: str,
    temperature: float,
    num_predict: int,
) -> tuple[str, str]:
    key = config.OPENAI_API_KEY
    if not key:
        raise LLMError("OPENAI_API_KEY is not set. Get a free key at https://console.groq.com/keys")
    selected = model or config.OPENAI_MODEL
    payload = {
        "model": selected,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": num_predict,
        "top_p": 0.9,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        response = requests.post(
            f"{config.OPENAI_BASE_URL}/chat/completions",
            json=payload,
            headers=headers,
            timeout=config.LLM_TIMEOUT_SECONDS,
        )
    except requests.Timeout as exc:
        raise LLMError(f"The LLM API did not respond within {config.LLM_TIMEOUT_SECONDS} seconds.") from exc
    except requests.RequestException as exc:
        raise LLMError(f"Could not reach the LLM API at {config.OPENAI_BASE_URL}: {exc}") from exc
    if response.status_code in (401, 403):
        raise LLMError(
            f"The LLM API rejected the API key (HTTP {response.status_code}). Check the OPENAI_API_KEY value."
        )
    if response.status_code == 429:
        raise LLMError("The free LLM API rate limit was reached (HTTP 429). Wait a moment and try again.")
    if response.status_code != 200:
        raise LLMError(f"The LLM API returned HTTP {response.status_code}: {response.text[:400]}")
    try:
        text = response.json()["choices"][0]["message"]["content"].strip()
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMError("The LLM API returned a response that could not be parsed.") from exc
    if not text:
        raise LLMError("The LLM API returned an empty explanation.")
    return text, selected


def _generate_ollama(
    prompt: str,
    model: str | None,
    system: str,
    host: str | None,
    temperature: float,
    num_predict: int,
    repeat_penalty: float,
) -> tuple[str, str]:
    host = host or config.OLLAMA_HOST
    if not is_ollama_available(host):
        raise LLMError(f"Ollama is not reachable at {host}. Start it with 'ollama serve' or open the Ollama app.")
    selected = pick_model(model, host)
    payload = {
        "model": selected,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_ctx": config.LLM_CONTEXT_TOKENS,
            "num_predict": num_predict,
            "repeat_penalty": repeat_penalty,
            "top_p": 0.9,
            "min_p": 0.05,
        },
    }
    try:
        response = requests.post(f"{host}/api/generate", json=payload, timeout=config.LLM_TIMEOUT_SECONDS)
    except requests.Timeout as exc:
        raise LLMError(f"The local LLM did not respond within {config.LLM_TIMEOUT_SECONDS} seconds.") from exc
    except requests.RequestException as exc:
        raise LLMError(f"Could not reach the local LLM at {host}: {exc}") from exc
    if response.status_code != 200:
        raise LLMError(f"Ollama returned HTTP {response.status_code}: {response.text[:400]}")
    try:
        text = response.json().get("response", "").strip()
    except ValueError as exc:
        raise LLMError("Ollama returned a response that could not be parsed.") from exc
    if not text:
        raise LLMError("The local LLM returned an empty explanation.")
    return text, selected


def build_prompt(repo_name: str, repo_url: str, files: list[dict], languages: dict[str, int]) -> str:
    file_listing = "\n".join(f"- {item['path']} ({item['language']})" for item in files)
    language_listing = ", ".join(f"{name}: {count}" for name, count in languages.items()) or "unknown"
    corpus = "\n".join(f"--- FILE: {item['path']} ---\n{item['content']}\n" for item in files)
    return f"""You are reviewing a GitHub repository. Explain it so that a student with basic programming knowledge can understand it.

Repository: {repo_name}
URL: {repo_url}
Detected languages: {language_listing}
Files provided ({len(files)}):
{file_listing}

SOURCE CODE:
{corpus}

Write the explanation in Markdown with exactly these sections:

# Project Overview
Two or three sentences describing what this repository is and the problem it solves.

# Features
A bullet list of the concrete things the application lets a user do, based on the actual code.

# Main Technologies
A bullet list of the languages, frameworks, libraries and database/tools the code uses.

# How It Works
A numbered, step-by-step story of the flow from user action to stored result, following the real code path.

# Project Structure
A short table or bullet list of the most important files and what each one is responsible for.

Rules:
- Use simple language, short sentences, and no unexplained jargon.
- Ground every claim in the source code above; if something is unclear, say so instead of guessing.
- Write about the application itself. Test files are only supporting evidence, so never list
  individual test cases and never turn the answer into a test catalogue.
- Never repeat a section or a bullet, and never pad the answer with filler.
- Do not mention that you were given code snippets or a prompt.
- Keep the whole answer under about 450 words and stop after the Project Structure section."""
