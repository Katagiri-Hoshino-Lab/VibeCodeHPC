# Token Keeper

定額の CLI の契約には、口座ごとに窓(多くは 5 時間と 1 週間)ごとの利用上限がある。多数のエージェントの組織は、窓を半日で使い切ることがある。Token Keeper は各窓の使用率を読み、数分ごとに記録し、窓がしきい値を越えたら門を閉じる。門が閉じている間、`vibecodehpc launch` はエージェントを起こさず、PM には1回だけ知らせる。

設定しない限り動かない。`Agent-shared/quota/state.json` が無いとき、または読み取りの間隔3回分より古いときは、何も止めない。

## 読む物

どの読み手も資格情報のファイルを開かない。保存するのは百分率・窓の名前・回復の時刻だけである。

| 読み手(`type`) | 提供元 | 方法 |
|---|---|---|
| `codex_rollouts` | Codex CLI | Codex が自分の会話の記録(`$CODEX_HOME/sessions/**/rollout-*.jsonl`)に書く `rate_limits` の、契約の種類ごとの最新の値。その口座で最後に Codex が回った時点の値 |
| `claude_usage` | Claude Code | 専用の tmux セッションで Claude Code を開き、`/usage` を出して画面を読み、閉じる。CLI は自分のログインを使い、モデルへの要求はしない。任意で有効にする。tmux が要る |
| `command` | 何でも | 指定のコマンドを走らせる。標準出力は `{"window", "used_pct", "resets_at", "provider", "account"}` の JSON の配列。他の欄は捨てる |

窓の名前は `5h`、`week`、`week:<モデル>`(Claude Code のモデル別の週の窓)、`<分>m`。

## 設定

`Agent-shared/quota_config.json`:

```json
{
  "sources": [
    {"type": "codex_rollouts", "account": "personal", "codex_home": "~/.codex"},
    {"type": "claude_usage", "account": "personal"},
    {"type": "claude_usage", "account": "org", "config_dir": "~/.claude-org"}
  ],
  "thresholds": {"claude": {"5h": 90, "week": 90}, "codex/personal": {"week": 85}},
  "notify": "PM",
  "interval_s": 300
}
```

しきい値の鍵は `provider` か `provider/account` で、細かい方が優先する。窓の使用率がしきい値以上なら門を閉じる。

## 動かし方

```bash
# cron で 5 分ごと(常駐の loop を持たないので推奨)
*/5 * * * * cd /path/to/project && python3 -m vibecodehpc.monitor.quota --once
# あるいは常駐で(バッチジョブの中など)
python3 -m vibecodehpc.monitor.quota --interval 300 &
```

Windows では `--once` の形をタスクスケジューラに登録する。`claude_usage` は tmux が要るので Windows では使えない。

## 出力(`Agent-shared/quota/`)

| ファイル | 中身 |
|---|---|
| `quota.log` | 1回の読み取りにつき1行。例 `2026-10-14T02:45:08+00:00 claude/personal 5h 9% / week 3% \| codex/personal:pro 5h na / week 52% \| pause_new_seats no` |
| `usage.jsonl` | 全部の読み取りの全部の窓(図にする用) |
| `state.json` | 最新の窓、`pause_new_seats`、理由、`valid_until` |

## 門

- 門が閉じている間、`vibecodehpc launch` は理由を出して終了コード 3 で終わる。`--ignore-quota` で越えられる(ユーザーが明示的に頼んだ時だけ)。
- 門が閉じた時と開いた時に、keeper は PM に1通(`[TK] [Warning]` か `[TK] [Report]`)を `vibecodehpc send` で送る。
- PM の指示書(「Allocate Agents by Quota」)は、エージェントを起こす・配り直す前に `quota.log` を読み、新しい仕事を余裕のある口座へ回すよう求める。

## 注意

- Codex の値は Codex が最後に見た時点の値である。何時間も turn を回していない口座は古い値のまま。
- `/usage` の画面の形は Claude Code のものなので、将来の版で変わったら、読み手は誤った数を出さずに「usage screen not recognised」と記録する。
- tmux のペインに手で知らせを送るときは `vibecodehpc send` と同じ型を使う: ペインに許可や利用上限の問いが出ていないことを確かめ、文を打ち、Enter を別に送り、画面で受け取られたことを確かめる。
