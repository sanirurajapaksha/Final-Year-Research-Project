"""Step 8: the REPORT step, with FakeLLM playing the model."""

from argus.contracts import ProposedAction
from argus.diagnosis.core.models import Candidate, DiagContext, Evidence, HypothesisSpec
from argus.diagnosis.demo import scenario_reads
from argus.diagnosis.loop.report import MAX_WORDS, ReportWriter, top_verdicts
from argus.diagnosis.ports.fakes import FakeLLM
from argus.diagnosis.prompts import render_report
from argus.diagnosis.service import diagnose_report

CTX = DiagContext(
    namespace="default",
    candidates=[Candidate(service="cart")],
    symptoms=["cart: log_error (failed to connect to redis: CART_ADDR environment variable not set)"],
)
TOP = HypothesisSpec(
    id="H1",
    component="cart",
    layer="app-config",
    fault="CART_ADDR env var missing",
    test="kubectl get deployment cart -n default -o json",
)
E1 = Evidence(id="E1", hyp_id="H1", command=TOP.test, output='{"env": []}', ok=True)
FIX = ProposedAction(command="kubectl patch deployment cart -n default -p '{}'", is_write=True)
GOOD = (
    "cart cannot reach redis because its CART_ADDR env var is missing [E1] [S1], so cart requests fail. "
    "M2 proposes setting it with a patch, which the safety gate (M3) checks before it runs."
)


def write(llm, confirmed=True, fix=FIX, note=""):
    return ReportWriter(llm).write(
        TOP, 0.85, confirmed, "confident", [E1], {"E1": "strong-support"}, fix, note, CTX
    )


def reply(text, cited=("E1",)):
    return FakeLLM({"report": [{"text": text, "cited": list(cited)}]})


def test_a_good_llm_note_is_used():
    text, source = write(reply(GOOD))
    assert (text, source) == (GOOD, "llm")


def test_notes_that_break_a_rule_fall_back_to_the_template():
    bad = {
        "too long": ("cart " * (MAX_WORDS + 1)).strip() + " [E1]",
        "cites a read that never happened": GOOD.replace("[E1]", "[E7]"),
        "cites nothing": "cart has a missing CART_ADDR env var. M3 checks the fix.",
        "does not name the service": "A setting is missing [E1]. M3 checks the fix.",
    }
    for why, text in bad.items():
        out, source = write(reply(text, cited=()))
        assert source == "template", why
        assert out.startswith("Root cause: cart [app-config]")


def test_an_unconfirmed_guess_must_say_so():
    _, source = write(reply(GOOD), confirmed=False, fix=None, note="No write: not confirmed")
    assert source == "template"  # GOOD reads like a finding
    ok = "Unconfirmed: cart may be missing CART_ADDR [E1]; M2 proposes only the read that would check it."
    assert write(reply(ok), confirmed=False, fix=None) == (ok, "llm")


def test_no_llm_gives_the_template_with_the_facts():
    text, source = ReportWriter().write(
        TOP, 0.85, True, "confident", [E1], {"E1": "strong-support"}, FIX, "", CTX
    )
    assert source == "template"
    assert text == (
        "Root cause: cart [app-config] CART_ADDR env var missing (85%), confirmed by 1 read(s) "
        f"(E1 strong-support). Proposed fix, to be checked by M3: {FIX.command}"
    )


def test_template_for_an_unconfirmed_guess_says_so_and_carries_the_reason():
    text, _ = ReportWriter().write(
        TOP, 0.28, False, "out of hypotheses", [], {}, None, "No write: unconfirmed", CTX
    )
    assert text.startswith("Unconfirmed: the best guess is cart") and text.endswith("No write: unconfirmed")


def test_top_verdicts_keep_only_the_reads_that_judged_the_hypothesis():
    history = [
        {"event": "init"},
        {"event": "update", "evidence": "E1", "verdicts": {"H1": "strong-support", "H2": "neutral"}},
        {"event": "update", "evidence": "E2", "verdicts": {"H2": "strong-refute"}},
    ]
    assert top_verdicts(history, "H1") == {"E1": "strong-support"}


def test_the_prompt_carries_the_facts_and_the_confirmation_status():
    facts = ["Diagnosis: cart [app-config] f", "Belief: 85%; stop reason: confident; confirmed by the reads"]
    confirmed = render_report(facts, [], ["cart: x"], confirmed=True)
    unconfirmed = render_report(facts, [], ["cart: x"], confirmed=False)
    assert "Diagnosis: cart [app-config] f" in confirmed and "<signals>" in confirmed
    assert "did NOT confirm" in unconfirmed and "did NOT confirm" not in confirmed


def test_report_reaches_the_dashboard_data_and_the_top_hypothesis(m2_context):
    context, _ = m2_context("cart_addr")
    report = diagnose_report(context, llm=reply(GOOD), reads=scenario_reads())
    assert report["report_source"] == "llm" and report["report_text"] == GOOD
    assert report["diagnosis"]["hypotheses"][0]["evidence"][0] == f"Report (llm): {GOOD}"


def test_a_failed_read_is_never_citable():
    # deepseek-v4-flash's first end-to-end note cited a failed read as "redis endpoints unavailable".
    failed = Evidence(
        id="E2", hyp_id="H2", command="kubectl get endpoints redis -n default", output="", ok=False
    )
    llm = reply(GOOD.replace("[E1] [S1]", "[E1] [E2]"))
    text, source = ReportWriter(llm).write(
        TOP, 0.85, True, "confident", [E1, failed], {"E1": "strong-support"}, FIX, "", CTX
    )
    assert source == "template"
    sent = llm.prompts[0][1]
    assert [e["id"] for e in sent["evidence"]] == ["E1"]
    assert any("E2" in line and "not evidence" in line for line in sent["facts"])


def test_template_for_a_tentative_fix_says_it_is_not_confirmed():
    text, _ = ReportWriter().write(TOP, 0.62, False, "out of hypotheses", [E1], {}, FIX, "", CTX)
    assert text.startswith("Unconfirmed: the best guess is cart")
    assert text.endswith(
        f"Tentative fix, sent to M3 for checking only because the cause is not confirmed: {FIX.command}"
    )
