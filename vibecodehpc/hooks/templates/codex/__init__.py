"""Codex CLI anti-idle templates for VibeCodeHPC.

Codex (codex-rs) supports SessionStart and Stop hooks via
``.codex/hooks.json`` when ``features.codex_hooks = true`` is set in
``config.toml``.  AGENTS.md anti-idle directives serve as a fallback
for environments where the hooks feature flag is unavailable.
"""
