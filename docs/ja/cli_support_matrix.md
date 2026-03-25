# CLI対応表

更新日: 2026-03-25

## 概要

> `vibecodehpc setup` 実行**前**に認証（サブスクリプション / ブラウザログイン）を済ませること。

| CLI | ステータス | 備考 |
|-----|-----------|------|
| Claude Code | ✅ デフォルトCLI | |
| Codex CLI | ✅ | `OPENAI_BASE_URL` をグローバルに設定しないこと |
| Cline CLI | ✅ | |
| Gemini CLI | ✅ | |
| OpenCode | ✅ | |
| vibe-local | ✅ Ollama必須 | |
| Qwen Code | ☑ | ネイティブ認証のみ（OpenRouter ✕） |
| Kimi Code CLI | ☑ | ネイティブ認証のみ（OpenRouter ✕） |

---

## 既知の制限事項

- **Qwen Code / Kimi Code CLI（OpenRouter経由）**: ツール呼び出しが動作しない。ネイティブ認証を使用すること。
  - Qwen CodeはQwen3-Coder向けに最適化されており、非Qwenモデルではテキストのみの応答になる（[#70](https://github.com/QwenLM/qwen-code/issues/70)）
  - Kimi Code CLIはネイティブOAuthトークンが必要で、OpenRouterプロキシでは動作しない
- **vibe-local**: Ollamaでローカルモデルのデプロイが必要。コンテキストウィンドウのデフォルトは32K。増やすには `cli_args` で `--context-window` を指定する。
- **Gemini CLI**: `--yolo` モードにはフォルダ信頼が必要（v0.11.1以降アダプタが自動設定）
- **Codex CLI**: `OPENAI_BASE_URL` をグローバルに設定するとCodexが誤ったエンドポイントに接続する。必要な場合は `env_vars` でエージェントごとに設定すること。

---

<details>
<summary>認証</summary>

| CLI | ログインコマンド | APIキーの場所 |
|-----|-----------------|--------------|
| Claude Code | `claude auth login` | `~/.claude/.credentials.json` |
| Codex CLI | `codex login` | `~/.codex/auth.json` |
| Cline CLI | `cline auth -p <provider>` | `~/.cline/data/globalState.json` |
| Gemini CLI | `GOOGLE_API_KEY` 環境変数 | `~/.config/configstore/` |
| OpenCode | `opencode providers login` | `~/.local/share/opencode/` |
| vibe-local | — (Ollama、認証不要) | — |
| Qwen Code | `/auth` (対話式) | `~/.config/configstore/` |
| Kimi Code CLI | `kimi login` | `~/.kimi/kimi.json` |

</details>

<details>
<summary>コンテキスト監視の実装</summary>

全8種のCLIをコンテキスト監視がサポートしている。ログの場所とキャッシュの扱い:

| CLI | ログの場所 | inputにキャッシュを含む? |
|-----|-----------|:--------------------:|
| Claude Code | `~/.claude/projects/<encoded>/session.jsonl` | No |
| Codex CLI | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | Yes |
| Cline CLI | `~/.cline/data/tasks/<id>/ui_messages.json` | No |
| Gemini CLI | `~/.gemini/tmp/<id>/chats/session-*.json` | Yes |
| OpenCode | `~/.local/share/opencode/opencode.db` (SQLite) | N/A |
| vibe-local | tmux capture-pane `ctx:N%` + Ollama `/api/ps` | N/A |
| Qwen Code | `~/.qwen/projects/<encoded>/chats/*.jsonl` | Yes |
| Kimi Code CLI | `~/.kimi/sessions/<hash>/<uuid>/wire.jsonl` | No |

</details>

<details>
<summary>ツール呼び出し互換性（プロバイダ別）</summary>

| CLI | ネイティブAPI | OpenRouter | Ollama |
|-----|-------------|------------|--------|
| Claude Code | ✅ | ✅ | ☑ |
| Codex CLI | ✅ | ☑ | ☑ |
| Cline CLI | ✅ | ✅ | ☑ |
| Gemini CLI | ✅ | ☑ | ☑ |
| OpenCode | ✅ | ✅ | ☑ |
| vibe-local | — | — | ✅ Ollama必須 |
| Qwen Code | ✅ (DashScope) | **No** | **No** ([#176](https://github.com/QwenLM/qwen-code/issues/176)) |
| Kimi Code CLI | ✅ (native) | ☑ | ☑ |

</details>
