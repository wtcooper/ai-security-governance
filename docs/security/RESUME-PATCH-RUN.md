# Resume notes — Claude Security fix run (2026-08-10)

State of the fix run against report `CLAUDE-SECURITY-20260810-151644`. Two units remain.
Both stalled on an API session limit, not on anything about the code.

## Fixed constants for this run

- **PATCH BASE**: `8a03909ba7c1fdbcffc3db2654693c7d42a8492b` (branch `develop`)
- **REPO ROOT**: `/Users/wadecooper/Code/GitWCoop/ai-security-governance`
- **PATCH DIR**: `CLAUDE-SECURITY-20260810-151644/.claude-security-run/patch-20260810-170834`
- **Tests**: `cd backend && PYTHONPATH=$PWD ../backend/.venv/bin/python -m pytest -q`
  — 246 at the patch base, **251** with the F5 fix applied.

Note the patch base is now behind `develop`: the F1 and F5 fixes are committed, so a future
patch run should re-scan or re-base rather than reuse `F4.diff` blindly.

## Settled

| Unit | Status |
|---|---|
| **F1** — `source_url` XSS | ✅ **Applied and committed.** Verifier PASS (3/3 CONFIDENT), adversarial reviewer found nothing, frontend `tsc --noEmit` clean. `untested: true` — the frontend has no test suite, so its behaviour claim rests on review plus probes, not a project test. |
| **F5** — policy version race | ✅ **Applied and committed**, including the correction the verifier identified (the `try` in `seed_policies` had to enclose the whole attempt body, not just `session.commit()`, because the read autoflushes the previous iteration's pending insert). Proven both ways with a race probe. 5 regression tests. |
| **F2** — upload CSRF | ⛔ **Was unpatchable**: its file `frontend/lib/api.ts` was outside version control, so no diff could be built against the committed tree. **That blocker is now gone** — the `.gitignore` pattern is anchored and the file is tracked — so this is patchable from here. |
| **F6** — `source_url` open redirect | ✅ **Closed by F1's fix** — same sink, same `httpUrl()` guard. No separate patch was written; one would have conflicted textually with F1's on the same lines. |

## Outstanding

### F4 — prompt injection in the extraction endpoint

**A fix is written and independently verified, but is NOT applied**, because its adversarial
review never ran to completion (the agent was killed by the session limit). Protocol here is
that a patch needs both the verifier and a fresh reviewer of the bare diff; F4 has only the
first, so applying it would overstate its assurance.

- Diff: `<PATCH DIR>/F4.diff`
- Verifier result: PASS, all three claims CONFIDENT, `untested: false`, 251 tests pass
  (246 base + 5 new), and the 5 new tests fail against the unmodified file.
- What it does: wraps the fetched page in a per-request unguessable fence
  (`untrusted-document-<token_hex(8)>`), states before and after the fence that the content is
  untrusted data whose directives must not be followed, adds `_quote_in_document` so a reviewer
  is told when a model's supporting quote does not actually appear on the page, and adds an
  additive optional `quote_in_document` response field.
- **To finish:** run one `claude-security:scan-researcher` over `F4.diff` alone, asking "what can
  an attacker do with this change that they could not do before it?". Angles the dispatch called
  out: pathological CPU cost in `_quote_in_document` normalisation against a large fetched page
  and many candidates; whether the fence token can leak into the response or logs; whether
  `_validate`'s changed signature drops a check. If it comes back clean, apply the diff. If it
  objects, F4 gets one revision round (it has had none).
- Re-check it still applies first — the tree has moved since it was generated.

### F3 — no authentication on policy-version writes

**Not started.** The generator was killed by the session limit before producing anything, so
there is no attempt to review.

This one likely should not be resolved by a patch at all, and the dispatch said so explicitly.
The application has no authentication anywhere; compose binds to `127.0.0.1`; and the browser
client has no mechanism to hold or send a credential. A mandatory token on this endpoint would
reject requests the current code accepts and break the shipped frontend — which fails the
verifier's "behaviour unchanged" claim by construction. The honest options are:

1. Accept the loopback-only threat model explicitly, and document it as the control.
2. Introduce a local API token **plus** a frontend path that can send it (that means a
   same-origin Next.js route handler or server action, which would also close F2).
3. Build a real session layer.

That is a product decision. Worth pairing with F2, since option 2 closes both.

## Ground rules that shaped this run

- One revision round per unit; a second objection declines it. That is why F5 was declined by the
  run even though its fix was nearly right — the remaining defect was then fixed by hand, with the
  verifier's own diagnosis, and proven with a probe before being applied.
- The panel earned its keep: it caught an unhandled 500 on an unauthenticated endpoint in one
  proposed fix, and a fail-closed startup check in another that would have permanently prevented
  the app from booting on any database with pre-existing duplicate rows.
