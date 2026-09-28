# Specification

このディレクトリには、現在有効な仕様だけを置く。

- 過去案や作業ログは置かない
- 仕様変更が確定した場合は必要に応じて `docs/decisions/` に理由を残す
- Issueやチャット上の指示と衝突した場合は、最新の明示決定を反映して更新する

## Current specifications

- [CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md](./CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md) — cross-repository authority and operating model
- [DEVELOPMENT_RECONCILIATION.md](./DEVELOPMENT_RECONCILIATION.md) — deterministic evidence-to-disposition contract for devflow#155/#156
- [DEVELOPMENT_RECONCILIATION_PUBLICATION.md](./DEVELOPMENT_RECONCILIATION_PUBLICATION.md) — deterministic reviewer/recovery work-demand publication contract for devflow#159
- [CHAT_WORKER_BOOTSTRAP.md](./CHAT_WORKER_BOOTSTRAP.md) — provider-neutral manual-started chat-worker bootstrap contract v1 for devflow#191 (schemas in `schemas/`, examples in `examples/chat-worker-bootstrap/`)
