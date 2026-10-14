# Windows ネイティブ(任意・実験的)

> **任意・実験的な機能。** 既定の IPC は tmux のまま。`python3 -m vibecodehpc` の振る舞いは何も変わらず、merge しても tmux の利用者には影響しない。既存の tmux の経路で変えた行は 0。新しい code は選んだときだけ import される。

## なぜ

VibeCodeHPC は各エージェントを tmux のペインで動かし、ペインに文字を打ち込んで話す。WSL を使わない Windows には tmux が無い。Windows ネイティブの Claude Code には、代わりになる物がある:

- バックグラウンドのセッション: `claude --bg`。`claude agents --json` で一覧、`claude attach <id>` で見る、`claude stop <id>` と `claude rm <id>` で終える;
- 同じ機械のセッション同士の cross-session messaging(`ListAgents`、`SendMessage`、セッションごとの socket か named pipe。Windows ネイティブは Claude Code 2.1.234 から);
- hooks。セッションの文脈に文を足したり、止まるのを止めたりできる。

## 越えられない物

- WSL2 のセッションと Windows ネイティブのセッションは、同じ PC でも互いに届かない。エージェントは同じ側に揃える。
- 中核の CLI `python -m vibecodehpc` は `fcntl` を使う登録表の module を import するので、Windows ネイティブでは起動しない。任意の backend には別の入口 `python -m vibecodehpc.ipc` があり、それを import しない。

## 設計

| 部品 | ファイル | 役目 |
|---|---|---|
| interface | `vibecodehpc/ipc/base.py` | `IPCBackend`: `send`、`receive`、`health`、`launch`。CLI ごとの `CLIAdapter` と同じく、伝送路ごとに1つの class |
| tmux backend | `vibecodehpc/ipc/tmux_backend.py` | 既存の `tmux_utils` の関数を interface の後ろに置いただけ(変更なし) |
| cross_session backend | `vibecodehpc/ipc/cross_session.py` | バックグラウンドのセッション、ファイルの受信箱、hooks。tmux を使わない |
| 受信箱の hook | `vibecodehpc/hooks/templates/claude/inbox_inject.py` | 溜まった文をセッションに渡す(標準ライブラリのみ) |
| 入口 | `python -m vibecodehpc.ipc` | 選んだ backend で `send`、`receive`、`health`、`launch` |

選び方(この順): `--backend`、変数 `VIBECODEHPC_IPC_BACKEND`、`config.yaml` の `ipc_backend:`、無ければ `tmux`。`vibecodehpc.ipc.get_backend` は頼まれた時だけ選んだ module を import する。既定の経路はこれを呼ばない。

`cross_session` での文の通り道:

| 送り手 → 受け手 | 通り道 |
|---|---|
| 枠組み → エージェント、最初の文 | 起動時の `claude --bg` の最初の prompt |
| 枠組み → エージェント、その後 | `Agent-shared/ipc/inbox/<agent_id>.jsonl` に足す。hook が次の `UserPromptSubmit` か `PostToolUse` で文脈に足すか、次の `Stop` をその文で止めて続けさせる |
| エージェント → エージェント | Claude Code の `SendMessage`(相手は `ListAgents` で探す) |
| 生死 | `claude agents --json`: 一覧にあり `done` でなければ生きている |
| 人が見る | `claude attach <id>`(id は `Agent-shared/ipc/sessions.json`) |

起動の命令は adapter 自身の物(`ClaudeAdapter.build_launch_command()`、tmux の時と同じ flag とモデル)に `--bg` を足した物。`--launcher wt` を付けると、バックグラウンドの代わりに Windows Terminal の見えるタブで開く。

## 使い方

```powershell
# 一度だけ: プロジェクトルートを Claude Code で開き、信頼の確認を受け入れる
# (claude --bg は信頼されていない作業場所を断る。下の dir は親の信頼を受け継ぐ)
$env:VIBECODEHPC_IPC_BACKEND = "cross_session"
python -m vibecodehpc.ipc launch PG1.1 --workdir Agent-workdir\PG1.1 --model sonnet `
    --first-message "You are PG1.1. Read CLAUDE.md, instructions/PG.md and requirement_definition.md."
python -m vibecodehpc.ipc send PG1.1 "[PM] [Request] Report your current status."
python -m vibecodehpc.ipc health PG1.1
```

## 限界

- 受信箱は待機中のセッションを起こさない。文はセッションの次の出来事(道具の呼び出し、新しい turn、今の turn の終わり)を待つ。別の Claude のセッション(例えば PM)からの `SendMessage` なら起こせる。
- つないだのは Claude Code だけ。他の CLI にはこの種のバックグラウンドのセッションと cross-session messaging が無い。
- cross_session backend は登録表を書かない。バックグラウンドの id は `Agent-shared/ipc/sessions.json` に残す。`python -m vibecodehpc send` は tmux のペインに打ち込むので、これらのエージェントには届かない。`python -m vibecodehpc.ipc send` を使う。
- PM の指示書は tmux の流れのまま。Windows ネイティブの PM には要件定義で「起動と生死は `python -m vibecodehpc.ipc`、エージェントとの会話は `SendMessage`」と書く。

## 試験の状況

| 確かめた事 | 結果 |
|---|---|
| 新しい module の `py_compile`(Windows の Python 3.10) | 通過 |
| Windows ネイティブ、モデルなし: 受信箱の送りと取り出し、`UserPromptSubmit` と `Stop` の hook の出力、hook の入れ直し、backend の選択、CLI | 通過 |
| Windows ネイティブ、実物: hook を入れた作業 dir の `claude -p` が受信箱の文を受け取る | 通過 |
| Windows ネイティブ、実物: Python から `claude --bg`、`claude agents --json` から id、生死、`stop`、`rm` | 通過 |
| 実物: Windows ネイティブの2つのセッションの間の `SendMessage` | 未実施: 相手の一覧が機械の全セッション(無関係な物も)を含むため |
| `--launcher wt` | 未実施 |
