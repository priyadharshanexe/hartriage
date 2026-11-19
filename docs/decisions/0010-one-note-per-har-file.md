# 0010. One private note per HAR file, not one per tag action

- **Status:** accepted
- **Date:** 2026-11-19

## Context

The spec says a tagged ticket gets "exactly one private note". Tested on a live Freshdesk trial, a ticket with two HAR files on the ticket and a third in a later note got three notes, one per file. Is that a deviation?

"Exactly one" in the spec is about duplicates: the same webhook delivered twice, a second trigger, a worker that crashes after posting ([0006](0006-exactly-once-private-notes.md)). It does not say several files must be merged.

## Options considered

1. **One note per HAR file.** Each file is its own analysis, with its own findings, redacted copy and link; the exactly-once key (case, attachment) and the note marker (analysis id) already work this way, and were proven live. Cost: N notes on a ticket with N HAR files.
2. **One merged note per tag action.** Tidier ticket. But a HAR that arrives later must either edit the old note (Freshdesk and Zendesk both make that awkward for private notes) or post a second note anyway, and the exactly-once key becomes "this set of files", which is much harder to keep exactly-once across retries and crashes. Agents also lose the one-to-one link between a note and its file.

## Decision

Option 1: one private note per HAR file, each naming its file. Duplicates of the same file are never posted.

## Consequences

- An agent can see which file each note is about, and download that file's redacted copy from the note.
- A ticket with many HAR files gets many notes. If agents ask for it, a short index note could be added later without changing the exactly-once keys.
