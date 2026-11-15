"""In-place edits of a policy file for `ai-task policy sync`.

Sync used to write render_policy_toml(merged), a fresh render of the parsed TOML,
so applying one key dropped every comment, reflowed lists and moved tables. This
module applies the merge result to the existing file text instead:

- a key added from the bundled template is inserted into its table with the
  template's comment block above it, after the nearest template sibling the file
  already has;
- a changed value is replaced on its own lines, keeping the indent, the list
  layout (one line or one item per line) and a trailing comment;
- a missing table is appended at the end of the file, copied from the template
  text with its comments.

Everything outside the edited lines stays byte for byte. The result must parse to
exactly the merged data; when it does not, or an edit has no safe place (an inline
table, a dotted key, an array of tables), edit_policy_text falls back to the full
render and returns the reason, so the caller can say so in its report.

Standard library only, like ai_task.policy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback.
    tomllib = None  # type: ignore[assignment]

from ai_task.policy import (
    format_toml_scalar,
    loads_policy_toml,
    render_dict_table,
    render_policy_toml,
)

_HEADER_RE = re.compile(r"^\s*\[(?!\[)(?P<name>[^\]]+)\]\s*(?:#.*)?$")
_ARRAY_TABLE_RE = re.compile(r"^\s*\[\[")
_KEY_RE = re.compile(r'^(?P<indent>[ \t]*)(?P<key>[A-Za-z0-9_-]+|"[^"\\]*")[ \t]*=')
_BARE_KEY_RE = re.compile(r"[A-Za-z0-9_-]+")
_ITEM_INDENT_RE = re.compile(r"^([ \t]*)")


class PolicyEditError(Exception):
    """An edit has no safe place in the file text; the caller renders instead."""


@dataclass
class _Entry:
    key_text: str  # the key as written, quotes included
    indent: str
    start: int  # first line of `key = value`
    end: int  # one past its last line


@dataclass
class _Table:
    path: tuple[str, ...]
    header: int | None  # line of the [header]; None for the root table
    end: int = 0  # one past the table body (the next header's leading comments)
    entries: dict[str, _Entry] = field(default_factory=dict)


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith("#")


def _is_blank(line: str) -> bool:
    return not line.strip()


def _parses(text: str) -> dict[str, Any] | None:
    if tomllib is None:  # pragma: no cover - guarded by loads_policy_toml callers.
        return None
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None


def _split_header(name: str) -> tuple[str, ...]:
    parts: list[str] = []
    for raw in name.split("."):
        part = raw.strip()
        if _BARE_KEY_RE.fullmatch(part):
            parts.append(part)
        elif len(part) >= 2 and part[0] == part[-1] == '"' and "\\" not in part:
            parts.append(part[1:-1])
        else:
            raise PolicyEditError(f"table header [{name}] is not a plain dotted name")
    return tuple(parts)


def _value_end(lines: list[str], start: int) -> int:
    """One past the last line of the `key = value` that starts at `start`."""
    for end in range(start + 1, len(lines) + 1):
        if _parses("".join(lines[start:end])) is not None:
            return end
    raise PolicyEditError(f"line {start + 1}: value does not parse")


def _leading_comments(lines: list[str], index: int, floor: int) -> int:
    """First line of the comment run directly above `index` (no blank line between)."""
    start = index
    while start - 1 >= floor and _is_comment(lines[start - 1]):
        start -= 1
    return start


def _parse(lines: list[str]) -> list[_Table]:
    tables = [_Table(path=(), header=None)]
    index = 0
    while index < len(lines):
        line = lines[index]
        if _ARRAY_TABLE_RE.match(line):
            raise PolicyEditError(f"line {index + 1}: arrays of tables are not edited")
        header = _HEADER_RE.match(line)
        if header:
            tables.append(_Table(path=_split_header(header["name"]), header=index))
            index += 1
            continue
        if _is_blank(line) or _is_comment(line):
            index += 1
            continue
        match = _KEY_RE.match(line)
        if not match:
            raise PolicyEditError(f"line {index + 1}: not a plain `key = value` line")
        end = _value_end(lines, index)
        key_text = match["key"]
        key = key_text[1:-1] if key_text.startswith('"') else key_text
        tables[-1].entries[key] = _Entry(key_text, match["indent"], index, end)
        index = end
    for position, table in enumerate(tables):
        if position + 1 < len(tables):
            nxt = tables[position + 1]
            assert nxt.header is not None
            floor = max((e.end for e in table.entries.values()), default=0)
            if table.header is not None:
                floor = max(floor, table.header + 1)
            table.end = _leading_comments(lines, nxt.header, floor)
        else:
            table.end = len(lines)
    return tables


def _toml_key(key: str) -> str:
    if _BARE_KEY_RE.fullmatch(key):
        return key
    return format_toml_scalar(key)


def _inline_value(value: Any) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(_inline_value(item) for item in value) + "]"
    if isinstance(value, dict):
        items = ", ".join(
            f"{_toml_key(k)} = {_inline_value(v)}" for k, v in value.items()
        )
        return "{ " + items + " }" if items else "{}"
    return format_toml_scalar(value)


def _inline_comment(line: str, key: str) -> str:
    """Trailing `  # comment` of a one-line `key = value`, or ""."""
    body = line.rstrip("\n")
    whole = _parses(body + "\n")
    if whole is None:
        return ""
    for match in re.finditer("#", body):
        head = body[: match.start()]
        parsed = _parses(head + "\n")
        if parsed is not None and parsed.get(key) == whole.get(key):
            return body[len(head.rstrip()) :]
    return ""


def _replacement(lines: list[str], entry: _Entry, key: str, value: Any) -> list[str]:
    first = lines[entry.start]
    lead = f"{entry.indent}{entry.key_text} = "
    if entry.end - entry.start == 1:
        return [lead + _inline_value(value) + _inline_comment(first, key) + "\n"]
    if isinstance(value, list) and not any(isinstance(v, (list, dict)) for v in value):
        indent_match = _ITEM_INDENT_RE.match(lines[entry.start + 1])
        item_indent = indent_match.group(1) if indent_match else "    "
        body = [f"{item_indent}{_inline_value(item)},\n" for item in value]
        return [lead + "[\n", *body, f"{entry.indent}]\n"]
    return [lead + _inline_value(value) + "\n"]


def _template_entry_text(
    template_lines: list[str],
    template_tables: dict[tuple[str, ...], _Table],
    path: tuple[str, ...],
    key: str,
    value: Any,
) -> list[str] | None:
    """The template's comment block for `key` and its `key = value` lines.

    The template's own value lines are kept when they carry `value`; otherwise
 the line is rendered with `value`.
    """
    table = template_tables.get(path)
    if table is None or key not in table.entries:
        return None
    entry = table.entries[key]
    floor = table.header + 1 if table.header is not None else 0
    floor = max(
        [floor, *(e.end for e in table.entries.values() if e.end <= entry.start)]
    )
    start = _leading_comments(template_lines, entry.start, floor)
    comments = template_lines[start : entry.start]
    parsed = _parses("".join(template_lines[entry.start : entry.end]))
    if parsed is not None and parsed.get(key) == value:
        return comments + template_lines[entry.start : entry.end]
    return [*comments, f"{entry.key_text} = {_inline_value(value)}\n"]


def _template_table_text(
    template_lines: list[str],
    template_tables: list[_Table],
    path: tuple[str, ...],
) -> list[str]:
    """The template's [path] table and its sub-tables, with their comment blocks."""
    out: list[str] = []
    for position, table in enumerate(template_tables):
        if table.header is None or table.path[: len(path)] != path:
            continue
        previous_end = template_tables[position - 1].end if position else 0
        start = _leading_comments(template_lines, table.header, previous_end)
        block = template_lines[start : table.end]
        while block and _is_blank(block[-1]):
            block = block[:-1]
        if out:
            out.append("\n")
        out.extend(block)
    return out


