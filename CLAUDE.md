# CLAUDE.md

最初に `AGENTS.md` を読み、その指示を最上位のリポジトリ内運用規則として扱うこと。

## レビュー依頼の扱い（必須）

- 「PRをレビューして」等の依頼は、チャットへの回答だけで完結させない。必ず GitHub 上の PR に Review として記録を残すこと。
- 記録する内容は、指摘事項（根拠と再現手順を含む）、確認した範囲と未確認の範囲、判定（APPROVE / COMMENT / REQUEST_CHANGES）、レビュー対象の head SHA、Review Provenance v2 の署名（Reviewer-System / Reviewer-Model など）。
- 行に紐づく指摘は inline comment にし、`pull_request_review_write` で pending review を作成して提出すること。
- チャットでは要約と PR/Review へのリンクのみ報告する。
- 実装者と同一システム・モデルの場合は different-reviewer ゲートを満たさない旨を明記する。
- 提出済みの Review は履歴として残す。再レビュー時は新しい Review を追加し、過去の Review を編集・削除しない。
