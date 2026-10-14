# VibeCodeHPC のエージェントのための自前の推論

自前の推論エンジンを立てて Claude Code(と Codex CLI)をそこに向ける方法と、多数のエージェントで1台のサーバーを共有するときのサーバー側の注意点。バッチジョブ一式は [samples/self_hosted_inference_on_hpc](../samples/self_hosted_inference_on_hpc/README.md)(日本語: [samples/ja/self_hosted_inference_on_hpc.md](../samples/ja/self_hosted_inference_on_hpc.md))。

## 何をどこで動かすか

2つの選択は独立している: エージェントの CLI(ハーネス)をどこで動かすかと、モデルをどこで出すか。

| | ベンダーの API のモデル | 自分の機械で出すモデル | HPC のジョブの中で出すモデル |
|---|---|---|---|
| **ハーネスは手元の PC** | VibeCodeHPC の既定の構成。ジョブは SSH でクラスタへ | 手元に GPU が要る | PC から計算ノードへの経路が要る(認めるサイトは少ない) |
| **ハーネスは HPC のジョブの中** | 計算ノードから外への通信が要る | 計算ノードから手元の機械へ戻る経路が要る | 全部がノードの中で閉じる([サンプル](../samples/ja/self_hosted_inference_on_hpc.md)) |

VibeCodeHPC はどの組み合わせでも動く。一番簡単なのはハーネスを手元の PC で動かす形である。クラスタへ移すときは、外への通信の可否と、共用のログインノードにかける負荷を先に確かめる。最後の欄は閉じた計算ノード向けで、モデルもエージェントも道具も1つの確保枠の中で動き、外へ何も出ない。

## エンジンの選び方

| エンジン | API | GPU 4枚の1ノードで動かした所見 |
|---|---|---|
| vLLM(公式のコンテナイメージ) | Anthropic Messages、OpenAI Responses と Chat | Claude Code と `codex exec` をそのまま向けられる。投機デコード(MTP head、n-gram、draft model)と CPU への KV offload は flag で選ぶ |
| SGLang(公式のコンテナイメージ) | OpenAI Chat(他は未確認) | 同じ大きな MoE モデルを出せる。CLI は向けていないので、エージェントが Claude Code なら vLLM を使う |
| llama.cpp server | OpenAI Chat | そこでは動かしていない。大きなモデルは先に形式の変換が要る |

エンジンは公式のコンテナイメージを使い、サイトのコンテナ形式(Singularity/Apptainer)に一度だけ変換する。重みは公開されたままで使う。

## エンドポイント

Claude Code は Anthropic Messages API(`/v1/messages`)を話す。Codex CLI など多くの CLI は OpenAI API(`/v1/chat/completions` か `/v1/responses`)を話す。vLLM は1つのプロセスで両方を出すので、CLI が混在する組織も1台のサーバーで賄える。

## Claude Code: 環境変数

`python3 -m vibecodehpc setup` の前に export する。tmux サーバーは起動したシェルの環境を受け継ぎ、各ペインは tmux サーバーから受け継ぐ。tmux サーバーが既に動いていると古い環境のままなので、先に止めるか `tmux set-environment -g` を使う。

| 変数 | 値 | 理由 |
|---|---|---|
| `ANTHROPIC_BASE_URL` | `http://127.0.0.1:8000` | サーバーのアドレス(`/v1` は付けない) |
| `ANTHROPIC_AUTH_TOKEN` | 空でない任意の文字列 | Claude Code は認証情報を要求する。vLLM は `--api-key` を付けない限り無視する |
| `ANTHROPIC_API_KEY` | unset | 本物のキーをローカルサーバーへ送らない |
| `ANTHROPIC_MODEL` | サーバーのモデル名 | 主モデル |
| `ANTHROPIC_DEFAULT_OPUS_MODEL`、`ANTHROPIC_DEFAULT_SONNET_MODEL`、`ANTHROPIC_DEFAULT_HAIKU_MODEL`、`ANTHROPIC_SMALL_FAST_MODEL` | サーバーのモデル名 | Claude Code は裏の処理で小さいモデルも呼ぶ。サーバーが知らない名前だと失敗する |
| `CLAUDE_CODE_SUBAGENT_MODEL` | サーバーのモデル名 | サブエージェント |
| `CLAUDE_CODE_MAX_OUTPUT_TOKENS` | 例 `32000` | プロンプトと出力の和をサーバーの `--max-model-len` 未満に保つ |
| `CLAUDE_CODE_EFFORT_LEVEL`、`CLAUDE_CODE_ALWAYS_ENABLE_EFFORT=1` | 任意 | Claude Code は既知のモデル名にしか effort を送らない(強制しない限り)。効くかはサーバーがモデルのチャットテンプレートへどう写すか次第なので、推論の長さで確かめる |
| `DISABLE_AUTOUPDATER`、`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`、`DISABLE_TELEMETRY`、`DISABLE_ERROR_REPORTING` | `1` | 閉じた計算ノードから外へ通信しない |
| `http_proxy`、`https_proxy`(大文字も) | unset、`NO_PROXY=127.0.0.1,localhost` | 計算ノードは proxy を export していることが多く、localhost への要求が proxy 経由で失敗する |

無人のノードでは `vibecodehpc/scripts/seed_claude_home.py` で初回の画面にも先に答えておく。v2 は CLI 起動の3秒後に Enter を1回送るだけで、フォルダの信頼確認は越えるが、初回案内と bypass-permissions の警告は越えられない。

## Codex CLI: プロバイダ

`OPENAI_BASE_URL` をグローバルに設定しない([CLI対応表](cli_support_matrix.md))。代わりに `~/.codex/config.toml` にプロバイダを定義する(例えばジョブ専用の HOME に置く):

