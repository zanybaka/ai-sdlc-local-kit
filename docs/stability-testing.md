# Stability testing — idle and empty-state gaps

## Core principle

Every runnable module or component must be testable with empty, null, or no-data
input **before** delivery. A test suite that only exercises the "happy path after
data is loaded" leaves the pre-load state untested and can ship broken behaviour
that automated checks never see.

## Three concrete shapes

### 1. Idle state

The app or process is open but no data has been loaded yet. The UI renders, the
process starts, no user action has occurred. Tests must cover this state directly —
do not assume a setup fixture always supplies data.

*Indicator that this is missing:* every test calls `load()`, `setInputFiles()`, or
similar before asserting anything; the app state at t=0 is never observed.

### 2. Smoke test

A minimal test that verifies the entry point starts and produces no errors with no
user action. For a CLI: run with no arguments and check the exit code and stderr.
For a web app: open the page, wait briefly, assert zero console errors and no
visible crash UI.

A smoke test is the first test executed. It fails fast when the idle state is broken
and protects the rest of the suite from false negatives caused by a bad startup.

### 3. Stack-specific anti-patterns

The sections below list known patterns that cause instability when the component or
module receives empty input. Each entry shows a broken example and its fix.

---

## React anti-patterns

### Unstable reference from inline `??[]` / `??{}` in hook return values

**Problem:** returning `??[]` or `??{}` inline creates a new object every render,
causing consumers that depend on referential equality to re-render infinitely.

```tsx
// bad — new array on every render when data is null
function useItems() {
  const { data } = useFetch('/items');
  return data ?? [];
}
```

```tsx
// fix — stable empty reference via useMemo
function useItems() {
  const { data } = useFetch('/items');
  return useMemo(() => data ?? [], [data]);
}
```

### `new Set()` / `new Map()` literals in `useEffect` dependency array

**Problem:** `new Set()` and `new Map()` are never referentially equal across
renders. Placing them directly in a `useEffect` dep array causes the effect to run
on every render, often producing an infinite update loop.

```tsx
// bad — new Set() !== new Set(), effect runs every render
useEffect(() => {
  setSelected(new Set());
}, [new Set()]);
```

```tsx
// fix — move the stable value outside the component or use useMemo
const EMPTY_SET = new Set<string>();

useEffect(() => {
  setSelected(EMPTY_SET);
}, []);
```

### Inline object or array literals in props

**Problem:** `<Component config={{}} />` or `<Component items={[]} />` passes a new
reference on every parent render, breaking memoised children and triggering
unnecessary re-renders.

```tsx
// bad — new object reference every render
<DataTable filters={{}} onSort={() => {}} />
```

```tsx
// fix — define constants outside the component or memoise
const NO_FILTERS = {};
const handleSort = useCallback(() => {}, []);

<DataTable filters={NO_FILTERS} onSort={handleSort} />
```

---

## Python anti-patterns

### Mutable default argument

**Problem:** Python evaluates default argument values once at function definition
time. A mutable default like `[]` or `{}` is shared across all calls, so mutations
in one call bleed into later calls.

```python
# bad — all callers share the same list
def append_item(item, collection=[]):
    collection.append(item)
    return collection
```

```python
# fix — use None as sentinel, create a fresh object inside the function
def append_item(item, collection=None):
    if collection is None:
        collection = []
    collection.append(item)
    return collection
```

### Unclosed file handle in error path

**Problem:** opening a file with `open()` and assigning it to a variable leaves the
handle open if an exception is raised before `close()` is called. On empty or
malformed input files this is a common source of resource leaks.

```python
# bad — handle stays open if process() raises
f = open(path)
data = process(f.read())
f.close()
```

```python
# fix — use a context manager; handle is always closed
with open(path) as f:
    data = process(f.read())
```

### Script crash on empty input without a helpful error

**Problem:** a script that reads from stdin or a file argument and immediately
iterates or indexes the result will raise an obscure traceback when the input is
empty, giving the caller no actionable information.

```python
# bad — IndexError or StopIteration with no context
lines = sys.stdin.read().splitlines()
header = lines[0]
```

```python
# fix — validate at the boundary and fail with a clear message
lines = sys.stdin.read().splitlines()
if not lines:
    sys.exit("error: empty input — expected at least one line")
header = lines[0]
```
