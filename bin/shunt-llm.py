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
                v = v.split(" #", 1)[0].strip()
                os.environ.setdefault(k, v)

def need(var):
    v = os.environ.get(var)
    if not v:
        sys.exit(f"shunt: {var} is empty. Set it in {ENV}, or pick a provider whose key you have "
                 f"(SHUNT_READ_PROVIDER / SHUNT_WRITE_PROVIDER in that same file).")
    return v

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
        headers = {"x-goog-api-key": need("GEMINI_API_KEY")}
        r = _post(url, body, headers, timeout)
        text = "".join(p.get("text", "") for p in r["candidates"][0]["content"]["parts"])
        u = r.get("usageMetadata", {})
        return text, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0)
    if provider.startswith("minimax"):
        model = {"minimax": "MiniMax-M3"}.get(provider, provider.replace("minimax:", ""))
        url = "https://api.minimax.io/v1/text/chatcompletion_v2"
        body = {"model": model, "temperature": temperature, "thinking": {"type": "disabled"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        headers = {"Authorization": "Bearer " + need("MINIMAX_API_KEY")}
        r = _post(url, body, headers, timeout)
        if r.get("base_resp", {}).get("status_code"):
            sys.exit(f"minimax error: {r['base_resp']}")
        u = r.get("usage", {})
        return r["choices"][0]["message"]["content"], u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
    if provider.startswith("claude"):
        model = {"claude": "claude-haiku-4-5"}.get(provider, provider.replace("claude:", ""))
        url = "https://api.anthropic.com/v1/messages"
        body = {"model": model, "max_tokens": 4096, "temperature": temperature,
                "system": system, "messages": [{"role": "user", "content": user}]}
        headers = {"x-api-key": need("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"}
        r = _post(url, body, headers, timeout)
        text = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
        u = r.get("usage", {})
        return text, u.get("input_tokens", 0), u.get("output_tokens", 0)
    if provider.startswith("deepseek"):
        model = {"deepseek": "deepseek-flash"}.get(provider, provider.replace("deepseek:", ""))
        url = "https://api.deepseek.com/chat/completions"
        body = {"model": model, "temperature": temperature, "thinking": {"type": "disabled"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        headers = {"Authorization": "Bearer " + need("DEEPSEEK_API_KEY")}
        r = _post(url, body, headers, timeout)
        if "error" in r:
            sys.exit(f"deepseek error: {r['error']}")
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
