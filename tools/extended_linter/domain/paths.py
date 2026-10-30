import fnmatch


def normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def matches_glob(path: str, pattern: str) -> bool:
    """Apply the same normalized glob semantics to denies and exemptions."""
    normalized = normalize_path(path)
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        if normalized == prefix or normalized.startswith(prefix + "/"):
            return True
    if "/" not in pattern and "*" not in pattern:
        return normalized == pattern
    return fnmatch.fnmatch(normalized, pattern)
