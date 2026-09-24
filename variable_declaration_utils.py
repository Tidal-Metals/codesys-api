"""Helpers for listing and editing IEC declaration variables."""

from __future__ import annotations

import re
from dataclasses import dataclass


VAR_HEADER_RE = re.compile(r"^\s*(VAR(?:_[A-Z]+)?)(?:\s+.*)?$", re.IGNORECASE)
END_VAR_RE = re.compile(r"^\s*END_VAR\s*$", re.IGNORECASE)
DECL_RE = re.compile(
    r"""
    ^
    (?P<indent>\s*)
    (?P<names>[A-Za-z_][A-Za-z0-9_]*(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*)*)
    (?P<address>\s+AT\s+[^:;]+)?
    \s*:\s*
    (?P<type>[^;:=]+?)
    (?:\s*:=\s*(?P<initial>.*?))?
    \s*;
    (?P<tail>\s*(?://.*)?)$
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass
class VarBlock:
    header_index: int
    end_index: int
    header_line: str
    section: str


def _split_lines(text: str) -> tuple[list[str], str]:
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    if text.endswith(("\r\n", "\n", "\r")):
        return lines, newline
    return lines, newline


def _join_lines(lines: list[str], newline: str) -> str:
    return newline.join(lines)


def find_var_blocks(declaration: str) -> list[VarBlock]:
    lines, _ = _split_lines(declaration)
    blocks: list[VarBlock] = []
    current_header = None
    current_section = None

    for idx, line in enumerate(lines):
        header_match = VAR_HEADER_RE.match(line)
        if header_match:
            current_header = idx
            current_section = header_match.group(1).upper()
            continue
        if current_header is not None and END_VAR_RE.match(line):
            blocks.append(
                VarBlock(
                    header_index=current_header,
                    end_index=idx,
                    header_line=lines[current_header],
                    section=current_section or "VAR",
                )
            )
            current_header = None
            current_section = None

    return blocks


def parse_variables(declaration: str, path: str) -> list[dict]:
    lines, _ = _split_lines(declaration)
    blocks = find_var_blocks(declaration)
    results: list[dict] = []

    for block in blocks:
        for idx in range(block.header_index + 1, block.end_index):
            line = lines[idx]
            match = DECL_RE.match(line)
            if not match:
                continue
            names = [name.strip() for name in match.group("names").split(",")]
            address = (match.group("address") or "").strip()
            type_name = match.group("type").strip()
            initial = (match.group("initial") or "").strip()
            tail = (match.group("tail") or "").strip()
            comment = tail[2:].strip() if tail.startswith("//") else ""
            for name in names:
                results.append(
                    {
                        "name": name,
                        "type": type_name,
                        "initialValue": initial,
                        "address": address[3:].strip() if address.upper().startswith("AT ") else address,
                        "section": block.section,
                        "path": path,
                        "line": idx + 1,
                        "rawLine": line,
                        "comment": comment,
                    }
                )

    return results


def _build_declaration_line(
    name: str,
    type_name: str,
    initial_value: str | None,
    address: str | None,
    comment: str | None,
    indent: str,
) -> str:
    line = indent + name
    if address:
        line += " AT " + address
    line += " : " + type_name
    if initial_value not in (None, ""):
        line += " := " + initial_value
    line += ";"
    if comment:
        line += " // " + comment
    return line


def _find_existing_var(
    declaration: str,
    name: str,
) -> tuple[VarBlock | None, int | None, re.Match[str] | None]:
    lines, _ = _split_lines(declaration)
    blocks = find_var_blocks(declaration)
    needle = name.casefold()

    for block in blocks:
        for idx in range(block.header_index + 1, block.end_index):
            match = DECL_RE.match(lines[idx])
            if not match:
                continue
            names = [item.strip() for item in match.group("names").split(",")]
            if any(item.casefold() == needle for item in names):
                return block, idx, match
    return None, None, None


def upsert_variable(
    declaration: str,
    path: str,
    name: str,
    type_name: str | None = None,
    initial_value: str | None = None,
    address: str | None = None,
    comment: str | None = None,
    section: str | None = None,
    declaration_line: str | None = None,
) -> tuple[str, dict]:
    lines, newline = _split_lines(declaration)
    blocks = find_var_blocks(declaration)
    target_section = (section or "").strip().upper()
    if not target_section:
        target_section = blocks[0].section if blocks else "VAR"

    block, line_index, match = _find_existing_var(declaration, name)
    operation = "created"

    if line_index is not None and match is not None and block is not None:
        existing_names = [item.strip() for item in match.group("names").split(",")]
        indent = match.group("indent") or "    "
        existing_type = match.group("type").strip()
        existing_initial = (match.group("initial") or "").strip()
        existing_address = (match.group("address") or "").strip()
        existing_address = existing_address[3:].strip() if existing_address.upper().startswith("AT ") else existing_address
        tail = (match.group("tail") or "").strip()
        existing_comment = tail[2:].strip() if tail.startswith("//") else ""

        final_type = type_name or existing_type
        final_initial = initial_value if initial_value is not None else existing_initial
        final_address = address if address is not None else existing_address
        final_comment = comment if comment is not None else existing_comment

        replacement = declaration_line or _build_declaration_line(
            name=name,
            type_name=final_type,
            initial_value=final_initial,
            address=final_address,
            comment=final_comment,
            indent=indent,
        )

        if len(existing_names) == 1:
            lines[line_index] = replacement
        else:
            rebuilt: list[str] = []
            for existing_name in existing_names:
                if existing_name.casefold() == name.casefold():
                    rebuilt.append(replacement)
                else:
                    rebuilt.append(
                        _build_declaration_line(
                            name=existing_name,
                            type_name=existing_type,
                            initial_value=existing_initial,
                            address=existing_address,
                            comment=existing_comment,
                            indent=indent,
                        )
                    )
            lines[line_index : line_index + 1] = rebuilt
        operation = "updated"
    else:
        target_block = None
        for candidate in blocks:
            if candidate.section == target_section:
                target_block = candidate
                break
        if target_block is None and blocks:
            target_block = blocks[0]
        indent = "    "
        if target_block is not None:
            for idx in range(target_block.header_index + 1, target_block.end_index):
                match = DECL_RE.match(lines[idx])
                if match:
                    indent = match.group("indent") or indent
                    break
            insert_index = target_block.end_index
            line = declaration_line or _build_declaration_line(
                name=name,
                type_name=type_name or "WORD",
                initial_value=initial_value,
                address=address,
                comment=comment,
                indent=indent,
            )
            lines.insert(insert_index, line)
        else:
            if lines and lines[-1].strip():
                lines.append("")
            header = target_section or "VAR"
            lines.extend(
                [
                    header,
                    declaration_line
                    or _build_declaration_line(
                        name=name,
                        type_name=type_name or "WORD",
                        initial_value=initial_value,
                        address=address,
                        comment=comment,
                        indent=indent,
                    ),
                    "END_VAR",
                ]
            )

    new_declaration = _join_lines(lines, newline)
    variables = parse_variables(new_declaration, path)
    target = next((item for item in variables if item["name"].casefold() == name.casefold()), None)
    return new_declaration, {"operation": operation, "variable": target}


def delete_variable(declaration: str, path: str, name: str) -> tuple[str, dict]:
    lines, newline = _split_lines(declaration)
    _, line_index, match = _find_existing_var(declaration, name)
    if line_index is None or match is None:
        return declaration, {"operation": "noop", "deleted": False}

    existing_names = [item.strip() for item in match.group("names").split(",")]
    indent = match.group("indent") or "    "
    existing_type = match.group("type").strip()
    existing_initial = (match.group("initial") or "").strip()
    existing_address = (match.group("address") or "").strip()
    existing_address = existing_address[3:].strip() if existing_address.upper().startswith("AT ") else existing_address
    tail = (match.group("tail") or "").strip()
    existing_comment = tail[2:].strip() if tail.startswith("//") else ""

    remaining = [item for item in existing_names if item.casefold() != name.casefold()]
    if not remaining:
        del lines[line_index]
    elif len(remaining) == 1:
        lines[line_index] = _build_declaration_line(
            name=remaining[0],
            type_name=existing_type,
            initial_value=existing_initial,
            address=existing_address,
            comment=existing_comment,
            indent=indent,
        )
    else:
        rebuilt = []
        for item in remaining:
            rebuilt.append(
                _build_declaration_line(
                    name=item,
                    type_name=existing_type,
                    initial_value=existing_initial,
                    address=existing_address,
                    comment=existing_comment,
                    indent=indent,
                )
            )
        lines[line_index : line_index + 1] = rebuilt

    new_declaration = _join_lines(lines, newline)
    return new_declaration, {"operation": "deleted", "deleted": True, "name": name, "path": path}
