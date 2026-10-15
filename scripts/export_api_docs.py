"""Exporte le schéma OpenAPI (YAML + JSON) et une collection Postman v2.1 dans docs/api/.

Usage : python scripts/export_api_docs.py   (depuis backend/, venv actif)
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT.parent / "docs" / "api"
OUT.mkdir(parents=True, exist_ok=True)
env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.dev"}

for fmt, name in (("openapi", "openapi.yaml"), ("openapi-json", "openapi.json")):
    subprocess.run(
        [sys.executable, "manage.py", "spectacular", "--format", fmt, "--file", str(OUT / name), "--validate"],
        cwd=ROOT, env=env, check=True,
    )

schema = json.loads((OUT / "openapi.json").read_text(encoding="utf-8"))
folders: dict[str, list] = {}
for path, methods in schema["paths"].items():
    for method, op in methods.items():
        if method not in {"get", "post", "patch", "put", "delete"}:
            continue
        tag = (op.get("tags") or ["divers"])[0]
        raw = "{{baseUrl}}" + path.replace("{", "{{").replace("}", "}}")
        request = {
            "method": method.upper(),
            "header": [{"key": "Authorization", "value": "Bearer {{accessToken}}", "disabled": path.startswith("/api/v1/search")}],
            "url": {"raw": raw, "host": ["{{baseUrl}}"], "path": [p for p in path.strip("/").split("/")]},
            "description": op.get("description", ""),
        }
        body = op.get("requestBody", {}).get("content", {})
        if "application/json" in body:
            ref = body["application/json"].get("schema", {}).get("$ref", "")
            props = schema["components"]["schemas"].get(ref.split("/")[-1], {}).get("properties", {})
            example = {k: v.get("example", "") for k, v in props.items() if not v.get("readOnly")}
            request["header"].append({"key": "Content-Type", "value": "application/json"})
            request["body"] = {"mode": "raw", "raw": json.dumps(example, indent=2, ensure_ascii=False)}
        elif "multipart/form-data" in body:
            request["body"] = {"mode": "formdata", "formdata": []}
        if path.endswith(("/auth/refresh/", "/auth/logout/")):
            request["header"].append({"key": "X-Requested-With", "value": "XMLHttpRequest"})
        folders.setdefault(tag, []).append({"name": f"{method.upper()} {path}", "request": request})

collection = {
    "info": {
        "name": "E-Courtier API v1",
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        "description": "Générée depuis docs/api/openapi.json. Connectez-vous via POST /auth/login/ puis copiez `access` dans la variable accessToken.",
    },
    "variable": [{"key": "baseUrl", "value": "http://localhost:8000"}, {"key": "accessToken", "value": ""}],
    "item": [{"name": tag, "item": items} for tag, items in sorted(folders.items())],
}
(OUT / "E-Courtier.postman_collection.json").write_text(json.dumps(collection, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"{sum(len(i) for i in folders.values())} opérations exportées dans {OUT}")
