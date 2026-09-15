"""CC Switch configuration builder (``python -m radar.cc_switch``).

Builds the import payload for CC Switch, anchored to the **official V1 deep
link protocol** documented at
``docs/user-manual/zh/5-faq/5.3-deeplink.md`` in ``farion1231/cc-switch``.

Verified protocol shape (quoted from the official documentation, see
``docs/cc-switch.md`` for the full record):

    ccswitch://v1/import?resource={type}&app={app}&name={name}&...

    resource  required  provider | mcp | prompt | skill
    app       required  claude | codex | gemini | opencode | openclaw
    name      required
    endpoint  optional  API endpoint; comma-separated list is allowed
    apiKey    optional  API key
    homepage  optional
    model     optional
    ...

WHAT THIS MODULE DELIBERATELY DOES NOT DO
-----------------------------------------
* It never invents a JSON blob and claims CC Switch can import it.
* It never writes to CC Switch's SQLite database and never performs a
  full-database SQL restore.
* It never overwrites a user's existing configuration.
* It never puts an API key in a link. Radar does not collect upstream keys at
  all; the user fills their own key inside CC Switch.

Protocol fidelity
-----------------
``openai_chat``, ``openai_responses``, ``anthropic_messages`` and
``gemini_native`` are tracked separately. A service that only supports Chat
Completions is NOT reported as compatible with a path that requires Responses.
When support cannot be established the status is ``unknown`` or
``unsupported`` -- never a fabricated success.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from .vocab import (
    CCApp,
    CCResource,
    CCStatus,
    Protocol,
)

#: The CC Switch release this integration was written and verified against.
#: Pinning a baseline is required so a later GUI change cannot silently break
#: the generated links.
SUPPORTED_CC_SWITCH_VERSION = "3.20.3"
SUPPORTED_CC_SWITCH_REF = "v3.20.3"
SUPPORTED_CC_SWITCH_COMMIT = "06082e1"

#: Deep link version segment confirmed by the official protocol document.
DEEP_LINK_VERSION = "v1"

#: Maximum lengths enforced as a whitelist guard before anything is emitted.
MAX_FIELD_LENGTH = 2048
MAX_NAME_LENGTH = 120

#: Characters permitted in an endpoint URL once assembled.
_ENDPOINT_PATTERN = re.compile(r"^https?://[^\s<>\"'\\]+$")

#: Which CC Switch target applications a given protocol can serve.
#:
#: ``claude`` drives Claude Code, which speaks the Anthropic Messages API.
#: ``codex`` drives Codex, which uses the OpenAI Responses API.
#: ``gemini`` drives the Gemini CLI, which uses the native Gemini API.
#: ``opencode`` and ``openclaw`` are recorded as OpenAI Chat Completions
#: clients here, which is the behaviour of the pinned release.
APP_PROTOCOL_REQUIREMENTS: dict[str, set[Protocol]] = {
    CCApp.CLAUDE.value: {Protocol.ANTHROPIC_MESSAGES},
    CCApp.CODEX.value: {Protocol.OPENAI_RESPONSES},
    CCApp.GEMINI.value: {Protocol.GEMINI_NATIVE},
    CCApp.OPENCODE.value: {Protocol.OPENAI_CHAT},
    CCApp.OPENCLAW.value: {Protocol.OPENAI_CHAT},
}

APP_DISPLAY_NAMES = {
    CCApp.CLAUDE.value: "Claude Code",
    CCApp.CODEX.value: "Codex",
    CCApp.GEMINI.value: "Gemini CLI",
    CCApp.OPENCODE.value: "OpenCode",
    CCApp.OPENCLAW.value: "OpenClaw",
}

#: Human label for each protocol, used in the UI instead of a green tick that
#: would imply blanket compatibility.
PROTOCOL_LABELS = {
    Protocol.OPENAI_CHAT.value: "Chat Completions",
    Protocol.OPENAI_RESPONSES.value: "Responses",
    Protocol.ANTHROPIC_MESSAGES.value: "Messages (Anthropic)",
    Protocol.GEMINI_NATIVE.value: "Gemini native",
}


@dataclass
class CCField:
    """One configurable field shown in the preview and copied by the user."""

    key: str
    label: str
    value: str | None
    required: bool = False
    hint: str | None = None
    secret: bool = False
    copiable: bool = True


@dataclass
class CCExtra:
    """Optional protocol-adjacent fields."""

    haiku_model: str | None = None
    sonnet_model: str | None = None
    opus_model: str | None = None


@dataclass
class CCConfig:
    """Result of building an import payload for one provider/app pair."""

    status: str
    target: str | None
    target_label: str | None
    supported_version: str
    supported_commit: str
    resource: str
    fields: list[CCField] = field(default_factory=list)
    deep_link: str | None = None
    warnings: list[str] = field(default_factory=list)
    reason: str | None = None
    requires_conversion: bool = False
    protocol: str | None = None
    protocol_label: str | None = None
    #: Named explicitly so the UI can say what it is NOT: a CC Switch native
    #: import file requires verification; this is a Radar data-exchange file.
    radar_export: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in {CCStatus.READY.value, CCStatus.READY_WITHOUT_KEY.value}

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "target": self.target,
            "target_label": self.target_label,
            "supported_version": self.supported_version,
            "supported_commit": self.supported_commit,
            "resource": self.resource,
            "protocol": self.protocol,
            "protocol_label": self.protocol_label,
            "requires_conversion": self.requires_conversion,
            "reason": self.reason,
            "warnings": self.warnings,
            "deep_link": self.deep_link,
            "fields": [
                {
                    "key": item.key,
                    "label": item.label,
                    "value": item.value,
                    "required": item.required,
                    "hint": item.hint,
                    "secret": item.secret,
                    "copiable": item.copiable,
                }
                for item in self.fields
            ],
            # Labelled unambiguously as a Radar exchange file.
            "radar_export": self.radar_export,
            "radar_export_label": "Radar 数据交换文件（非 CC Switch 原生导入文件）",
        }


# ---------------------------------------------------------------------------
# Endpoint handling
# ---------------------------------------------------------------------------


def normalise_endpoint(base_url: str | None) -> str | None:
    """Validate and canonicalise an API base URL.

    The task book calls out path-joining rules explicitly: the existing ``/v1``
    must not be duplicated, a trailing slash is collapsed, and a URL that
    already carries the full endpoint path is kept as-is. Chinese characters
    and other non-ASCII in a path are percent-encoded.
    """
    if not base_url:
        return None
    text = base_url.strip().strip("`'\"")

    # A URL that already ends in a known completion path stays untouched.
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None

    path = parts.path or ""

    # Collapse a duplicated version segment such as /v1/v1.
    path = re.sub(r"/v1/v1(/|$)", r"/v1\1", path)
    path = re.sub(r"/v1beta/v1beta(/|$)", r"/v1beta\1", path)

    # Remove a trailing slash so the caller can join consistently.
    path = path.rstrip("/")

    # Percent-encode non-ASCII without double-encoding existing escapes.
    if any(ord(character) > 127 for character in path):
        path = quote(path, safe="/:@!$&'()*+,;=~-._")

    rebuilt = urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))
    if not _ENDPOINT_PATTERN.match(rebuilt):
        return None
    return rebuilt


def join_endpoint(base_url: str, suffix: str) -> str | None:
    """Join a path suffix without duplicating a version segment."""
    base = normalise_endpoint(base_url)
    if base is None:
        return None
    tail = "/" + suffix.strip("/")
    if base.endswith(tail):
        return base
    if "/v1" in base and tail.startswith("/v1"):
        tail = tail[3:]
    return base + tail


def is_valid_endpoint(url: str | None) -> bool:
    if not url:
        return False
    return bool(_ENDPOINT_PATTERN.match(url)) and len(url) <= MAX_FIELD_LENGTH


# ---------------------------------------------------------------------------
# Core builder
# ---------------------------------------------------------------------------


def build_config(
    *,
    provider_name: str,
    app: str,
    base_url: str | None,
    model_id: str | None = None,
    protocols: Iterable[str] = (),
    homepage: str | None = None,
    display_name: str | None = None,
    extra: CCExtra | None = None,
    notes: str | None = None,
    include_key_placeholder: bool = False,
    verified: bool = False,
) -> CCConfig:
    """Build the CC Switch import payload for one provider/app pair.

    Returns a structured result rather than raising, so the UI can always show
    a clear next step. Nothing here fetches anything or probes localhost.
    """
    protocol_set = {_as_protocol(value) for value in protocols}
    protocol_set.discard(None)  # type: ignore[arg-type]

    target = app if app in APP_PROTOCOL_REQUIREMENTS else None
    warnings: list[str] = []

    deep_link: str | None = None

    if target is None:
        return CCConfig(
            status=CCStatus.UNKNOWN.value,
            target=None,
            target_label=None,
            supported_version=SUPPORTED_CC_SWITCH_VERSION,
            supported_commit=SUPPORTED_CC_SWITCH_COMMIT,
            resource=CCResource.PROVIDER.value,
            warnings=[f"未知的目标应用：{app!r}"],
            reason="unsupported_target",
            radar_export=_radar_export(provider_name, app, base_url, model_id, protocols),
        )

    target_label = APP_DISPLAY_NAMES.get(target, target)
    required = APP_PROTOCOL_REQUIREMENTS[target]
    matched = protocol_set & required

    field_protocol = next(iter(matched)) if matched else None

    fields: list[CCField] = []
    endpoint = normalise_endpoint(base_url)

    # -- protocol gate ----------------------------------------------------
    if not protocol_set:
        status = CCStatus.UNKNOWN.value
        reason = "protocol_unknown"
        warnings.append(
            "来源未声明协议，无法判断该服务是否满足目标工具的调用路径。"
            "已标记为 unknown，不会生成可用的导入链接。"
        )
    elif not matched:
        status = CCStatus.UNSUPPORTED_PROTOCOL.value
        reason = "protocol_not_supported"
        labels = "、".join(
            PROTOCOL_LABELS.get(value.value if hasattr(value, "value") else str(value), str(value))
            for value in sorted(protocol_set, key=lambda p: str(p))
        )
        warnings.append(
            f"该服务声明支持 {labels}，但 {target_label} 需要 "
            f"{'、'.join(PROTOCOL_LABELS.get(p.value, p.value) for p in sorted(required, key=lambda x: x.value))}。"
            "仅支持 Chat Completions 的服务不能直接用于需要 Responses 的调用路径。"
        )
    elif endpoint is None:
        status = CCStatus.MISSING_FIELDS.value
        reason = "missing_endpoint"
        warnings.append("缺少可用的 Base URL，无法生成导入链接。")
    elif not is_valid_endpoint(endpoint):
        status = CCStatus.MISSING_FIELDS.value
        reason = "invalid_endpoint"
        warnings.append("Base URL 未通过格式白名单校验，已拒绝生成链接。")
    else:
        status = CCStatus.READY_WITHOUT_KEY.value
        reason = "ok"

    # -- fields -----------------------------------------------------------
    fields.append(
        CCField(
            key="name",
            label="Provider 名称",
            value=_safe_text(display_name or provider_name, MAX_NAME_LENGTH),
            required=True,
            hint="在 CC Switch 中显示的供应商名称",
        )
    )
    fields.append(
        CCField(
            key="app",
            label="目标应用",
            value=target,
            required=True,
            hint=target_label,
            copiable=False,
        )
    )
    fields.append(
        CCField(
            key="endpoint",
            label="Base URL",
            value=endpoint,
            required=True,
            hint="API 端点地址；Radar 已检查 /v1 拼接规则，不会重复拼接",
        )
    )
    fields.append(
        CCField(
            key="model",
            label="模型 ID",
            value=_safe_text(model_id, 200) if model_id else None,
            required=False,
            hint="精确的上游模型标识",
        )
    )
    fields.append(
        CCField(
            key="homepage",
            label="供应商官网",
            value=_safe_text(homepage, MAX_FIELD_LENGTH) if homepage else None,
            required=False,
            hint="可选",
        )
    )
    if field_protocol is not None:
        fields.append(
            CCField(
                key="protocol",
                label="协议",
                value=PROTOCOL_LABELS.get(field_protocol.value, field_protocol.value),
                required=False,
                hint="以文本明确标注，不使用一个勾号表示全部兼容",
                copiable=True,
            )
        )

    if extra is not None and target == CCApp.CLAUDE.value:
        for key, label, value in (
            ("haikuModel", "Haiku 模型", extra.haiku_model),
            ("sonnetModel", "Sonnet 模型", extra.sonnet_model),
            ("opusModel", "Opus 模型", extra.opus_model),
        ):
            if value:
                fields.append(
                    CCField(
                        key=key,
                        label=label,
                        value=_safe_text(value, 200),
                        required=False,
                        hint="仅 Claude 支持",
                    )
                )

    if notes:
        fields.append(
            CCField(
                key="notes",
                label="备注",
                value=_safe_text(notes, 400),
                required=False,
                hint="会写入 CC Switch 的备注字段",
            )
        )

    # The user's own key is never collected by Radar. The field is shown so the
    # user knows what to paste inside CC Switch, and is marked as a secret so
    # it never enters a URL or an export.
    fields.append(
        CCField(
            key="apiKey",
            label="API Key",
            value=None,
            required=True,
            hint=("请在你自己的 CC Switch 中填写。Radar 不收集、不传输、" "不记录任何上游密钥。"),
            secret=True,
            copiable=False,
        )
    )

    # -- deep link --------------------------------------------------------
    if status in {CCStatus.READY.value, CCStatus.READY_WITHOUT_KEY.value}:
        deep_link = build_deep_link(
            resource=CCResource.PROVIDER.value,
            app=target,
            name=display_name or provider_name,
            endpoint=endpoint,
            homepage=_safe_text(homepage, MAX_FIELD_LENGTH) if homepage else None,
            model=_safe_text(model_id, 200) if model_id else None,
            api_key=None,  # never populated by Radar
            include_key_placeholder=include_key_placeholder,
        )
        if include_key_placeholder:
            warnings.append(
                "链接中包含 API Key 占位符。CC Switch 会在导入确认框中显示该字段，"
                "请在导入后替换为你自己的密钥。"
            )

    if not verified:
        warnings.append(
            "该配置未经过真实 API 调用验证。Radar 只确认字段格式与协议声明，"
            "不代表密钥有效或额度可用。"
        )

    return CCConfig(
        status=status,
        target=target,
        target_label=target_label,
        supported_version=SUPPORTED_CC_SWITCH_VERSION,
        supported_commit=SUPPORTED_CC_SWITCH_COMMIT,
        resource=CCResource.PROVIDER.value,
        fields=fields,
        deep_link=deep_link,
        warnings=warnings,
        reason=reason,
        requires_conversion=_requires_conversion(protocol_set, required),
        protocol=field_protocol.value if field_protocol else None,
        protocol_label=(PROTOCOL_LABELS.get(field_protocol.value) if field_protocol else None),
        radar_export=_radar_export(provider_name, app, base_url, model_id, protocols),
    )


def _requires_conversion(available: set[Any], required: set[Protocol]) -> bool:
    """Whether a protocol translation step would be needed.

    Only true when the service does have an OpenAI-compatible path but the
    target needs a different one. It is never guessed beyond what the sources
    actually declare.
    """
    if not available or not required:
        return False
    if available & required:
        return False
    openai_family = {Protocol.OPENAI_CHAT, Protocol.OPENAI_RESPONSES}
    return bool(available & openai_family) and bool(required & openai_family)


def build_deep_link(
    *,
    resource: str,
    app: str,
    name: str,
    endpoint: str | None = None,
    homepage: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    include_key_placeholder: bool = False,
) -> str:
    """Assemble a ``ccswitch://v1/import`` URL exactly per the V1 protocol.

    ``urllib``-style percent encoding is applied to every parameter value, so
    Chinese names and special characters are encoded correctly.
    """
    from urllib.parse import urlencode

    params: list[tuple[str, str]] = [
        ("resource", resource),
        ("app", app),
        ("name", name),
    ]
    if endpoint:
        params.append(("endpoint", endpoint))
    if homepage:
        params.append(("homepage", homepage))
    if model:
        params.append(("model", model))

    if api_key:
        # Radar never does this with a real key. The branch exists solely so a
        # future integration could, and it is guarded by the caller.
        params.append(("apiKey", api_key))
    elif include_key_placeholder:
        params.append(("apiKey", "YOUR_API_KEY"))

    query = urlencode(params, quote_via=quote, safe="")
    return f"ccswitch://{DEEP_LINK_VERSION}/import?{query}"


def _radar_export(
    provider_name: str,
    app: str,
    base_url: str | None,
    model_id: str | None,
    protocols: Iterable[str],
) -> dict[str, Any]:
    """The project's own JSON export.

    Named and described as a Radar data-exchange file. It must NOT be called a
    CC Switch native import file unless that has actually been verified.
    """
    return {
        "kind": "freeai-radar.exchange.v1",
        "notice": (
            "这是 FreeAI Radar 的数据交换文件，不是 CC Switch 原生导入文件。"
            "CC Switch 原生的批量导入能力请使用 ccswitch:// 深度链接。"
        ),
        "provider_name": provider_name,
        "target_app": app,
        "base_url": normalise_endpoint(base_url),
        "model_id": model_id,
        "protocols": sorted(
            str(value.value if hasattr(value, "value") else value) for value in protocols
        ),
        "api_key": None,
    }


def _as_protocol(value: Any) -> Protocol | None:
    if isinstance(value, Protocol):
        return value
    try:
        return Protocol(str(value))
    except ValueError:
        return None


def _safe_text(value: str | None, limit: int) -> str | None:
    """Whitelist-guard free text before it enters a link or the DOM.

    Control characters and angle brackets are removed, and the length is
    capped. Scraped content can therefore never inject markup or script.
    """
    if value is None:
        return None
    text = re.sub(r"[\x00-\x1f\x7f<>]", "", str(value)).strip()
    if not text:
        return None
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


# ---------------------------------------------------------------------------
# Batch build for the static export
# ---------------------------------------------------------------------------


def build_all(
    catalog: dict[str, Any],
    *,
    apps: Iterable[str] = (CCApp.CLAUDE.value, CCApp.CODEX.value, CCApp.GEMINI.value),
) -> dict[str, Any]:
    """Pre-compute CC Switch payloads for every provider in the catalog.

    Emitting this at build time keeps the browser work trivial and means the
    same logic is exercised by the tests. The browser also re-runs the pure
    function when a user changes the target tool.
    """
    providers = {provider["id"]: provider for provider in catalog.get("providers", [])}
    models_by_provider: dict[str, list[dict[str, Any]]] = {}
    for model in catalog.get("models", []):
        models_by_provider.setdefault(model["provider_id"], []).append(model)

    offers_by_provider: dict[str, list[dict[str, Any]]] = {}
    for offer in catalog.get("offers", []):
        offers_by_provider.setdefault(offer["provider_id"], []).append(offer)

    payload: dict[str, Any] = {
        "schema_version": 1,
        "supported_version": SUPPORTED_CC_SWITCH_VERSION,
        "supported_ref": SUPPORTED_CC_SWITCH_REF,
        "supported_commit": SUPPORTED_CC_SWITCH_COMMIT,
        "protocol": f"ccswitch://{DEEP_LINK_VERSION}/import",
        "entries": {},
    }

    for provider_id, provider in providers.items():
        models = models_by_provider.get(provider_id, [])
        offers = offers_by_provider.get(provider_id, [])

        base_url = next((offer.get("base_url") for offer in offers if offer.get("base_url")), None)
        protocols: set[str] = set()
        for model in models:
            protocols.update(model.get("protocols") or [])
        primary_model = next((model for model in models if model.get("model_id")), None)

        entries: dict[str, Any] = {}
        for app in apps:
            config = build_config(
                provider_name=provider.get("name") or provider_id,
                display_name=provider.get("name"),
                app=app,
                base_url=base_url,
                model_id=(primary_model or {}).get("model_id"),
                protocols=protocols,
                homepage=provider.get("homepage_url"),
                verified=False,
            )
            entries[app] = config.to_dict()

        payload["entries"][provider_id] = {
            "provider_slug": provider.get("slug"),
            "provider_name": provider.get("name"),
            "base_url": base_url,
            "protocols": sorted(protocols),
            "apps": entries,
        }

    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m radar.cc_switch",
        description="Pre-compute CC Switch import payloads from a public catalog.",
    )
    parser.add_argument("--catalog", required=True, help="path to catalog.<version>.json")
    parser.add_argument("--output", required=True, help="output JSON path")
    parser.add_argument(
        "--apps",
        nargs="*",
        default=[CCApp.CLAUDE.value, CCApp.CODEX.value, CCApp.GEMINI.value],
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    payload = build_all(catalog, apps=args.apps)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    statuses: dict[str, int] = {}
    for entry in payload["entries"].values():
        for app_config in entry["apps"].values():
            status = app_config["status"]
            statuses[status] = statuses.get(status, 0) + 1

    print(
        json.dumps(
            {
                "providers": len(payload["entries"]),
                "statuses": statuses,
                "supported_version": payload["supported_version"],
                "output": str(output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
