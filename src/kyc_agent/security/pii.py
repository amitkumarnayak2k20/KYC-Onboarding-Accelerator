import re

# Demonstration-only patterns. This is not complete PII detection.
PATTERNS = {
    "EMAIL": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "PHONE": re.compile(r"(?:\+?91[- ]?)?[6-9]\d{9}\b"),
    "SORT_CODE": re.compile(r"\b\d{2}-\d{2}-\d{2}\b"),
    "PASSPORT_LIKE": re.compile(r"\b[A-Z][0-9]{7}\b"),
    "DOB_LIKE": re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
}

def redact_text(value: str) -> tuple[str, dict]:
    redacted = value or ""
    counts = {}
    for label, pattern in PATTERNS.items():
        found = pattern.findall(redacted)
        if found:
            counts[label] = len(found)
            redacted = pattern.sub(f"[REDACTED_{label}]", redacted)
    return redacted, counts
