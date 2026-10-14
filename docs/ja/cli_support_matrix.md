# CLI対応表

更新日: 2026-10-14

## 概要

> `vibecodehpc setup` 実行**前**に認証（サブスクリプション / ブラウザログイン）を済ませること。

| CLI | ステータス | 自前のサーバー | 備考 |
|-----|-----------|----------------|------|
| Claude Code | ✅ デフォルトCLI | Anthropic Messages API（登録表の `endpoint`） | |
| Codex CLI | ✅ | OpenAI Responses API（登録表の `endpoint`） | `OPENAI_BASE_URL` をグローバルに設定しないこと |
| Cline CLI | ✅ | — | |
| Gemini CLI | ✅ | — | |
| OpenCode | ✅ | — | |
| vibe-local | ✅ Ollama必須 | Ollama（もともとローカル） | |
| Qwen Code | ☑ | `env` で OpenAI Chat API（`OPENAI_BASE_URL`）、未確認 | ネイティブ認証のみ（OpenRouter ✕） |
| Kimi Code CLI | ☑ | — | ネイティブ認証のみ（OpenRouter ✕） |

「—」は adapter に設定口が無いことを表す。[自前のモデルサーバー](#自前のモデルサーバー)を参照。

---

## 既知の制限事項

- **Qwen Code / Kimi Code CLI（OpenRouter経由）**: ツール呼び出しが動作しない。ネイティブ認証を使用すること。
  - Qwen CodeはQwen3-Coder向けに最適化されており、非Qwenモデルではテキストのみの応答になる（[#70](https://github.com/QwenLM/qwen-code/issues/70)）
  - Kimi Code CLIはネイティブOAuthトークンが必要で、OpenRouterプロキシでは動作しない
- **vibe-local**: Ollamaでローカルモデルのデプロイが必要。コンテキストウィンドウのデフォルトは32K。増やすには `cli_args` で `--context-window` を指定する。
- **Gemini CLI**: `--yolo` モードにはフォルダ信頼が必要（v0.11.1以降アダプタが自動設定）
- **Codex CLI**: `OPENAI_BASE_URL` をグローバルに設定するとCodexが誤ったエンドポイントに接続する。自前のサーバーには登録表の `endpoint` を使う。エージェントごとのプロバイダを `-c` の上書きで設定する。

---

## 自前のモデルサーバー

エージェントを自前のモデルサーバーに向けるには、`Agent-shared/agent_and_pane_id_table.jsonl` のその行に `endpoint` を足す。`vibecodehpc launch` が CLI の起動前にそのペインを設定する。`endpoint` の無い行は何も変わらない。

```json
{"agent_id": "PG1.1", "cli_type": "claude", "model": "local", "endpoint": {"base_url": "http://127.0.0.1:8000"}, ...}
{"agent_id": "PG1.2", "cli_type": "codex", "model": "local", "endpoint": {"base_url": "http://127.0.0.1:8000/v1"}, ...}
```

| キー | 対象 | 意味 |
|-----|------|------|
| `base_url` | 全部 | サーバーのアドレス。Claude Code は `/v1` を付けない。Codex は付ける |
| `model` | 全部 | 行に `model` が無いときのサーバーのモデル名 |
| `api_key_env` | 全部 | サーバーが鍵を確かめる場合、鍵を持つ変数の名前 |
| `effort` | Claude Code | effort の段階。Claude Code が知らないモデル名にも送る |
| `wire_api` | Codex | `responses`(既定)か `chat` |

adapter がすること:

- **Claude Code**: `ANTHROPIC_BASE_URL`、`ANTHROPIC_AUTH_TOKEN` と全部のモデルの枠(`ANTHROPIC_MODEL`、Opus/Sonnet/Haiku の既定、`CLAUDE_CODE_SUBAGENT_MODEL`)をサーバーのモデル名で export し、`ANTHROPIC_API_KEY` を unset する。
- **Codex CLI**: 指定の `base_url` を持つプロバイダを定義して選ぶ `-c` の上書きを起動の命令に足す。設定ファイルは変えない。

行には `env`(起動前に export する変数の表)も書ける。値は変数を参照してよい(`"$MY_TOKEN"`)。秘密の値を登録表に書かないこと。

サーバーと、それが出す API:

| サーバー | Anthropic Messages(`/v1/messages`) | OpenAI Responses(`/v1/responses`) | OpenAI Chat(`/v1/chat/completions`) | 確かめた CLI |
|--------|:---:|:---:|:---:|---|
| vLLM(公式のコンテナイメージ、arm64 版) | ✅ | ✅ | ✅ | GPU 4 枚の 1 ノードで Claude Code(対話と `-p`)と `codex exec` |
| SGLang(公式のコンテナイメージ) | 未確認 | 未確認 | ✅ | サーバーのみ、CLI は未実行 |
| llama.cpp server | 未確認 | 未確認 | ✅(同プロジェクトの文書による) | 未実行 |

サーバーのツール呼び出しのパーサーはモデルに合わせる。合わないとツール呼び出しが平文で返る。こうしたサーバーに対する headless の loop は [samples/self_hosted_endpoint](../samples/self_hosted_endpoint/README.md) を参照。

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

<details>
<summary>止まらない仕組み（CLI別）</summary>

polling のエージェントは1つの仕事で止まってはいけない。各 adapter は CLI が持つ仕組みを使う(`vibecodehpc/hooks/intents.py` の `StopAction`)。どの CLI でも、`periodic_enter` が tmux の側から Enter を送り、メッセージが入力欄に残らないようにする。

| CLI | 仕組み |
|-----|--------|
| Claude Code | Stop hook。終了コード 2 で停止を止め、ChangeLog/ToDo を差し戻す |
| Codex CLI | `.codex/hooks.json` の Stop hook(feature flag `codex_hooks`)と、控えの AGENTS.md の指示 |
| Cline CLI | 停止の intent を `UserPromptSubmit` hook に対応させる |
| Gemini CLI | `.gemini/settings.json` の Stop hook |
| OpenCode | plugin(セッションの登録)。止まりは tmux の側で扱う |
| vibe-local | なし。内蔵の agent loop が回り続ける |
| Qwen Code | hooks と、控えの AGENTS.md の指示 |
| Kimi Code CLI | AGENTS.md の指示のみ(hooks なし) |

</details>
