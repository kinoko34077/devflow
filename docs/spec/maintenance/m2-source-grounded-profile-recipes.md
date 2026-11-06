# SMC M2 — 実ソースに基づく監査プロファイル候補（5リポ横断・2026-10-16）

Owner: [devflow #588](https://github.com/kinoko34077/devflow/issues/588) / M2。根拠となる共通方針は [M0–M3 rubric](multi-angle-audit-coverage-v1.md)、[12-Lens Common Baseline](common-baseline.v1.yaml)、完了した [#363](https://github.com/kinoko34077/devflow/issues/363)。

**状態: SOURCE-GROUNDED PROPOSAL / READ-ONLY。** 本文はリポ固有監査の候補と未検証境界を定義する。実監査、Ledgerへの完了記録、カタログ採用、リスク格下げ、PILOT増枠、実機検証、公開・運用開始の証拠ではない。2026-10-16時点に確認した各リポのControlと実ファイルに依拠する。出典の履歴・監査SHAと現在HEADは同一視しない。続行前に毎回該当リポの最新Control/owner/sourceを再確認する。

## 1. 作成方法・共通の適用判断

1. **責務境界から監査単位を作る。** 同一リポにWeb / ネイティブ / 外部サービス等が共存する場合、単なるリポ全体の「STANDARD済み」に合算しない。1単位を `repo × component/scope × Lens × Depth × code+catalog/external fingerprint` で識別する。
2. **12 Lens IDは維持する。** a11y、リアルタイム音声、原典真正性、研究再現性などは新しい「共通Lens」の増殖ではなく、原則として既存Lensに付けるリポ固有の検査方法・slot候補として表現する。独立した失敗原因・証拠・除外理由が明示できる場合のみ専用slotを提案する。
3. **リスクはリポControlと対象コンポーネントで別々に評価。** 以下のControl表示の `MEDIUM` は当時のリポ分類であり、認証処理や音声RTといった高リスク境界を自動的にMEDIUMへ下げる根拠にならない。提案したslotの `risk_override` は採用時にownerが実ソース・権限・影響範囲を吟味して決定する。
4. **検査結果と検査可否を混同しない。** 実ブラウザ・FL Studio・実Worker・外部原典・二台の研究実験などの観測がない限り、それぞれを `UNKNOWN/NOT_RUN` とする。CI成功、v2 `ATTESTED_SCOPE_MATCH`、Control監査SHA、README記載だけから現在スコープのCLEANを導かない。
5. **採用の最小条件。** repo-local owner Issue、仕様/コードの新鮮な確認、カタログ変更PR、schema検証、リスク/除外理由、owner Ledger、latest-HEAD CI、独立Review、merge後検証。候補の記録自体はPILOT追加でも供給でもない。

## 2. 5リポの実ファイル・Control観測

| リポ（Control） | 確認した構成・出典 | 監査時に分離すべきスコープ |
| --- | --- | --- |
| [frequency-warp-vst](https://github.com/kinoko34077/devflow/issues/500) | [README](https://github.com/kinoko34077/frequency-warp-vst/blob/main/README.md)、[DSP構成](https://github.com/kinoko34077/frequency-warp-vst/blob/main/docs/SHARED_DSP_ARCHITECTURE.md)、[仕様](https://github.com/kinoko34077/frequency-warp-vst/blob/main/docs/SPECIFICATION.md)。Rust `core/` をnative/WASM共有し、WebのAudioWorkletとVST3 shellに別の検証境界がある。 | 数学oracle、Rust streaming DSP、WASM/AudioWorklet、Web UI/Pages、Windows VST3/DAW、交換式engine |
| [japanese-orthography](https://github.com/kinoko34077/devflow/issues/180) | [AGENTS](https://github.com/kinoko34077/japanese-orthography/blob/main/AGENTS.md)、[README](https://github.com/kinoko34077/japanese-orthography/blob/main/README.md)、[owner #349](https://github.com/kinoko34077/japanese-orthography/issues/349)。`data/evidence/`、`data/lexical/constraints/`、`data/packs/contextual-kanji/` が正本、`dist/contextual-kanji/` は生成物。 | 原典・出典拘束、Pack/lexical compiler、runtime resolver、生成物・golden、実TAR/Workerの信頼境界 |
| [UniverseGenome](https://github.com/kinoko34077/devflow/issues/314) | [README](https://github.com/kinoko34077/UniverseGenome/blob/main/README.md)、[仕様index](https://github.com/kinoko34077/UniverseGenome/blob/main/docs/SPECIFICATION.md)、[研究owner #275](https://github.com/kinoko34077/UniverseGenome/issues/275)。決定的Inner physicsとOuter探索、seed固定の実験・性能比較を分離。 | 物理/状態遷移、データ・checkpoint、seed比較・selection、測定driver、host依存の性能結果 |
| [kinotch-api](https://github.com/kinoko34077/devflow/issues/18) | [AGENTS](https://github.com/kinoko34077/kinotch-api/blob/main/AGENTS.md)、[README](https://github.com/kinoko34077/kinotch-api/blob/main/README.md)、[Current State](https://github.com/kinoko34077/kinotch-api/blob/main/project/docs/CURRENT_STATE.md)。Cloudflare public Gateway、private Workers、Access保護Remote MCP、Service Bindingを区別。 | Public API、private service、認証・認可境界、外部プロバイダ、デプロイ/rollback、machine-local Token E2E |
| [tarot-draw](https://github.com/kinoko34077/devflow/issues/371) | [README](https://github.com/kinoko34077/tarot-draw/blob/main/README.md)、[仕様](https://github.com/kinoko34077/tarot-draw/blob/main/docs/SPECIFICATION.md)、[audit owner #126](https://github.com/kinoko34077/tarot-draw/issues/126)。Node/Cloudflare APIがshuffle/sessionを所有し、Pages Web UIとbrowser-local履歴は別責務。 | Deck/branch/draw状態、Durable Object/expiry、Web UI/コピー、localStorage/インポート、公開API/Pages接続 |

上記は各実ファイルとControlに記録された責務境界の列挙であり、全機能・リスクの現地網羅性はまだ保証しない。Controlの対象リポはすべて当該観測でACTIVEかつリポリスクMEDIUM。SMC v1のカタログは既存3 PILOT（devflow、execution-coordinator、kinotch-repository-base）のみに認可済みであり、この5リポにカタログを作成・適用していない。

## 3. リポ別の候補検査と成立に必要な証拠

| リポ / 候補scope | 適用する既存Lens | 実行する具体的検査・残す根拠 | 単独では合格と見なせない証拠 |
| --- | --- | --- | --- |
| Frequency Warp / `core/src/stream.rs` と数学的mapping | `correctness`, `edge-cases`, `resource-management`, `spec-implementation-drift` | 固定WAV/サンプルレート/FFT条件、DC・Nyquist・ゼロ近傍・位相/遅延を独立oracleと出力比較。音声処理中の過剰割当、CPU/latency計測。入力fixtures・出力差分・環境・actual source SHAを添付。 | UIでグラフが描画されたこと、共通Rust関数をWebが呼べたこと、通常ユニットテスト成功 |
| Frequency Warp / Web AudioWorklet / Pages | `correctness`, `reliability-recovery`, `error-handling`, `edge-cases` | 破損ファイル、unsupported codec、音声処理不成立時のoriginal fallback、再生中パラメータ操作、画面リフロー/タッチ、公開Pages実配信を個別試験。実ブラウザ/OS・ソース/公開SHAを保存。 | Chrome CIのみから物理iPhone Safari・WebAudio動作を主張すること |
| Frequency Warp / native VST3 + engine切替 | `state-integrity-concurrency`, `reliability-recovery`, `resource-management`, `correctness` | automation ID安定性、DAWでの保存・復元、multi-instance、失敗時旧engine維持、非RT側準備とaudio callbackの資源・ロック境界をWindows Validator+実DAWで確認。 | Validator passのみからFL Studio/他DAW実機受入・本番音質を認定すること |
| Japanese Orthography / lexical source→Pack→runtime | `correctness`, `security`, `spec-implementation-drift`, `test-quality` | 出典原文/byte digest、source-qualified lexical ID、Pack生成と実VM producerの帰属証拠、golden parity、改変/偽Pack/不正参照拒否の正負テスト。原典/fixture/production経路を別記。 | fixture内のdigest一致から本番producer真正性や全TAR互換を推定すること |
| Japanese Orthography / Unicode処理・生成物 | `edge-cases`, `reliability-recovery`, `resource-management`, `state-integrity-concurrency` | 旧字旧かな、ルビ/変換不変箇所、未定義字、UTF-8境界、stream chunk、large payload、compile失敗時のatomic rollback。raw入出力・golden・memory/時間を記録。 | `dist/` の手書替え、短いfixtureだけの速度を20MB実文速度に外挿すること |
| UniverseGenome / Inner physics と保存状態 | `correctness`, `state-integrity-concurrency`, `reliability-recovery`, `spec-implementation-drift` | 決定的seed/revision/実験条件、凍結oracleとのbit/parity、journal/checkpoint中断回復、研究-only値の非既定性を検証。 | random seed未固定の単発出力、改変した測定条件の再計測 |
| UniverseGenome / Outer search とhost性能 | `test-quality`, `resource-management`, `dependency-external-assumptions`, `observability` | 探索とheld-outの分離、negative sentinel、同一source・seed・hostの比較、RSS/時間/CIハッシュ、測定の統計的限界と失敗観測を保持。 | 高速化比のみから科学的な学習成立・別host性能・本番採用を結論すること |
| kinotch-api / Gateway→private Worker→MCP | `security`, `state-integrity-concurrency`, `error-handling`, `reliability-recovery` | 公開RESTとAccess/Service Token経路の認可正負、異なるTokenの非互換、秘密値の非ログ化、429/403/上流Timeout/重複Request/部分失敗を隔離テスト。認証主体・実行環境・実際の副作用を記録。 | mock/CIで正しいことからProduction Accessやmachine-local専用Token E2Eまで成立したと主張すること |
| kinotch-api / release/prod状態 | `lifecycle-consistency`, `dependency-external-assumptions`, `observability` | 現行main・固定lockfile・dry-run・正式releaseのソースSHAと公開実URLを区別し、正式運用ownerと実smokeを照合。 | main上の依存PR mergeのみでProductionが更新されたと扱うこと |
| tarot-draw / session+deck+branches | `correctness`, `state-integrity-concurrency`, `security`, `edge-cases` | 78/80 deck境界、no-duplicate draw、並列branch独立性、予備カード不足、他session操作、TTL/Rate LimitingをAPI・Durable Objectの責務でテスト。 | Web画面の結果だけでAPI/Worker実際の状態更新を推定すること |
| tarot-draw / browser history+Pages | `reliability-recovery`, `error-handling`, `edge-cases`, `correctness` | localStorage破損/容量/拒否、全消去write失敗、Markdown読み込み部分互換、read-only復元、モバイル画面・コピー、API非接続時のfail-closedを試験。 | browser cacheを永続server履歴と扱うこと、1種browser CIのみで全端末合格とすること |

## 4. 明示的な非対象・保留・対立回避

- 本文には単一repoの包括的CLEANを付与しない。特に物理iOS Safari、FL Studio等の実DAW、JO実Pack可信producer/実TAR、UniverseGenome別hostの独立研究評価、kinotch-api専用Token real E2E、tarot-draw Cloudflare現在production状態は**この文書作成では未実行**。
- `security` はどのリポにも条件付きで残す。公開HTTP、署名・トークン、原典帰属、マルチテナント、ローカル保存など、**境界の違う負例**を検査する。検査対象なしと判断する場合はownerが根拠と除外理由を残す。
- `CONTROL`はControl/Issueの整合のみ。`STANDARD`は表内の対象に対する正負試験が必要。`DEEP`も実施したscope/Lensのみの記録であり、他scope/Lensの自動充足ではない。
- 独立製品開発のowner Issue（Frequency #172/#183、JO #349、UniverseGenome #275、API #9、Tarot #39/#92等）へ介入せず、監査で見つかった独立不具合は正しいownerに記録する。実装者と監査者の同一HEAD競合を避ける。
- **既存3 PILOT以外**の `.devflow/maintenance.yaml` 新設、Ledger採用、`PILOT`/ `ENABLED` 変更、実行供給・claim・credentials・permission・公開は一切しない。これらはM5証拠・M6の個別owner/安全審査・独立した認可が必要。

## 5. 次に必要なM2→M5の受入証拠

- M2を全管理対象へ広げるには、各repoの最新Control / Current State / main /製品別危険境界を読み、上記と同じ列（scope、Lens、Depth、positive/negative evidence、非対象、risk rationale、実検査実施可否）を個別に埋める。49/51などの数値は古い観測を無条件に転用せず、必ず時点を固定する。
- 実際のcatalog rolloutは、まず既存3 PILOTの本物の現在状態を再チェックし、#209 source-based 3C publish→別attempt claim/ack→実監査→信頼済みLedger completionとwithdrawを確認してから判断する。対象がない状態でM5を満たした扱いにしない。
- 検出価値はLens別の **検出した真の問題/重複/誤検出/未検証条件/調査コスト** で比較する。今回の表は実施手順候補であり、その測定結果ではない。

## 6. 参照の固定境界

2026-10-16時点の直接読取根拠: `frequency-warp-vst` README blob `d06d8d47`、DSP doc `d7a73d09`、spec `9757fc44`、Control #500。 `japanese-orthography` AGENTS `c5e07d72`、README `42e69a37`、Control #180。 `UniverseGenome` README `19fb1878`、spec `3656525a`、Control #314。 `kinotch-api` AGENTS `55c0193c`、README `af0aeed0`、Current State `96a17364`、Control #18。 `tarot-draw` README `b92435d0`、spec `c2c47605`、Control #371。文字列は読取対象blobの識別であり、最終main SHAや全ファイル同時スナップショットではない。
