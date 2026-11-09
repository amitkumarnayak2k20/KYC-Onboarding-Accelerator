from kyc_agent.rag.chunking import chunk_text, chunk_units
from kyc_agent.rag.loaders import TextUnit, load_document
from kyc_agent.security.pii import redact_text


def test_chunking_respects_size_and_creates_overlap():
    text = ("This is a sentence with useful context. " * 30).strip()
    chunks = chunk_text(text, chunk_size=180, overlap=40)
    assert len(chunks) > 1
    assert all(len(chunk) <= 180 for chunk in chunks)
    # Adjacent chunks should retain some context when overlap is configured.
    assert chunks[0][-20:] in chunks[1]


def test_chunk_units_preserve_source_metadata():
    units = [TextUnit("Policy text. " * 80, "policy.md", "section-1")]
    chunks = chunk_units(units, chunk_size=150, overlap=30)
    assert chunks
    assert chunks[0].source == "policy.md"
    assert chunks[0].unit_id == "section-1"
    assert chunks[0].chunk_index == 0


def test_redaction_happens_before_indexing():
    redacted, counts = redact_text("Contact user@example.test or 9876543210; sort code 12-34-56")
    assert "user@example.test" not in redacted
    assert "9876543210" not in redacted
    assert "12-34-56" not in redacted
    assert counts["EMAIL"] == 1
    assert counts["PHONE"] == 1
    assert counts["SORT_CODE"] == 1


def test_json_loader_creates_text_units(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text('{"topic":"passport", "required":["name", "date of birth"]}', encoding="utf-8")
    units = load_document(path)
    assert len(units) == 1
    assert "topic: passport" in units[0].text
    assert "required[0]: name" in units[0].text
