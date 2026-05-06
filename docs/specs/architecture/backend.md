<!-- Generated: 2026-05-06 | Files scanned: 9 | Token estimate: ~750 -->

# Core / "Backend" Modules

No HTTP server. "Backend" = orchestration + external-process layer.

## Pipeline orchestrator — `gh_readme_pipeline.py` (530 lines)
```
parse_args(argv)              → Namespace (env fallback)
_resolve_user()               → str (gh api user)
_clone_or_fetch(repo, dir)    → Path (git clone --depth=1 or fetch)
process_repo(repo, ...)       → ReviewResult|None  (review + commit)
_summary_rows(state_store)    → list[SummaryRow]
_print_summary(state_store)   → None
main(argv)                    → int  (exit code)
```

## Fetch — `src/fetch.py`
```
fetch_repos(user, limit) → list[Repo]
  _fetch_page(user, cursor) → (nodes, page_info, rate_limit)
  _parse_node(node)         → Repo
  _handle_rate_limit(rl)    → raises if depleted
  _disk_preflight(repos)    → raises on insufficient space
```
Source: `gh api graphql` paginated. Sort: pushedAt desc.

## State — `src/state.py`
```
xdg_cache_dir() → Path  (~/.cache/writeme)
xdg_state_dir() → Path  (~/.local/state/writeme)
class StateStore:
  load() / save() / mark_processed(repo, result) / is_processed(repo)
prompt_resume(count) → "resume" | "fresh" | "quit"
```
Storage: JSON file in XDG state dir.

## Review — `src/review.py` (609 lines)
```
generate_draft(repo_dir, timeout, ui, repo_name, env) → GenerationResult
  _restore_baseline                    # git checkout README.md (HEAD)
  _invoke_claude(repo_dir, timeout, env)  # subprocess, scrubbed env
  _blast_radius_ok(repo_dir)           # only README.md may change
  _read_file                           # capture generated content

review_loop(repo_dir, ui, timeout, pregenerated, ...) → ReviewResult
  _prompt_risky_files / _prompt_timeout / _prompt_nonzero
  _prompt_secret_override / _prompt_accept
  _stage_skill / _unstage_skill        # copies /create-readme skill in
  _invoke_claude(repo_dir, timeout)    # subprocess, scrubbed env
  _blast_radius_ok(repo_dir)           # only README.md may change
  _build_diff(old, new)                # unified diff
  _restore_baseline                    # git checkout README.md on abort
  _show_pager                          # less -R pager for diff
```
ReviewResult.status: `accepted | skipped | failed | quit`.
GenerationResult.status: `ready | timeout | nonzero | blast_radius | failed`.

## Commit — `src/commit.py` (325 lines)
```
commit_and_push(repo_dir, mode, msg, dry_run) → CommitResult
  _run_pr_mode          # branch, push, gh pr create
  _run_direct_mode      # commit on default branch + push
  _run_commit_only_mode # commit, no push
  warn_gpg_signing()    # detects GPG config, warns about prompts
```
External: `git`, `gh pr create`.

## Safety — `src/safety.py`
```
validate_repo_name(name)   # regex, no path traversal
validate_ssh_url(url)      # restrict to github.com SSH form
ensure_clean(repo_dir)     # no untracked / no uncommitted
acquire_lock(path)         # contextmanager, fcntl flock
```

## Secrets — `src/secrets.py`
```
scan_repo_for_risky_files(dir) → list[Path]   # .env, *.pem, id_rsa…
scan_text_for_secrets(s)        → list[str]   # AWS, GH token, OpenAI, PEM
```

## Unpushed — `src/unpushed.py`
```
scan_repos(repos_dir) → list[UnpushedFinding]  # dirty or ahead-of-upstream
```
Called at startup to warn before destructive cache reuse.
