"""Claude çağrıları. Tüm ajanlar yapılandırılmış (Pydantic) çıktı alır.

İki arka uç var (LLM_BACKEND):
- claude-code: bilgisayardaki Claude Code'u (`claude -p`) senin girişinle çalıştırır; API anahtarı gerekmez.
- api: Anthropic API'yi ANTHROPIC_API_KEY ile çağırır.
"auto" (varsayılan) önce Claude Code'u arar, bulamazsa API'ye düşer.
"""
import glob
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from . import config

T = TypeVar("T", bound=BaseModel)

_client: anthropic.Anthropic | None = None


class LLMError(RuntimeError):
    pass


def find_claude_code() -> str | None:
    """Claude Code çalıştırılabilirini bulur: CLAUDE_CODE_PATH, PATH, sonra VS Code eklentisi."""
    if config.CLAUDE_CODE_PATH and Path(config.CLAUDE_CODE_PATH).exists():
        return config.CLAUDE_CODE_PATH
    if found := shutil.which("claude"):
        return found
    if not config.WINDOWS and (local := Path.home() / ".local" / "bin" / "claude").exists():
        return str(local)  # masaüstü kısayolundan açılınca PATH'te olmayabilir
    exe = "claude.exe" if config.WINDOWS else "claude"
    candidates = sorted(
        (m for d in (".vscode", ".vscode-server")
         for m in glob.glob(str(Path.home() / d / "extensions" / "anthropic.claude-code-*" / "resources" / "native-binary" / exe))),
        key=os.path.getmtime,
    )
    return candidates[-1] if candidates else None


def backend() -> str:
    if config.LLM_BACKEND in ("claude-code", "api"):
        return config.LLM_BACKEND
    if find_claude_code():
        return "claude-code"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "api"
    raise LLMError("Claude bulunamadı: Claude Code kur veya .env içine ANTHROPIC_API_KEY yaz.")


def structured(system: str, prompt: str, schema: type[T], effort: str = "medium") -> T:
    if backend() == "claude-code":
        return _via_claude_code(system, prompt, schema, effort)
    return _via_api(system, prompt, schema, effort)


def _via_claude_code(system: str, prompt: str, schema: type[T], effort: str) -> T:
    exe = find_claude_code()
    if exe is None:
        raise LLMError("Claude Code bulunamadı (CLAUDE_CODE_PATH ayarla veya LLM_BACKEND=api yap).")
    # Boş bir klasörde çalıştır: proje dosyaları, CLAUDE.md ve hafıza bağlama karışmasın
    with tempfile.TemporaryDirectory() as tmp:
        system_file = Path(tmp) / "system.txt"
        system_file.write_text(system, encoding="utf-8")
        cmd = [
            exe, "-p",
            "--output-format", "json",
            "--json-schema", json.dumps(schema.model_json_schema(), ensure_ascii=False),
            "--system-prompt-file", str(system_file),
            "--model", config.CLAUDE_MODEL,
            "--effort", effort,
            "--tools", "",
            "--setting-sources", "",
            "--no-session-persistence",
        ]
        try:
            proc = subprocess.run(
                cmd, input=prompt, cwd=tmp, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=900,
            )
        except subprocess.TimeoutExpired as e:
            raise LLMError("Claude Code 15 dakikada yanıt vermedi.") from e

    try:
        data = json.loads(proc.stdout)
    except ValueError as e:
        detail = (proc.stderr or proc.stdout).strip()[-800:]
        raise LLMError(f"Claude Code çalışmadı (çıkış kodu {proc.returncode}): {detail}") from e
    if data.get("is_error") or data.get("subtype") != "success":
        raise LLMError(f"Claude Code hatası: {str(data.get('result') or data.get('subtype'))[:800]}")
    output = data.get("structured_output")
    if output is None:
        raise LLMError("Claude Code yapılandırılmış çıktı döndürmedi.")
    try:
        return schema.model_validate(output)
    except ValidationError as e:
        raise LLMError(f"Claude Code yanıtı beklenen biçimde değil: {e}") from e


def _client_api() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _via_api(system: str, prompt: str, schema: type[T], effort: str) -> T:
    """Güvenlik sınıflandırıcısı isteği reddederse sunucu tarafı yedek model
    (fallbacks="default") isteği otomatik olarak yeniden çalıştırır."""
    try:
        response = _client_api().beta.messages.parse(
            model=config.CLAUDE_MODEL,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_format=schema,
            output_config={"effort": effort},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as e:
        raise LLMError("Claude API anahtarı geçersiz veya eksik (.env içindeki ANTHROPIC_API_KEY).") from e
    except anthropic.RateLimitError as e:
        raise LLMError("Claude API hız sınırına takıldı; biraz sonra tekrar dene.") from e
    except anthropic.APIConnectionError as e:
        raise LLMError("Claude API'ye bağlanılamadı (internet bağlantısı?).") from e

    if response.stop_reason == "refusal":
        raise LLMError("Claude bu isteği reddetti; konu veya geri bildirim metnini değiştirip tekrar dene.")
    if response.stop_reason == "max_tokens":
        raise LLMError("Claude yanıtı uzunluk sınırında kesildi.")
    if response.parsed_output is None:
        raise LLMError("Claude yanıtı beklenen biçimde değil.")
    return response.parsed_output
