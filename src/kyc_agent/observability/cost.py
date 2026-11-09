# USD per 1M tokens. Refresh from provider pricing before using for real cost reporting.
RATES_PER_MILLION = {"gpt-4o-mini": {"input": 0.15, "output": 0.60}}

def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int):
    rates = RATES_PER_MILLION.get(model)
    if not rates:
        return None
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000
