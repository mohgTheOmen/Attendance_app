# Group voting implementation plan

## Agreed behavior

- Existing admins create polls with a subject, at least two distinct options, and one or more eligible groups. Existing student (`user`) accounts vote.
- Polls start open; admins can close them. No reopening, editing options, or changing votes in this first version.
- A student in any selected group may choose exactly one option once per poll. Membership and active account status are checked by the server.
- Admins see all polls; students see polls for their current groups. Both see automatically refreshed aggregate counts and percentages, including before voting and after closing.
- Responses contain no voter lists, names, emails, or other students' choices. Participation is stored internally to enforce uniqueness; this is aggregate display, not a claim of irreversible anonymity.
- Database uniqueness on `(poll_id, user_id)` enforces one submission even across simultaneous requests. Options must belong to the chosen poll. Poll closure and voting must be serialized on PostgreSQL.

## Shared API contract

- `GET /api/polls`: array of visible polls.
- `POST /api/polls` (admin): `{subject, options: string[], group_ids: number[]}`; returns created poll, 201.
- `POST /api/polls/{id}/close` (admin): closes poll; returns poll.
- `POST /api/polls/{id}/votes` (student): `{option_id}`; returns updated poll, 201. Duplicate or closed: 409; unauthorized audience: 404; admin voting: 403; invalid option: 422.
- Poll response: `{id, subject, is_open, created_at, groups: [{id,name}], options: [{id,label,vote_count}], total_votes, has_voted}`. `has_voted` describes only the authenticated student; no selected option or voter identity is returned.

## Implementation sequence

1. Backend agent: models, migration, schemas, role/audience checks, aggregate queries, transactional vote and close operations.
2. Frontend agent: shared voting page and navigation, admin creation and closing, student single-choice submission, automatically refreshed totals, clear pending/error/empty states.
3. Test agent: API regression tests for lifecycle, roles, groups, validation, aggregate privacy, and repeat/concurrent voting.
4. Integrate and review on the single `feature/group-voting` branch; update README.

## Final verification

- Run complete backend suite against temporary SQLite and a separate disposable PostgreSQL database (never the development database).
- On PostgreSQL verify simultaneous votes by the same student produce exactly one accepted submission and one counted vote, and multiple eligible students count correctly.
- Apply migrations, run Alembic model drift check, and verify downgrade/re-upgrade on the disposable database.
- Run frontend lint, TypeScript check, and production build.
- Smoke-test the running local app API, migration head, frontend delivery, and voting flow; record actual outcomes below.

## Manual acceptance checks

1. Sign in at `http://127.0.0.1:5173` as an admin. In **Users**, enroll students A, B, and C. In **Groups**, put A and B in Class 1 and C in Class 2.
2. In **Voting**, create two different polls with at least two options each, selecting only Class 1. Both polls should appear for the admin.
3. Use separate browser profiles or normal/private windows for A and B. Open **Voting**. Both must see the same two polls and counters; C must see neither. Each eligible student can vote once in each poll independently.
4. A votes for one option. A sees the recorded message and no submission controls. B and the admin see the updated counter within roughly five seconds. B can still vote, and the total becomes two. No view shows voter names or individual selections.
5. Refresh A's page, open another tab, and sign out/back in: A must remain unable to vote in that same poll. The automated API tests additionally bypass the UI and submit twice and concurrently.
6. Close one poll as admin. It remains visible with final results, but no further votes are accepted. The other poll stays open.
7. Try creating a poll with no groups, fewer than two options, blank options, or duplicate options. Creation must fail.
8. Remove a student from Class 1 while their poll page is open. Their next refresh hides it; a stale-page vote is rejected by the server. Deleting the last eligible group must never make a poll public.

For direct API tests, use the student's own token with `POST /api/polls/{poll_id}/votes` and `{ "option_id": ... }`. Out-of-group polls return 404, duplicate or closed voting returns 409, and an option from another poll returns 422. Changing the URL or adding another student's ID never grants permission.

## Verification results

- Full original-plus-voting suite: PostgreSQL **67 passed, 1 skipped**; SQLite **65 passed, 3 skipped**. SQLite skips the two PostgreSQL concurrency cases; both passed on PostgreSQL. The remaining skip is the existing optional OCR integration.
- After adding the requested explicit cross-class, multiple-shared-poll, and logout/new-session scenarios, the complete voting suite passed again: PostgreSQL **22 passed**; SQLite **20 passed, 2 skipped** (PostgreSQL races). The full suite result above preceded these three additional tests.
- Alembic upgrade, model drift check, full downgrade to base, and re-upgrade passed on the disposable `attendance_voting_verify` database. Development database upgraded additively to `0005`.
- Frontend lint and TypeScript/production build passed. Existing lint warnings remain outside the voting page; the voting page has no lint warnings.
- Browser walkthrough passed using separate admin/student browser sessions against the disposable database: create/open, select/submit, shared automatic totals, immutable submitted vote, admin closure, and closure reflected on the student's page. Browser console had no errors. Poll cards also checked at 390px width.
- Repeated the walkthrough before committing in a visible Microsoft Edge window: admin created a group poll, student submitted once, reloading preserved the recorded vote with no second-vote controls, and admin saw the same count and closed the poll successfully. No browser console errors were reported.
- Development app remains at `http://127.0.0.1:5173/polls`; no browser-check demo data was added to its database.

### Permission boundary

An eligible student is an active `user` account belonging to any group selected for the poll. Every such student sees the same poll and aggregate counts. Admins can create multiple independent polls. This app currently has no professor-to-class ownership model: admins can manage all groups, and selecting groups on a poll defines its audience.

## Run the voting regression tests

From the repository root in PowerShell:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest -q tests/test_polls.py
```

That uses temporary SQLite by default. To also run the concurrency cases, point `TEST_DATABASE_URL` at a dedicated disposable PostgreSQL database before executing the same command. The test fixtures drop and recreate tables in that database. The verified isolated database for this session was `attendance_voting_verify`; do not point tests at the development `attendance` database.
