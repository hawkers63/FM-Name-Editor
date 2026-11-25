# Roadmap

Short public plan for FM Name Editor. The detailed numbered session plan
stays in the private `roadmap.md` on this PC and is not published.
Session progress belongs in `docs/SESSION_HANDOFF.md`.

Update this file when a public milestone is completed, a new item is
agreed for the public plan, an item is dropped or deferred, or priority
changes.

© Mark Hawksworth. All rights reserved.

## Now

- **Release 3.11** is current (25 November 2026), with bug
  fixes: a file whose changes are all unticked stays out of Deploy,
  Restore selected names compares the names themselves, Undo and Redo
  take a restore's file state with them, the "Restored" message stays in
  the Backups window, and the test suite runs clean on Linux.

## Next

- Further work is to be planned.

## Later


## Done

Public releases already shipped (see `CHANGELOG.md` and the GitHub tags):

- 3.10 — Restore selected names in the background, refusing names changed since the list was shown
- 3.9 — a quicker Save, pack import and backups in the background, and why a backup's bytes differ
- 3.8 — snapshot rollback asks first, with Cancel by default
- 3.7 — suggested short names and codes, name health, and in-memory snapshots
- 3.6 — search scope and aliases, name-length counters, and faster keyboard moves
- 3.5 — start folders and favourites, the ID column, and Add name
- 3.4 — illustrative previews and per-name backup restore
- 3.3 — shared-word selection, batch recipe from the selection, pinned spelling pairs
- 3.2 — smart selection, batch rename, Harmonise terminology, command palette
- 3.1 — visual pass and the rest of saved rules
- 3.0 — three-way update migration, conflict inspector, saved rules
- 2.6.1 / 2.6 / 2.5 — public-ready executable and follow-ups, then corrections from the 2.4 review
- 2.4 — interface, persisted view state, collections, background work
- 2.3 — spelling profiles, Changes view, operation undo
- 2.2 — correctness and write safety
