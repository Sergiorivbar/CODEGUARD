#!/usr/bin/env python3
"""CodeGuard: bot de revisión de código con IA para Pull Requests.

Obtiene el diff de una PR, lo envía a la API de Groq (gratuita, compatible
con OpenAI) para que un LLM lo revise, y publica el resultado como
comentario en la propia PR usando la API REST de GitHub.

Variables de entorno requeridas:
    GITHUB_TOKEN   - token de la API de GitHub (lo provee Actions automáticamente)
    GROQ_API_KEY   - API key de Groq (https://console.groq.com/keys)
    GITHUB_REPOSITORY - "owner/repo" (lo provee Actions automáticamente)

El número de PR se obtiene del evento de GitHub Actions (GITHUB_EVENT_PATH)
o, para pruebas locales, de la variable de entorno PR_NUMBER.
"""

import json
import os
import sys

import requests

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"
MAX_DIFF_CHARS = 12000
REQUEST_TIMEOUT = 60

SYSTEM_PROMPT = (
    "Eres un revisor de código senior, directo y objetivo. Analizas el diff de un "
    "Pull Request y respondes SIEMPRE en este formato Markdown:\n\n"
    "## Resumen\n"
    "(2-4 frases explicando qué hace el cambio)\n\n"
    "## Posibles bugs o problemas de lógica\n"
    "(lista con viñetas; si no ves ninguno, escribe exactamente: "
    "'No se detectaron problemas evidentes.')\n\n"
    "## Sugerencias de estilo y buenas prácticas\n"
    "(lista con viñetas; si no hay sugerencias, escribe exactamente: "
    "'Sin sugerencias adicionales.')\n\n"
    "Reglas importantes:\n"
    "- No inventes problemas que no existan en el diff. Si el código está bien, dilo claramente.\n"
    "- Sé conciso y específico, referenciando archivos cuando sea posible.\n"
    "- No repitas el diff completo en tu respuesta."
)


class ReviewError(Exception):
    """Error esperado y con mensaje legible para el usuario."""


def get_env(name, required=True):
    value = os.environ.get(name)
    if required and not value:
        raise ReviewError(f"Falta la variable de entorno requerida: {name}")
    return value


def get_pr_number():
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if event_path and os.path.isfile(event_path):
        with open(event_path, "r", encoding="utf-8") as f:
            event = json.load(f)
        pr_number = event.get("pull_request", {}).get("number") or event.get("number")
        if pr_number:
            return pr_number

    pr_number_env = os.environ.get("PR_NUMBER")
    if pr_number_env:
        return pr_number_env

    raise ReviewError("No se pudo determinar el número de la Pull Request.")


def fetch_pr_diff(repo, pr_number, github_token):
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github.v3.diff",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        raise ReviewError(f"Error de red al obtener el diff de la PR: {exc}") from exc

    if resp.status_code != 200:
        raise ReviewError(
            f"GitHub API devolvió {resp.status_code} al pedir el diff: {resp.text[:300]}"
        )
    return resp.text


def truncate_diff(diff, max_chars=MAX_DIFF_CHARS):
    if len(diff) <= max_chars:
        return diff, False
    return diff[:max_chars], True


def build_user_prompt(diff, was_truncated):
    notice = (
        "\n\n[NOTA: el diff fue truncado por longitud, esta es solo una parte del cambio completo.]"
        if was_truncated
        else ""
    )
    return (
        "Revisa el siguiente diff de un Pull Request y responde siguiendo el formato indicado.\n\n"
        f"```diff\n{diff}\n```{notice}"
    )


def call_groq(diff, was_truncated, api_key):
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(diff, was_truncated)},
        ],
        "temperature": 0.2,
        "max_tokens": 1024,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        raise ReviewError(f"Error de red al llamar a la API de Groq: {exc}") from exc

    if resp.status_code != 200:
        raise ReviewError(f"Groq API devolvió {resp.status_code}: {resp.text[:300]}")

    try:
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, ValueError) as exc:
        raise ReviewError(f"Respuesta inesperada de Groq: {exc}") from exc


def format_comment(review_text):
    return (
        "## 🤖 CodeGuard AI Review\n\n"
        f"{review_text}\n\n"
        "<sub>Generado automáticamente por CodeGuard usando Groq · "
        f"modelo `{GROQ_MODEL}`. Puede cometer errores, revisa siempre con criterio humano.</sub>"
    )


def post_pr_comment(repo, pr_number, github_token, body):
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        resp = requests.post(url, headers=headers, json={"body": body}, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        raise ReviewError(f"Error de red al publicar el comentario en la PR: {exc}") from exc

    if resp.status_code not in (200, 201):
        raise ReviewError(
            f"GitHub API devolvió {resp.status_code} al publicar el comentario: {resp.text[:300]}"
        )


def main():
    try:
        github_token = get_env("GITHUB_TOKEN")
        groq_api_key = get_env("GROQ_API_KEY")
        repo = get_env("GITHUB_REPOSITORY")
        pr_number = get_pr_number()

        print(f"Obteniendo diff de la PR #{pr_number} en {repo}...")
        diff = fetch_pr_diff(repo, pr_number, github_token)

        if not diff or not diff.strip():
            print("El diff está vacío, no hay cambios que revisar. Publicando aviso.")
            post_pr_comment(
                repo,
                pr_number,
                github_token,
                format_comment("No se detectaron cambios en el diff de esta PR."),
            )
            return

        diff, was_truncated = truncate_diff(diff)
        if was_truncated:
            print(f"Diff truncado a {MAX_DIFF_CHARS} caracteres antes de enviarlo al modelo.")

        print("Enviando diff a Groq para revisión...")
        review_text = call_groq(diff, was_truncated, groq_api_key)

        print("Publicando comentario en la PR...")
        post_pr_comment(repo, pr_number, github_token, format_comment(review_text))
        print("Listo.")

    except ReviewError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