```toml
model = "local"
model_provider = "local"

[model_providers.local]
name = "local vLLM"
base_url = "http://127.0.0.1:8000/v1"
wire_api = "responses"   # サーバーと Codex の版が対応する方("chat" か "responses")
```

キー名は Codex の設定リファレンスに従う。使う版で確かめること。この経路は測定した構成(Claude Code のみ)では動かしていない。

## サーバーの設定

- **ツール呼び出し。** モデルに合うツール呼び出しのパーサー(`--enable-auto-tool-choice --tool-call-parser ...`)と、あれば推論のパーサーを付けて vLLM を起動する。パーサーが無いとツール呼び出しが平文で返り、エージェントは何もできない。
- **同時数。** `--max-num-seqs` は全エージェントとそのサブエージェントを賄う数にする。超えた要求は待たされ、エージェントが応答しないように見える。
- **文脈長。** `--max-model-len` はプロンプトと出力の和の上限。エージェントのプロンプトは auto-compact まで上限近くまで伸びるので、出力の上限分を空けておく。
- **文字だけのモデル。** サーバー(`--limit-mm-per-prompt '{"image":0,"video":0,"audio":0}'`)とエージェント(`deny_media_read.py` の hook、`seed_claude_home.py --text-only`)の両方で画像などを断る。サーバーは画像に "At most 0 image(s) may be provided in one prompt" と返し、会話に画像が1つ入るとその会話の以後の要求が全部失敗する。VibeCodeHPC の監視は PNG の図を書き、エージェントはそれを読もうとする。
- **投機デコード。** `serve.sh` の引数で選ぶ(`mtp:K`、`ngram:K`、`METHOD:K:DRAFT_PATH`)。受理は自分の負荷で測る。`org_summary.py` が平均受理長と draft の位置ごとの受理率を出す。

## hybrid モデルの prefix cache

エージェントの要求は長い prefix(システムプロンプト、ツール定義、それまでの会話)を共有する。その prefill を安く保つのが prefix cache である。

sliding window の層と全体 attention の層を混ぜたモデルでは注意が要る。使った版の vLLM では、`prefix_cache_retention_interval` が既定の 0 のとき、sliding window 層の cache はプロンプトの終わりと、既に共有 prefix の継ぎ目と分かった位置にしか残らなかった。そのため新しい共有 prefix は2本目の要求で外れ、3本目から当たった。2本目は全部を prefill し直す。

`--prefix-cache-retention-interval 4096`(KV のブロックサイズの倍数)を付けると、sliding window 層の状態がその間隔で残る。測定では、直前と 90% を共有する 64K トークンのプロンプトが2本目から予想どおりの率で当たり、最初のトークンまでの時間が約5分の1になった。

測っていないこと: 異なる prefix が多数あるときの cache の圧迫、4096 以外の値、投機デコードや KV offload との組み合わせ。この flag は vLLM の版による。`vllm serve --help` で確かめる。`serve.sh` では `LLM_PREFIX_RETENTION` で渡す。

## hybrid モデルの KV と KV connector

vLLM の hybrid memory allocator は sliding window 層について窓の分だけを持つ。これに対応しない KV connector を付けると、vLLM は allocator を切り、"Turning off hybrid" を含む行をログに出す。すると sliding window 層も全長を持ち、層の大半が sliding window のモデルでは 1 トークンあたりの KV が数倍になる。前は載った長い要求が載らなくなることがある。

connector を付けたら、`server.log` にその行が無いかを見て、connector なしの時と KV のトークン容量を比べる。`serve.sh` は `LLM_CPU_OFFLOAD_GB` で vLLM 自前の CPU offload connector を有効にし、サンプルのジョブは ready の前にサーバーが落ちたら connector なしで1回だけ起動し直す。

## 時間の前提

VibeCodeHPC の決まり(3分以内に ACK、5分黙ったエージェントは落ちた疑い)は速いクラウドの API を前提にしている。1台のローカルサーバーを多数で使うと応答は遅くなるので、`requirement_definition.md` で期限を緩める。`Agent-shared/periodic_monitor_config.json` の `max_runtime_min` をジョブの長さに合わせる(既定では 120 分で監視が止まる)。

## Claude Code 自身の cross-session messaging

Claude Code には、同じマシンのセッション同士を per-session の socket か named pipe でつなぐ機能(`ListAgents`、`SendMessage`)がある。執筆時点の Claude Code の文書によれば:

- WSL2 のセッションと Windows ネイティブのセッションは、同じ PC でも互いに届かない。エージェントは同じ側に揃える。
- `--bare` で起動したセッションは受信箱を作らない。
- 受信側は受け付け・保留・拒否を選べる(`crossSessionInbound`)。

VibeCodeHPC はこの機能に頼らない。`vibecodehpc send` は tmux のペインに文字を打ち込み、文字と Enter を分けて送る。どの CLI でも動くが、Claude Code の文書にあるインターフェースの外である。

## 確認項目

- [ ] サーバーが `curl http://127.0.0.1:8000/health` に答え、`/v1/models` にモデル名が出る。
- [ ] 上の環境で `claude -p "say ok"` が文字を返し、ツールが要る依頼(`claude -p "list the files here"`)でツールを呼ぶ。
- [ ] `--max-num-seqs` が全エージェントを賄い、`CLAUDE_CODE_MAX_OUTPUT_TOKENS` と最大のプロンプトの和が `--max-model-len` 未満。
- [ ] 文字だけのモデルなら、画像を断る hook が入り、サーバーも断る。
- [ ] hybrid モデルなら、意図しない限り `server.log` に "Turning off hybrid" の行が無く、prefix cache が2本目から当たる(`org_metrics.sh`)。
