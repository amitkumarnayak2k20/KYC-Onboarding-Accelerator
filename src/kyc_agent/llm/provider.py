import json, re
from ..config import settings
from ..schemas import ExtractedFields
from ..observability.metrics import LLM_TOKENS, LLM_COST
from ..observability.cost import estimate_cost_usd
from ..observability.tracing import span

def _mock_extract(text: str) -> dict:
    # Deterministic parser for labelled synthetic training text.
    patterns = {
        "full_name": r"(?im)^\s*(?:name|full name)\s*:\s*(.+?)\s*$",
        "date_of_birth": r"(?im)^\s*(?:date of birth|dob)\s*:\s*(.+?)\s*$",
        "document_number": r"(?im)^\s*(?:document number|passport number|id number)\s*:\s*(.+?)\s*$",
        "expiry_date": r"(?im)^\s*(?:expiry date|expiration date)\s*:\s*(.+?)\s*$",
        "address": r"(?im)^\s*address\s*:\s*(.+?)\s*$",
    }
    result = {}
    for field, pattern in patterns.items():
        match = re.search(pattern, text)
        result[field] = match.group(1).strip() if match else None
    result["document_type"] = None
    return result

def extract_fields(document_text: str, document_type: str):
    with span("llm.document_extraction", {"llm.provider": settings.llm_provider,
                                         "document.type": document_type}):
        if settings.llm_provider == "openai":
            if not settings.openai_api_key:
                raise RuntimeError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
            from openai import OpenAI
            client = OpenAI(api_key=settings.openai_api_key)
            response = client.chat.completions.create(
                model=settings.openai_model, temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content":
                     "Extract only explicitly present fields from the supplied synthetic text. "
                     "Return JSON keys full_name,date_of_birth,document_number,expiry_date,address,document_type. "
                     "Use null for missing or ambiguous fields. Never infer values."},
                    {"role": "user", "content": f"Type: {document_type}\nText:\n{document_text}"}
                ])
            raw = json.loads(response.choices[0].message.content or "{}")
            usage = response.usage
            input_tokens = getattr(usage, "prompt_tokens", 0) or 0
            output_tokens = getattr(usage, "completion_tokens", 0) or 0
            model = settings.openai_model
            LLM_TOKENS.labels("input", model).inc(input_tokens)
            LLM_TOKENS.labels("output", model).inc(output_tokens)
            cost = estimate_cost_usd(model, input_tokens, output_tokens)
            if cost is not None:
                LLM_COST.labels(model).inc(cost)
            usage_info = {"model": model, "input_tokens": input_tokens,
                          "output_tokens": output_tokens, "estimated_cost_usd": cost}
        else:
            raw = _mock_extract(document_text)
            usage_info = {"model": "mock-parser", "input_tokens": 0,
                          "output_tokens": 0, "estimated_cost_usd": 0.0}
        raw["document_type"] = raw.get("document_type") or document_type
        return ExtractedFields(**raw), usage_info
