# Generated repro - origin/ju26-issue-2297

Pinned commit: `a0aa5ab2de7f5a669d97e37184a89034c1de82b6`. Sources are copied from that git object into
`source_snapshot/a0aa5ab2de7f5a669d97e37184a89034c1de82b6/`, so switching the working checkout cannot change
the result.

One command:

    dotnet test

## What you should see

Two tests FAIL. That is the point: they assert what issue #2297 actually asked
for, and the current implementation does not deliver it.

| Test | Asserts |
|---|---|
| `AttributeIsNotRestrictedByTargetFramework` | the attribute is applied unconditionally, as the issue requested |
| `ReadmeDoesNotClaimTheAttributeIsUnavailable` | the README does not state a false availability constraint |

`TemplatesExist` passes, which confirms the test is reading the real repository
and not vacuously succeeding.

## Independent check

The finding rests on the excluded frameworks being perfectly capable of the
attribute. Verify that yourself, without trusting this repro:

    dotnet build "D:\work\big-hackathon\.trust\probes\origin_ju26-issue-2297\probe_net472\p.csproj" -v q --nologo

## What this is NOT

- Not a crash, not data corruption, not a security issue. It is a feature gap
  plus a false sentence in the docs.
- Not a complaint about the whole change. The same agent updated all six
  templates, regenerated 222 snapshots consistently, and kept `.tt`/`.cs` in
  sync. Only the target-framework conditionality is wrong.
- This test detects the guard in template text. The compile probes separately
  establish API availability. It does not compile the full generated output.
