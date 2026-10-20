"""Pure source selection and policy limits, usable before any account is created."""
import json
import re


def package_name(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.md", name):
        raise ValueError("Invalid owned source package name.")
    return name


def headings(lines):
    result = []
    fence = None
    for index, line in enumerate(lines):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line.rstrip('\r\n'))
        if fence is not None:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1] and not marker[2].strip():
                fence = None
            continue
        if marker and (marker[1][0] != '`' or '`' not in marker[2]):
            fence = (marker[1][0], len(marker[1]))
            continue
        match = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line.rstrip())
        if match:
            result.append((index, len(match[1]), match[2]))
    return result


def section(lines, title):
    matches = [item for item in headings(lines) if item[2] == title]
    if len(matches) != 1:
        raise ValueError("Expected exactly one Markdown section: " + title)
    start, level, _ = matches[0]
    end = next((i for i, depth, _ in headings(lines) if i > start and depth <= level), len(lines))
    return start, end


def paragraphs(lines, start=0, end=None):
    end = len(lines) if end is None else end
    result = []
    cursor = start
    while cursor < end:
        if not lines[cursor].strip():
            cursor += 1
            continue
        finish = cursor + 1
        while finish < end and lines[finish].strip():
            finish += 1
        result.append((cursor, finish))
        cursor = finish
    return result