def _anchor(
    lines: list[str],
    table: _Table,
    key: str,
    template_order: list[str],
) -> int:
    """Line where a new `key` goes: after its nearest earlier template sibling the
    file has, else before the comment block of its nearest later one."""
    if key in template_order:
        position = template_order.index(key)
        for sibling in reversed(template_order[:position]):
            if sibling in table.entries:
                return table.entries[sibling].end
        for sibling in template_order[position + 1 :]:
            if sibling in table.entries:
                entry = table.entries[sibling]
                floor = table.header + 1 if table.header is not None else 0
                return _leading_comments(lines, entry.start, floor)
    else:
        # A key sync adds itself (model_override_bundled) joins its family.
        family = key.rsplit("_", 1)[0]
        related = [e.end for k, e in table.entries.items() if k.startswith(family)]
        if related:
            return max(related)
    if table.entries:
        return max(entry.end for entry in table.entries.values())
    if table.header is None:
        raise PolicyEditError(f"cannot place {key} in the root table")
    return table.header + 1


def _plan(
    local: dict[str, Any],
    merged: dict[str, Any],
    path: tuple[str, ...] = (),
) -> list[tuple[str, tuple[str, ...], str, Any]]:
    ops: list[tuple[str, tuple[str, ...], str, Any]] = []
    for key, value in merged.items():
        if key not in local:
            if isinstance(value, dict):
                ops.append(("table", (*path, key), "", value))
            else:
                ops.append(("add", path, key, value))
            continue
        current = local[key]
        if isinstance(value, dict) and isinstance(current, dict):
            ops.extend(_plan(current, value, (*path, key)))
        elif value != current:
            ops.append(("set", path, key, value))
    return ops


