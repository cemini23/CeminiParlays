"""Local loader for LiquidAI/d1-2B.

One forward pass over text. The loader does not send a slip image. It does
not read a remote Jev key. Transformers is imported only when the operator
runs this function.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ceminiparlays.slip_screen import MODEL_ID

Evaluator = Callable[[str, dict[str, Any]], dict[str, Any]]


def load_evaluator() -> Evaluator:
    try:
        import torch
        from transformers import AutoModel
    except ImportError as exc:
        raise RuntimeError(
            "LiquidAI/d1-2B needs a local install of transformers>=5.19 and torch. "
            "The screen does not call a remote model."
        ) from exc

    if torch.cuda.is_available():
        device = "cuda"
    elif torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"
    dtype = torch.float32 if device == "cpu" else torch.bfloat16
    model = AutoModel.from_pretrained(
        MODEL_ID,
        trust_remote_code=True,
        dtype=dtype,
    ).to(device)

    def evaluate(state: str, questions: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(state, str):
            raise ValueError("slip state must be text")
        out = model.system_one(state, questions)
        usage = out.get("usage") or {}
        if int(usage.get("output_tokens") or 0) != 0:
            raise RuntimeError("the model generated tokens; the screen refuses the answer")
        return out

    return evaluate
