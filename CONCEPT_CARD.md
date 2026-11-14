# Earned Trust in AI Code — concept card

**Recommendation.** Treat an AI review as an evidence receipt for a named
engineer. The AI links the requirement to the changed code, tests important
assumptions, lists unchecked areas, and recommends a route. Only the engineer
accepts, requests changes, or escalates the patch.

## Review contract

1. **Evidence before confidence.** A model's confidence is not a verdict. Each
   material claim needs a source and a repeatable check. A failed tool run is
   `UNCHECKABLE`, not a passing result.
2. **Risk controls attention.** Low-risk, well-covered changes can receive a
   targeted human check. A known requirement gap, security-sensitive change,
   or missing evidence requires focused investigation or a full human read.
3. **The AI may refuse.** It cannot waive a requirement, interpret an
   unstated product trade-off as authorized, or approve its own review.
4. **A human owns the outcome.** The receipt records the engineer, decision,
   checks performed, unchecked areas, and residual risk. No name means no
   approval.
5. **Trust can be withdrawn.** Spot-check AI reviews and record false findings,
   escapes, and reversions by code area. A clean run on one branch is not a
   reputation score.

## Reference example: MessagePack-CSharp #2297

Requirement: decorate **all** generated code with
`ExcludeFromCodeCoverage`. The AI-made patch adds
`#if !NETSTANDARD2_0 && !NETFRAMEWORK` around the attribute. The attribute
compiles unguarded on both excluded frameworks, while the library ships them.
The AI therefore recommends **request changes**. It refuses to decide whether
Tieto or the upstream maintainer should relax the requirement. The human
decision remains **pending**.

The [review receipt](demo/review-2297.html) shows the claim, three checkable
links or commands, unchecked areas, refusal, and decision log. The
[machine record](demo/review-2297.json) pins the branch commit.

## Trade-offs and limits

| Choice | Benefit | Limit |
|---|---|---|
| Check assumptions, not every line | Finds a test-invisible feature gap in a 237-file patch | Cannot prove absence of other defects |
| Run small compile probes | Fast, reproducible compatibility evidence | Does not build every emitted consumer configuration |
| Retrieve cited snippets | Keeps large diffs manageable | Saved tokens do not establish review quality |
| Record agent context when available | Preserves stated decisions and edits | Tieto's original author sessions were not supplied; our #2283 re-enactment is guided and separate |

## Reference implementation and technology considerations

- **Frontend:** the static receipt presents evidence, limits, and the pending
  human decision in one screen. It never offers an AI approval control.
- **Backend:** Python reads pinned git objects and issue text, checks
  assumptions, runs .NET probes, and emits JSON plus a reproducible test.
- **Security:** use public or cleared data in the stage package. The current
  prototype does not enforce a network-free sandbox for arbitrary repositories;
  production execution would require isolation, resource limits, and secret
  handling before accepting untrusted code.

## Lessons and decisions

| Failure mode observed | Decision |
|---|---|
| A wrong merge-base created a plausible false dependency finding | Pin the branch parent and cross-check the brief's file count |
| Existing snapshots encoded the #2297 guard | Treat green tests as evidence only for the targets they run |
| The original author transcript was unavailable | Label inferences from code as reconstructed, never as the author's reasoning |
| A probe or test runner can fail for environmental reasons | Report `UNCHECKABLE`; do not promote it to support |

The full [design document](DESIGN.md) contains additional proposed modules.
Its future architecture is not part of the working reference implementation.
