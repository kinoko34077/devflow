# Specification

このディレクトリは、横断仕様・提案仕様・例・受入記録が保管される
文書領域である。ディレクトリ名やファイル名だけでは現行性・効力・受入を
判定しない。機能単位の入口は [`../../features/README.md`](../../features/README.md)、
現行状態・権限・作業指示はlive Control、Issue、PR、CIおよび各ownerの正本を
確認する。

- 下記の一覧は、横断的な現行仕様の代表的な入口であり、ディレクトリ全体の網羅的な分類ではない
- 提案・履歴・例を現行契約へ昇格させない。採用状態はowner Issue/PRと現行コードで再確認する
- 仕様変更が確定した場合は必要に応じて `docs/decisions/` に理由を残す
- Issueやチャット上の指示と衝突した場合は、最新の明示決定と個別正本を優先する

## Current specifications

- [CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md](./CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md) — cross-repository authority and operating model
- [DEVELOPMENT_RECONCILIATION.md](./DEVELOPMENT_RECONCILIATION.md) — deterministic evidence-to-disposition contract for devflow#155/#156
- [DEVELOPMENT_RECONCILIATION_PUBLICATION.md](./DEVELOPMENT_RECONCILIATION_PUBLICATION.md) — deterministic reviewer/recovery work-demand publication contract for devflow#159
- [CHAT_WORKER_BOOTSTRAP.md](./CHAT_WORKER_BOOTSTRAP.md) — provider-neutral manual-started chat-worker bootstrap contract v1 for devflow#191 (schemas in `schemas/`, examples in `examples/chat-worker-bootstrap/`)
- [CHAT_WORKER_PROFILES.md](./CHAT_WORKER_PROFILES.md) — per-session worker identity/capability/environment profiles for devflow#195 (#190 Phase B)
