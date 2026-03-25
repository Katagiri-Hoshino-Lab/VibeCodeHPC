# ディレクトリ & ペイン配置図

> PMがプロジェクトルートにこのファイルを生成する。エージェントの配置・再配置のたびに即座に更新すること。全エージェントとユーザにとっての**唯一の配置図**。

## パターンA: HPC最適化（compiler/strategy分割）

```
📂VibeCodeHPC-v1.0.0 🤖PM
├── 📁GitHub 🤖CD ⬛
└── 📂Flow/TypeII
    ├── 📂single-node 🤖SE1 🟨
    │   ├── 📄hardware_info.md
    │   ├── 📂gcc11.4.0
    │   │   ├── 📁OpenMP 🤖PG1.1 🟦
    │   │   ├── 📁MPI 🤖PG1.2 🟦
    │   │   └── 📁AVX2 🤖PG1.3 🟦
    │   ├── 📂intel2024
    │   │   ├── 📁OpenMP 🤖PG1.4 🟪
    │   │   └── 📁MPI 🤖PG1.5 🟪
    │   └── 📂nvidia_hpc
    │       └── 📁CUDA 🤖PG1.6 🟫
    └── 📂multi-node 🤖SE2 🟡
        ├── 📄hardware_info.md
        ├── 📂gcc11.4.0
        │   └── 📁MPI 🤖PG2.1 🔵
        └── 📂intel2024
            └── 📁MPI 🤖PG2.2 🟣
```

### tmuxレイアウト（10ワーカー、4x3グリッド）

| | | | |
|:---|:---|:---|:---|
| 🟨SE1 single-node | 🟦PG1.1 gcc/OMP | 🟦PG1.2 gcc/MPI | 🟦PG1.3 gcc/AVX2 |
| 🟪PG1.4 intel/OMP | 🟪PG1.5 intel/MPI | 🟫PG1.6 nvidia/CUDA | 🟡SE2 multi-node |
| 🔵PG2.1 gcc/MPI | 🟣PG2.2 intel/MPI | ⬛CD | ⬜ |

---

## パターンB: マルチCLI競争（CLI/model分割）

```
📂VibeCodeHPC-main 🤖PM 🟧 claude/opus-4.6
└── 📂Local
    ├── 📁sota 🤖SE1 🟩 codex/gpt-5.4
    ├── 📁context 🤖SE2 🟧 claude/opus-4.6
    └── 📂gcc
        └── 📂OpenMP
            ├── 📁work1 🤖PG1.1 🟫 cline/sonnet-4.6
            ├── 📁work2 🤖PG1.2 🟥 vibe-local/qwen3.5:35b
            ├── 📁work3 🤖PG1.3 🟦 gemini/Gemini-3
            │
            ├── 📁work4 🤖PG2.1 🟪 qwen/qwen3.5-plus
            ├── 📁work5 🤖PG2.2 ⬛ opencode/qwen3-next-80b
            └── 📁work6 🤖PG2.3 🟨 kimi/kimi-code
```

### tmuxレイアウト（8ワーカー、2セッション）

#### Workers1
| | |
|:---|:---|
| 🟩SE1 codex/gpt-5.4 | 🟫PG1.1 cline/sonnet-4.6 |
| 🟥PG1.2 vibe/qwen3.5 | 🟦PG1.3 gemini/Gemini-3 |

#### Workers2
| | |
|:---|:---|
| 🟧SE2 claude/opus-4.6 | 🟪PG2.1 qwen/qwen3.5+ |
| ⬛PG2.2 opencode/qwen3-80b | 🟨PG2.3 kimi/kimi-code |

---

## 対応CLI

claude, codex, cline, gemini, opencode, vibe-local, qwen, kimi

> 詳細: [CLI対応表](cli_support_matrix.md)

## 注意事項

- `vibecodehpc launch` やエージェント再配置のたびに**即座に更新**すること
- PMがプロジェクト種別に応じてパターンAまたはBを選択する。両方の混合も可。

### 設計意図
- compiler/hardwareごとに別の 📂 → Makefile/フラグの衝突を防止
- strategy（OpenMP/MPI/CUDA）はflat 📁 → PGが独立して作業
- SEはスコープ（single-node vs multi-node）またはチーム単位で管理
- 色 = compilerグループ（A）またはCLIブランド（B）— 一目で識別
- 意味のない中間directoryを置かない
