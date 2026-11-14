# trust/generic - review any git repository, in any language

    python trust/generic/analyze.py https://github.com/OWNER/REPO --pr 123      # public GitHub PR
    python trust/generic/analyze.py https://github.com/OWNER/REPO/pull/123
    python trust/generic/analyze.py /path/to/repo --base main --head my-branch   # local
    python trust/generic/analyze.py <repo> --pr 123 --run [--spec claims.json]    # + execute

Output: `.trust/generic/<title>/review.html` (open it) and `review.json`.

## Why it was language-limited, and why it no longer is

The first prototype *executed* C# (compile probes) and parsed Python (`ast`).
Those are the only two language-specific steps. Everything else - diff, history,
text search, test discovery - is just git and file text. The generic analyzer uses
only that, and puts anything language-specific behind an explicit, opt-in tier.

| Tier | Needs | Can say |
|---|---|---|
| static | git + file text | Refuted (counterexample in the text, assumptions listed), else Unknown |
| induced | git history | **Unknown only**: a habit seen in past commits is a lead, not a defect |
| executed (`--run`) | the repo's own test command, and/or your `--spec` commands | Tested (passed) or Refuted (failed, and the base passes) |

A clean static pass is never reported as "no bugs". Intent is always `Unknown`.

## What is approximate (stated, not hidden)
- Changed symbols come from regexes for common syntax (Python, JS/TS, Go, Rust, Java, C#, Kotlin, C/C++, Ruby, PHP), not a parser.
  Config/data-only changes yield no symbols and G1 is then Unknown.
- "Callers" are whole-word text matches (`git grep -w`), with import lines removed. This over-approximates (shared names)
  and under-approximates (dynamic dispatch, reflection). Names matched by >60 files are skipped as too common.
- The PR base is the true merge-base. If it cannot be found the tool refuses instead of guessing: a wrong base blames the PR
  for other people's changes.

## Safety
Without `--run`, nothing from the target repo is executed. `--run` runs its test command (and any `--spec` commands) on
this machine: use it for code you would run anyway, or in a container. Only `https://github.com/...` URLs and local git
directories are accepted. Clones go to `.trust/_clones/` (gitignored).

## `--spec` format
    [{"id": "S1", "claim": "refunds are still summed", "command": "node -e \"...\"", "expect": 0}]
Exit code decides: match -> Tested (once, on this checkout), mismatch -> Refuted with the output as the witness.
