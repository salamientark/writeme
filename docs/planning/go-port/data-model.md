# data-model.md — Go Port Data Model

Typed data model for the Go reimplementation of `writeme`. Source of truth = current Python in `src/`. Each entity below is paired with the Python file:line it derives from.

Conventions:
- Field names use Go convention (`PascalCase`); JSON tags preserve Python wire format.
- `*T` denotes optional / nullable. Empty slices are NOT `nil`-equivalent — they mean "known empty" (e.g. `Contributors == []` means "fetched, zero humans"; `nil` means "not yet fetched").
- All struct sketches are illustrative — not yet authoritative Go source.

---

## 1. Repo

GraphQL-derived repository record. Immutable after fetch; enrichment produces a copy with `Contributors` set.

Source: `src/selection.py:14-31` (dataclass), `src/fetch.py:108-137` (parser), `src/contributors.py:105-140` (enrichment).

```go
type Repo struct {
    Name             string    `json:"name"`
    SSHURL           string    `json:"ssh_url"`
    PushedAt         string    `json:"pushed_at"`         // ISO-8601 UTC
    HadReadmeBefore  bool      `json:"had_readme_before"`
    DiskUsage        int       `json:"disk_usage"`        // KB
    IsFork           bool      `json:"is_fork"`
    Contributors     *[]string `json:"contributors,omitempty"` // nil = unenriched
}
```

Invariants:
- `Name` matches `safety.validate_repo_name` regex (alnum + `._-`, no traversal). See `src/fetch.py:117`.
- `SSHURL` matches `safety.validate_ssh_url` (e.g. `git@github.com:owner/repo.git`). See `src/fetch.py:118`.
- `PushedAt` parseable as RFC3339; used as cache key component (`src/contributors.py:44-45`).
- `Contributors == nil` ⇒ enrichment not yet run; predicate `is_solo` returns false (`src/filters.py:23-25`).
- `Contributors == &[]` ⇒ empty repo / all-bots; counted as solo.
- `HadReadmeBefore` is OR over five GraphQL README path variants (`src/fetch.py:124-128`).

Serialization:
- Wire (GraphQL): keys per `_GRAPHQL_QUERY` in `src/fetch.py:37-70`.
- On disk: not directly persisted. (Contributors cache is keyed by `name@pushed_at` — see Contributor cache below.)

Concurrency: Read-only across all goroutines once constructed. Safe to share by value (no pointer fields except optional slice).

---

## 2. Contributor cache (no struct — disk format)

Source: `src/contributors.py:44-65`.

Disk format (JSON map):
```json
{
  "<repo-name>@<pushed-at>": ["alice", "bob"],
  ...
}
```

```go
type ContributorCache map[string][]string  // key = repo.Name + "@" + repo.PushedAt
```

Invariants:
- Key format: `fmt.Sprintf("%s@%s", repo.Name, repo.PushedAt)` (`src/contributors.py:44-45`).
- Values are post-bot-strip (`src/contributors.py:32-37`); bot regex: `(.*\[bot\]$|^dependabot(-preview)?$|^github-actions$)`.
- Stale entries (mismatched `pushed_at`) are simply unreachable; never explicitly evicted.
- Corrupt JSON ⇒ treat as empty (`src/contributors.py:55-60`).

Serialization: JSON, indent=2, sorted keys (`src/contributors.py:65`).

On-disk path: caller-supplied; in practice under `xdg_cache_dir() / "contributors.json"` (`src/state.py:34-43`).

Concurrency: Read once at start of `enrich_repos`, written once at end (`src/contributors.py:118,138-139`). The `ThreadPoolExecutor.map` collects results serially in the main goroutine — no concurrent write. Go port: same pattern (errgroup + final write) or use a `sync.Mutex` if streaming writes.

---

## 3. SelectionState

Pure immutable TUI state machine. Every transition returns a new value.

Source: `src/selection.py:41-281`.

```go
type SelectionState struct {
    Repos                 []Repo
    Cursor                int               // index into Repos
    Selected              map[int]struct{}  // set semantics; key = index into Repos
    ViewportStart         int               // index in visible-position space
    ViewportHeight        int
    Filter                string            // case-insensitive substring
    SoloOnly              bool
    ExcludeForks          bool
    ExcludeExistingReadme bool
}
```

Derived (computed, not stored):
```go
func (s SelectionState) VisibleIndices() []int          // src/selection.py:196-215
func (s SelectionState) HiddenSelectedCount() int       // src/selection.py:217-223
func (s SelectionState) VisibleSlice() []VisibleRow     // src/selection.py:229-247

type VisibleRow struct {                                 // src/selection.py:34-38
    Repo       Repo
    IsSelected bool
    IsCursor   bool
}
```

