# DEC-0001: GitHub-native, implementer-agnostic execution

- Status: Accepted
- Date: 2026-09-24
- Related issues: #1, #2

## User statement — verbatim

> てかなんなら、ここで全て完結するならCodex無しでもいいんだけど
>
> 試しに、
> 現行版確認
> 監査
> 現状のいい点、問題点などの指摘
> 次の指示書の作成
> 実際にそれらへの着手
>
> を回せられない？指摘などはissueだとかみたいなGitHubの機能を最大限フル活用していい

## Normalized decision

GitHubを開発状態・作業履歴の中心に置き、実装主体をCodexへ固定しない。

監査、Work Order作成、branch上の実装、Pull Request、再監査までを、利用可能な実装主体がGitHub上の同じIssue / PRを参照して継続できる構造にする。

ChatGPTからGitHubへ直接変更できる場合は、Codexを経由せず実装まで進めてよい。

## Supersedes

初期READMEおよびIssue #1に含まれていた「ChatGPTで監査・整理し、Codexで実装する」という実装主体固定の前提。

## Rationale

開発状態をGitHubへ集約する目的は、特定のチャットや実装ツールへ状態を閉じ込めず、監査済み範囲、実装指示、差分、検証結果を継続的に追跡可能にすることにある。実装主体を固定すると、この目的に対して不要な依存が増えるため。

## Consequences

- workflow stateは実装主体非依存の名称を使う。
- 個別タスクのlive statusはIssue / PR側を正本とする。
- repository内のworkflow fileは状態遷移ルールを保持し、個別Issueの現在状態を複製しない。
- Codexは利用可能な実装手段の一つとして扱うが、必須工程にはしない。
