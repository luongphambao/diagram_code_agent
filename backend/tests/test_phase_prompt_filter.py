"""PhasePromptFilterMiddleware strips phase-irrelevant [[PHASE ...]] spans from
the main system prompt — the prose companion to PhaseToolFilterMiddleware."""

from langchain_core.messages import SystemMessage

from agent import PhasePromptFilterMiddleware, _PHASE_TOOLS, _strip_phase_spans
from prompts import build_pretty_system_prompt, build_system_prompt


SAMPLE = (
    "always-on header\n"
    "[[PHASE intake]]\nintake-only text\n[[/PHASE]]\n"
    "[[PHASE intake,blueprint]]\nstack text\n[[/PHASE]]\n"
    "[[PHASE draw,wbs,ppt,report]]\ndeliverables text\n[[/PHASE]]\n"
    "always-on footer"
)


def test_strip_keeps_matching_and_drops_rest():
    out = _strip_phase_spans(SAMPLE, "intake")
    assert "intake-only text" in out
    assert "stack text" in out
    assert "deliverables text" not in out
    assert "[[PHASE" not in out and "[[/PHASE]]" not in out
    assert "always-on header" in out and "always-on footer" in out


def test_strip_draw_phase():
    out = _strip_phase_spans(SAMPLE, "draw")
    assert "intake-only text" not in out
    assert "stack text" not in out
    assert "deliverables text" in out


def test_strip_unknown_phase_keeps_everything():
    # phase=None (detection failed) → keep all spans, still remove markers.
    out = _strip_phase_spans(SAMPLE, None)
    for frag in ("intake-only text", "stack text", "deliverables text"):
        assert frag in out
    assert "[[PHASE" not in out


def test_built_prompts_have_balanced_markers_and_strip_clean():
    for builder in (build_pretty_system_prompt, build_system_prompt):
        prompt = builder("/workspace", "/icons", "/manifest.json")
        assert prompt.count("[[PHASE ") == prompt.count("[[/PHASE]]")
        for phase in list(_PHASE_TOOLS) + [None]:
            stripped = _strip_phase_spans(prompt, phase)
            assert "[[PHASE" not in stripped
            assert "[[/PHASE]]" not in stripped
        # Every phase keeps the always-on scaffolding.
        intake = _strip_phase_spans(prompt, "intake")
        assert "Staged workflow" in intake
        # And the phase view is materially smaller than the full prompt.
        draw = _strip_phase_spans(prompt, "draw")
        assert len(draw) < len(_strip_phase_spans(prompt, None)) - 2000


def test_middleware_filters_system_message(monkeypatch):
    mw = PhasePromptFilterMiddleware()
    monkeypatch.setattr(PhasePromptFilterMiddleware, "_current_phase",
                        staticmethod(lambda: "draw"))

    class Req:
        def __init__(self, content):
            self.system_message = SystemMessage(content=content)

        def override(self, **kw):
            new = Req("")
            new.system_message = kw["system_message"]
            return new

    seen = {}

    def handler(request):
        seen["content"] = request.system_message.content
        return "ok"

    assert mw.wrap_model_call(Req(SAMPLE), handler) == "ok"
    assert "deliverables text" in seen["content"]
    assert "intake-only text" not in seen["content"]
    assert "[[PHASE" not in seen["content"]
