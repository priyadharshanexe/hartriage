# 0009. No LLM in the analysis

- **Status:** accepted
- **Date:** 2026-11-14

## Context

An LLM could write fluent summaries of a HAR file. But HAR contents are exactly the data this tool exists to protect, and support summaries must be reproducible and explainable to a customer.

## Options considered

1. **An LLM summariser as the core.** Fluent, but it sends customer data to a third party, gives different answers to the same file, and can state a cause the evidence doesn't support.
2. **Deterministic rules with written explanations.** Each finding cites request numbers and evidence, the same file always gives the same answer, and every rule is a small tested function with a KB article.

## Decision

Option 2. If an LLM is ever added, it is an opt-in extra, off by default, that only ever sees the redacted summary, never a HAR file.

## Consequences

- New failure patterns need a new rule (and a golden file and a KB article), which is slower than prompting but reviewable.
- "Why did it say that?" always has an answer: the rule id, its evidence and its code.
