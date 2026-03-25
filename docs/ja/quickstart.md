# クイックスタート

## 前提条件

- **tmux** — エージェント間通信基盤
- **Python 3.10+** — フレームワーク実行環境
  - matplotlib, numpy — 可視化（コンテキスト/SOTA/予算グラフ）
- **Node.js 18+** — npm系CLI（Codex, Cline, Gemini, OpenCode, Qwen）のインストールに必要
- **gh**（任意）— [GitHub CLI](https://cli.github.com/)、CDエージェント使用時に推奨
- **CLI** — 最低1つ（PMとして使用）

  [Claude Code](https://github.com/anthropics/claude-code) · [Codex CLI](https://github.com/openai/codex) · [Cline CLI](https://github.com/cline/cline) · [Gemini CLI](https://github.com/google-gemini/gemini-cli) · [OpenCode](https://github.com/opencode-ai/opencode) · [vibe-local](https://github.com/ochyai/vibe-local) · [Qwen Code](https://github.com/QwenLM/qwen-code) · [Kimi Code CLI](https://github.com/MoonshotAI/kimi-cli)

  各リポジトリの README に従ってインストール。一度起動して認証を完了する。詳細は [CLI対応表](cli_support_matrix.md)。

## 3つの入力を用意

1. `requirement_definition.md` — [テンプレート](requirement_definition_template.md)から編集、またはPMに対話的に作成させる
2. `_remote_info/` — 対象環境の接続情報（[詳細](../../_remote_info/README.md)）
3. `BaseCode/` — 最適化対象のコード

## 起動

```bash
# オプション: SSH agent設定（リモート実行が必要な場合のみ）
# 詳細: https://docs.google.com/presentation/d/1Nrz6KbSsL5sbaKk1nNS8ysb4sfB2dK8JZeZooPx4NSg/edit?usp=sharing
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/your_private_key

# setupがtmuxセッションを作成し、PM を自動起動
python3 -m vibecodehpc setup --name MyProject -w 4
```

PM が tmux セッション内で自動起動する。要件定義を読み、worker（SE, PG, CD）の起動・CLI/model選択・ディレクトリ設計を自動で行う。

## 動作の流れ

1. PMが要件読み込みと環境調査
2. PMがdirectory階層を設計しagentを配置
3. PGが反復最適化（code → compile → run → benchmark）
4. SEが統計追跡とreport生成
5. 成果物は `User-shared/` に集約