Invariants:
- `0 <= Cursor < len(Repos)` whenever `len(Repos) > 0`.
- `Cursor ∈ VisibleIndices()` after every transition (clamped via `_reapply_filters`, `apply_filter`, `move`). See `src/selection.py:131-194`.
- `Selected ⊆ {0..len(Repos)-1}`. Out-of-filter selections are preserved across filter toggles (`src/selection.py:117-125`).
- `0 <= ViewportStart <= max(0, len(VisibleIndices()) - ViewportHeight)`.
- `ViewportHeight >= 1` (treat `0` as "no rows visible" — degenerate).
- `Filter` is stored verbatim; lowercased only at compare time (`src/selection.py:203`).

Serialization: not persisted. Held in-memory for the TUI session only.

State transitions (each returns a new `SelectionState`):

| Transition | Trigger key | Effect | Source |
|---|---|---|---|
| `Toggle()` | space | Flip `Cursor` membership in `Selected` | `selection.py:70-82` |
| `Move(delta)` | ↑/↓ | Step cursor in visible-space; auto-scroll viewport | `selection.py:84-115` |
| `SelectAll()` | `a` | Add all `VisibleIndices` to `Selected` | `selection.py:117-120` |
| `SelectNone()` | `n` | Remove all visible from `Selected` | `selection.py:122-125` |
| `ApplyFilter(q)` | `/`+text | Set `Filter`, clamp cursor, reset viewport | `selection.py:131-145` |
| `ClearFilter()` | esc | `Filter=""` | `selection.py:147-148` |
| `JumpTop()` / `JumpBottom()` | g/G | Cursor to ends, viewport follows | `selection.py:150-162` |
| `PageDown()` / `PageUp()` | PgDn/PgUp | `Move(±ViewportHeight)` | `selection.py:164-168` |
| `ToggleSoloOnly()` | `s` | Flip predicate, re-clamp via `_reapply_filters` | `selection.py:170-171` |
| `ToggleExcludeForks()` | `F` | Same | `selection.py:173-174` |
| `ToggleExcludeExistingReadme()` | `r` | Same | `selection.py:176-179` |
| `HandleKey(c)` | dispatcher | Routes to above; unknown ⇒ identity | `selection.py:253-281` |

Concurrency: single-threaded (TUI event loop). No locking. Crosses no goroutine boundary in Python; same in Go port.

---

## 4. FilterToggles (predicate set)

Source: `src/filters.py:13-57`.

Conceptually a 3-bit subset of `SelectionState`. Predicates:

```go
func IsSolo(r Repo) bool      // r.Contributors != nil && len(*r.Contributors) <= 1
func IsFork(r Repo) bool      // r.IsFork
func HasReadme(r Repo) bool   // r.HadReadmeBefore

type FilterToggles struct {
    SoloOnly              bool
    ExcludeForks          bool
    ExcludeExistingReadme bool
}

func ApplyFilters(repos []Repo, t FilterToggles) []Repo  // AND composition
```

Invariants:
- AND composition (`src/filters.py:48-55`).
- `IsSolo` returns false when `Contributors == nil` — conservative pre-enrichment behavior (`src/filters.py:23-24`).

Serialization: not persisted.

Concurrency: pure functions; no state.

---

## 5. StateStore (persisted run log)

Append-only JSONL audit log. Used for resume + summary.

Source: `src/state.py:62-185`.

```go
type StateStore struct {
    user      string        // validated against _GH_USER_RE
    stateDir  string
    stateFile string        // <stateDir>/state-<user>.jsonl
    mu        sync.Mutex    // serialises Record() across goroutines
}

type StateEntry struct {
    Repo   string `json:"repo"`
    Status string `json:"status"`            // see status set below
    Ts     string `json:"ts"`                // ISO-8601 UTC, seconds precision
    Mode   string `json:"mode,omitempty"`
    Error  string `json:"error,omitempty"`
    PRURL  string `json:"pr_url,omitempty"`
}
```

Status set (string enum on the wire):
- Terminal-success: `"pushed"`, `"pr_opened"`, `"commit_only"` — counted by `LoadProcessed()` (`src/state.py:31, 147-159`).
- Terminal-failure: `"failed"` — surfaced in summary (`src/state.py:178-179`).
- Other: arbitrary intermediate strings allowed; counted but not in `processed` set.

