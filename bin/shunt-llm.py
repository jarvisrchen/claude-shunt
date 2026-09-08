#!/usr/bin/env python3
"""Shared worker-model caller. Reads ~/.config/shunt/env, no third-party deps."""
import json, os, sys, urllib.request, urllib.error

ENV = os.path.expanduser("~/.config/shunt/env")

def load_env():
    if os.path.exists(ENV):
        for line in open(ENV):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v)

def call(provider, system, user, temperature=0.2, timeout=120):
    load_env()
    if provider.startswith("gemini"):
        model = provider if "-" in provider else "gemini-3.6-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": user}]}],
            "generationConfig": {"temperature": temperature, "thinkingConfig": {"thinkingLevel": "minimal"}},
        }
        headers = {"x-goog-api-key": os.environ["GEMINI_API_KEY"]}
        r = _post(url, body, headers, timeout)
        text = "".join(p.get("text", "") for p in r["candidates"][0]["content"]["parts"])
        u = r.get("usageMetadata", {})
        return text, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0)
    if provider.startswith("minimax"):
        model = {"minimax": "MiniMax-M2.5"}.get(provider, provider.replace("minimax:", ""))
        url = "https://api.minimax.io/v1/text/chatcompletion_v2"
        body = {"model": model, "temperature": temperature,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        headers = {"Authorization": "Bearer " + os.environ["MINIMAX_API_KEY"]}
        r = _post(url, body, headers, timeout)
        if r.get("base_resp", {}).get("status_code"):
            sys.exit(f"minimax error: {r['base_resp']}")
        u = r.get("usage", {})
        return r["choices"][0]["message"]["content"], u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
    sys.exit(f"unknown provider {provider}")

def _post(url, body, headers, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} from {url.split('?')[0]}: {e.read().decode()[:500]}")

def wrap_files(paths):
    parts = []
    for p in paths:
        try:
            parts.append(f'<file path="{p}">\n{open(p, errors="replace").read()}\n</file>')
        except OSError as e:
            parts.append(f'<file path="{p}" error="{e}"/>')
    return "\n".join(parts)

def strip_fences(s):
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else ""
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.rstrip() + "\n"