def select_text(text, selector):
    lines = text.splitlines(keepends=True)
    if not isinstance(selector, dict) or not isinstance(selector.get('mode'), str):
        raise ValueError('Selector needs a named mode.')
    mode = selector["mode"]
    requirements = {
        'sections': {'titles': list}, 'exclude_sections': {'titles': list},
        'between_markers': {'start': str, 'end': str},
        'json_projection': {'title': str, 'fields': list},
        'paragraphs': {'prefixes': list},
        'status': {'latest_heading': str, 'table_heading': str, 'latest_paragraphs': int},
    }
    for key, kind in requirements.get(mode, {}).items():
        value = selector.get(key)
        if type(value) is not kind or not value:
            raise ValueError('Selector mode '+mode+' requires a nonempty '+key+'.')
        if kind is list and any(not isinstance(item, str) or not item for item in value):
            raise ValueError('Selector '+key+' must contain nonempty strings.')
    if 'preserve_prefixes' in selector and (not isinstance(selector['preserve_prefixes'], list)
            or any(not isinstance(item,str) or not item for item in selector['preserve_prefixes'])):
        raise ValueError('preserve_prefixes must be a list of nonempty strings.')
    if mode == 'status' and selector['latest_paragraphs'] < 1:
        raise ValueError('latest_paragraphs must be positive.')
    if mode == "json_projection" and (not isinstance(selector.get("fields"), list) or not selector["fields"]):
        raise ValueError("JSON projection requires a nonempty fields list.")
    ranges = []
    if mode == "full":
        ranges = [(0, len(lines))]
    elif mode == "sections":
        titles = selector["titles"]
        if not titles or len(titles) != len(set(titles)):
            raise ValueError("Section selection must contain unique headings.")
        ranges = sorted(section(lines, title) for title in titles)
        if any(a[1] > b[0] for a, b in zip(ranges, ranges[1:])):
            raise ValueError("Selected sections must not overlap.")
    elif mode == "between_markers":
        starts = [i for i, line in enumerate(lines) if line.startswith(selector["start"])]
        ends = [i for i, line in enumerate(lines) if line.startswith(selector["end"])]
        if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
            raise ValueError("Missing or ambiguous source section markers.")
        ranges = [(starts[0], ends[0])]
    elif mode == "json_projection":
        value = json.loads(text)
        selected = ["# " + selector["title"], ""]
        def walk(item, parts, prefix):
            if not parts:
                selected.append("- " + prefix + ": " + json.dumps(item, ensure_ascii=False))
            elif parts[0] == "*" and isinstance(item, list):
                for index, child in enumerate(item):
                    walk(child, parts[1:], prefix + "." + str(index))
            elif isinstance(item, dict) and parts[0] in item:
                walk(item[parts[0]], parts[1:], (prefix + "." if prefix else "") + parts[0])
            else:
                raise ValueError("Required JSON source field is missing: " + ".".join(parts))
        for field in selector["fields"]:
            walk(value, field.split("."), "")
        return "\n".join(selected) + "\n", [[1, len(lines)]]
    elif mode == "exclude_sections":
        excluded = [section(lines, title) for title in selector["titles"]
                    if any(h[2] == title for h in headings(lines))]
        for index in range(len(lines)):
            if any(a <= index < b for a, b in excluded):
                if not any(lines[index].startswith(prefix) for prefix in selector.get("preserve_prefixes", [])):
                    continue
            if ranges and ranges[-1][1] == index:
                ranges[-1] = ranges[-1][0], index + 1
            else:
                ranges.append((index, index + 1))
    elif mode == "paragraphs":
        title = next((index for index, depth, _ in headings(lines) if depth == 1), None)
        ranges = [(title, title + 1)] if title is not None else []
        for prefix in selector["prefixes"]:
            matches = [(a, b) for a, b in paragraphs(lines) if lines[a].startswith(prefix)]
            if len(matches) != 1:
                raise ValueError("Missing or ambiguous current paragraph: " + prefix)
            ranges.extend(matches)
    elif mode == "status":
        latest, finish = section(lines, selector["latest_heading"])
        ranges = [(0, latest), (latest, latest + 1)]
        latest_paragraphs = paragraphs(lines, latest + 1, finish)
        if len(latest_paragraphs) < selector["latest_paragraphs"]:
            raise ValueError("Current status lacks latest conclusion paragraphs.")
        ranges.extend(latest_paragraphs[:selector["latest_paragraphs"]])
        # New release notes can push the current entry below the preview window.
        # Keep its explicit redirect boundary without importing older history.
        entry_range = next(((a, b) for a, b in latest_paragraphs
                            if re.search(r"workId\s*`?\d+", "".join(lines[a:b]))
                            and "跳转" in "".join(lines[a:b])), None)
        if entry_range is not None and entry_range not in ranges:
            ranges.append(entry_range)
        start, end = section(lines, selector["table_heading"])
        table = [i for i in range(start + 1, end) if lines[i].lstrip().startswith("|")]
        if not table:
            raise ValueError("Current status feature table is missing.")
        ranges.extend([(start, start + 1), (table[0], table[-1] + 1)])
        if not all(value in "".join(lines[table[0]:table[-1] + 1]) for value in ("上线 Gate", "0 ERR", "阻断")):
            raise ValueError("Current status lacks required Gate/evidence boundary fields.")
    else:
        raise ValueError("Unsupported source selector.")
    selected = "\n\n".join("".join(lines[a:b]).strip() for a, b in ranges if a < b).strip() + "\n"
    if not selected.strip():
        raise ValueError("Selected source text is empty.")
    return selected, [[a + 1, b] for a, b in ranges]


def validate_limits(value):
    budgets = value.get("budgets", {})
    names = {"find", "directory", "read_default", "read_max"}
    if not isinstance(budgets, dict) or set(budgets) != names or any(type(v) is not int for v in budgets.values()):
        raise ValueError("Token budgets must provide find/directory/read_default/read_max integers.")
    if not 512 <= budgets["read_default"] <= budgets["read_max"] <= 15000:
        raise ValueError("Read budgets must satisfy 512 <= read_default <= read_max <= 15000.")
    if not 512 <= budgets["find"] <= 8000 or not 512 <= budgets["directory"] <= 8000:
        raise ValueError("Find and directory budgets must be between 512 and 8000.")
    first, maximum = value.get("find_default_limit"), value.get("find_max_limit")
    if type(first) is not int or type(maximum) is not int or not 1 <= first <= maximum <= 8:
        raise ValueError("Source counts must be integers satisfying 1 <= default <= maximum <= 8.")
    if type(value.get("max_changed_files")) is not int or not 1 <= value["max_changed_files"] <= 5:
        raise ValueError("Incremental changes must remain between 1 and 5 per run.")