Invariants:
- `user` matches `^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$` (`src/state.py:22, 76-77`). Prevents path traversal in filename.
- File is append-only. Each `Record()` writes one line + flushes (`src/state.py:118-122`).
- Malformed lines are skipped by reader, not erased (`src/state.py:142-144`).
- `LoadProcessed()` returns the set of repos whose **last** matching record has a terminal-success status. (Python implementation actually treats it as "any record with success status" via set comprehension at `state.py:155-159` — Go port should match.)

Serialization:
- Format: JSONL (one JSON object per line, UTF-8).
- On-disk path: `xdg_state_dir() / "state-<user>.jsonl"`.
  - `XDG_STATE_HOME` honored, fallback `~/.local/state/gh-readme-pipeline/` (`src/state.py:46-55`).
  - `APP_NAME = "gh-readme-pipeline"` (kept stable for backward compat with existing users).

Concurrency:
- `Record()` MUST be safe under parallel `WorkerPool` calls. Python uses `threading.Lock`; Go port uses `sync.Mutex` (`src/state.py:83, 119`).
- `LoadProcessed()` / `Summary()` are read-only and only called outside the parallel section (start + end), so no read lock required — but a mutex around the file handle is harmless.

Resume choice (separate from store):
```go
type ResumeChoice string  // "resume" | "all" | "fresh" | "quit"
```
Source: `src/state.py:192-222`.

---

## 6. WorkerJob / WorkerResult

Parallel pool plumbing for `generate_draft`.

Source: `src/worker.py:24-87`, `src/review.py:93-148`.

```go
const MaxParallelCap = 8  // worker.py:24

type WorkerPool struct {
    maxWorkers int
    fn         func(Repo) GenerationResult
    jobs       []*workerJob
    draining   atomic.Bool
    submitted  atomic.Bool
    // Go: use errgroup or a chan + sync.WaitGroup; expose Completed() <-chan WorkerResult
}

type workerJob struct {
    repo   Repo
    result GenerationResult
    err    error
    done   chan struct{}
}

// Yielded from Completed() in finish-order (FIFO):
type WorkerResult struct {
    Repo   Repo
    Result *GenerationResult  // nil if Failed
    Failed *FailedTuple       // nil if Result is set
}

type FailedTuple struct {       // worker.py:72  ("failed", name, msg)
    RepoName string
    Message  string             // "<ExceptionType>: <message>"
}

type GenerationResult struct {                   // review.py:93-112
    Status        string    // "ready" | "timeout" | "nonzero" | "blast_radius" | "failed"
    OldContent    string
    NewContent    *string   // non-nil only when Status == "ready"
    RiskyFiles    []string
    SecretMatches []string
    Error         *string   // set on "failed" / "blast_radius"
}
```

Invariants:
- `maxWorkers ∈ [1, MaxParallelCap]` clamped at construction (`src/worker.py:33`).
- `submit_all` is idempotent — second call is a no-op (`src/worker.py:42-45`).
- `Completed()` emits each job exactly once. "Drained" jobs (cancelled before start) are filtered out, not emitted (`src/worker.py:74-75`).
- Unhandled exception from `fn` ⇒ FailedTuple, never propagated (`src/worker.py:69-73`).
- `GenerationResult.NewContent != nil ⇔ Status == "ready"`.
- Status is a closed enum (no other values produced).

Serialization: not persisted. In-memory only between `submit_all` and review consumption.