def _edit(
    text: str,
    local: dict[str, Any],
    merged: dict[str, Any],
    template_text: str,
) -> str:
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    tables = {table.path: table for table in _parse(lines)}
    template_lines = template_text.splitlines(keepends=True)
    template_list = _parse(template_lines)
    template_tables = {table.path: table for table in template_list}

    replacements: dict[int, tuple[int, list[str]]] = {}
    inserts: dict[int, list[str]] = {}
    appended: list[list[str]] = []
    for kind, path, key, value in _plan(local, merged):
        if kind == "table":
            block = _template_table_text(template_lines, template_list, path)
            if not block or _parses("".join(block)) is None:
                block = render_dict_table(".".join(path), value)
                block = [line + "\n" for line in block]
            appended.append(block)
            continue
        table = tables.get(path)
        if table is None:
            raise PolicyEditError(f"[{'.'.join(path)}] has no header in the file")
        if kind == "set":
            entry = table.entries.get(key)
            if entry is None:
                raise PolicyEditError(
                    f"{'.'.join((*path, key))} is not a plain key line"
                )
            replacements[entry.start] = (
                entry.end,
                _replacement(lines, entry, key, value),
            )
            continue
        new_lines = _template_entry_text(
            template_lines, template_tables, path, key, value
        ) or [f"{_toml_key(key)} = {_inline_value(value)}\n"]
        template_table = template_tables.get(path)
        order = list(template_table.entries) if template_table else []
        inserts.setdefault(_anchor(lines, table, key, order), []).extend(new_lines)

    out: list[str] = []
    index = 0
    while index <= len(lines):
        out.extend(inserts.get(index, []))
        if index == len(lines):
            break
        if index in replacements:
            end, new_lines = replacements[index]
            out.extend(new_lines)
            index = end
            continue
        out.append(lines[index])
        index += 1
    for block in appended:
        if out and not _is_blank(out[-1]):
            out.append("\n")
        out.extend(block)
    return "".join(out)


def edit_policy_text(
    text: str,
    local: dict[str, Any],
    merged: dict[str, Any],
    template_text: str,
) -> tuple[str, str | None]:
    """The policy file text with the sync result applied in place.

    Returns (text, None) on an in-place edit, or (full render, reason) when the
    edit could not be placed or did not parse back to `merged`.
    """
    try:
        edited = _edit(text, local, merged, template_text)
    except PolicyEditError as exc:
        return render_policy_toml(merged), str(exc)
    if _parses(edited) != loads_policy_toml(render_policy_toml(merged)):
        return render_policy_toml(
            merged
        ), "the edited text did not parse to the merged policy"
    return edited, None


def fallback_note(reason: str, backup_path: Any) -> str:
    """The report line for an edit that fell back to the full render."""
    return (
        f"Note: the policy could not be edited in place ({reason}), so it was "
        "rewritten from the merged data: its comments and layout were not kept. "
        f"The previous file is in {backup_path}."
    )