Concurrency:
- Workers run `fn` in parallel goroutines. `fn` MUST NOT mutate `os.Environ` — instead pass per-job env via the function closure (Python's `_invoke_claude(..., env=...)` pattern, `src/review.py:231-273`).
- `draining` is checked atomically by each worker on start (`src/worker.py:55`).
- Completion channel is single-consumer (the review loop). Go: use a buffered `chan WorkerResult` of size `len(jobs)`.

---

## 7. SandboxPaths

Per-job XDG directory bundle so concurrent claude subprocesses don't collide on session DBs.

Source: `src/sandbox.py:14-37`.

```go
type SandboxPaths struct {
    Config string  // <base>/claude-jobs/<repo>/config
    Data   string  // <base>/claude-jobs/<repo>/data
    Cache  string  // <base>/claude-jobs/<repo>/cache
    State  string  // <base>/claude-jobs/<repo>/state
}

func SandboxFor(base, repoName string) (SandboxPaths, error)  // creates dirs
func (s SandboxPaths) Env() map[string]string                  // XDG_*_HOME → path
```

Invariants:
- `repoName` validated by `safety.validate_repo_name` before path join — prevents traversal (`src/sandbox.py:22`).
- All four subdirs created with `MkdirAll` before return (`src/sandbox.py:25-26`).
- `Env()` produces exactly: `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_CACHE_HOME`, `XDG_STATE_HOME` (`src/sandbox.py:30-37`).

Serialization: paths exist on disk; struct itself is not persisted.

Concurrency: each `WorkerPool` job constructs its own `SandboxPaths`. Distinct `repoName` ⇒ disjoint paths ⇒ no contention. Distinct goroutines never share an instance.

---

## 8. ReviewSession (review FSM state)

Source: `src/review.py:444-609` (`review_loop`), `src/review.py:87-91` (`ReviewResult`), `src/ui/protocol.py:17-25` (`ReviewContext`).

The review loop is procedural in Python — no explicit struct. For Go we model it as a session value with explicit state.

```go
type ReviewSession struct {
    RepoDir          string
    RepoName         string
    RepoIndex        int             // 1-based
    RepoTotal        int
    HadReadmeBefore  bool
    ClaudeTimeout    time.Duration

    // Per-iteration mutable state
    Iteration       int
    OldContent      string           // captured once before loop
    PrevDraft       *string          // last draft before a 'redo'
    Pregenerated    *GenerationResult // consumed on first iteration only
    CurrentGen      GenerationResult
}

type ReviewContext struct {                       // ui/protocol.py:17-25
    RepoName     string `json:"repo_name"`
    Index        int    `json:"index"`
    Total        int    `json:"total"`
    HeadReadme   *string
    PrevDraft    *string
    CurrentDraft string
}

type ReviewResult struct {                        // review.py:87-91
    Status string  // "accepted" | "skipped" | "failed" | "quit"
    Reason *string
}
```

Invariants:
- `Iteration >= 1` inside the loop body.
- `Pregenerated` consumed exactly once: set on entry, nil-ed after first iteration (`src/review.py:486, 493-500`).
- `OldContent` captured once before loop and reused (no re-read mid-loop) (`src/review.py:480-484`).
- `HadReadmeBefore == true` ⇒ accept requires literal `"yes"` typed (`src/review.py:391-432`); guarded UI path uses `ui.show_review` instead (`src/review.py:577-592`).
- Terminal statuses (`accepted`, `skipped`, `failed`, `quit`) exit the FSM. `redo` re-enters with `PrevDraft = lastDraft` (`src/review.py:608-609`).
- Before any non-`accepted` exit, `safety.ensure_clean(repo_dir)` is called (`src/review.py:545, 556, 561, 565, 572, 600, 604`).

Serialization: not persisted directly. Outcomes propagate to `StateStore.Record()` post-FSM.

State transitions (one iteration):

```
                   ┌─ timeout ─→ prompt → {retry|skip|quit}
                   │
generate_draft ────┼─ nonzero ─→ prompt → {redo|discard}
                   │
                   ├─ blast_radius ─→ failed
                   │
                   ├─ failed ──────→ failed
                   │
                   └─ ready ─→ secret-scan ─→ accept-prompt
                                                 │
                                                 ├─ accept  → accepted
                                                 ├─ redo    → loop (prev_draft=current)
                                                 ├─ discard → skipped
                                                 └─ quit    → quit
```

Source: `src/review.py:489-609`.

Concurrency: single-threaded. The review FSM runs in the main goroutine, sequentially consuming `WorkerPool.Completed()`. No locking; no shared mutable state with workers other than the immutable `Repo` and the `GenerationResult` value passed across the channel.

---

## Cross-cutting summary

| Entity | Persisted? | Path | Format | Cross-goroutine? | Lock |
|---|---|---|---|---|---|
| Repo | no | — | — | shared read-only | none |
| ContributorCache | yes | `xdg_cache_dir/contributors.json` | JSON | no (single writer) | none |
| SelectionState | no | — | — | no (TUI only) | none |
| FilterToggles | no | — | — | pure | none |
| StateStore | yes | `xdg_state_dir/state-<user>.jsonl` | JSONL | yes (parallel `Record`) | `sync.Mutex` |
| WorkerPool | no | — | — | yes (the point) | channels + atomics |
| GenerationResult | no | (passed through channel) | — | yes | immutable |
| SandboxPaths | dirs only | `<base>/claude-jobs/<repo>/{config,data,cache,state}` | dirs | no (per-job) | none |
| ReviewSession | no | — | — | no (main goroutine) | none |
