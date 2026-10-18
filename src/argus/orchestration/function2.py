"""M4's routed diagnostic entry point using existing shared contract models."""

import json
from collections.abc import Callable
from dataclasses import dataclass

from argus.contracts import DiagnosisResult, SemanticContext
from argus.orchestration.budget import EstimatedBudget
from argus.orchestration.execution import Executor, Gate
from argus.orchestration.model_dispatch import DispatchPolicy, DispatchResult, ModelAdapter, dispatch
from argus.orchestration.pipeline import FeedbackHandler, PipelineResult, process_diagnosis
from argus.orchestration.router import RoutingRequest


@dataclass(frozen=True)
class Function2Result:
    dispatch: DispatchResult
    # None when no valid diagnosis was produced. Inspect dispatch for the reason.
    pipeline: PipelineResult | None = None


def _diagnosis_from_output(value: object) -> DiagnosisResult:
    # Shared models are mutable; do not trust an already constructed instance
    # without revalidating its current contents at the model-output boundary.
    if isinstance(value, DiagnosisResult):
        value = value.model_dump(mode="json")
    if isinstance(value, str):
        return DiagnosisResult.model_validate_json(value, strict=True)
    return DiagnosisResult.model_validate(value, strict=True)


def run_function2(
    context: SemanticContext,
    *,
    request: RoutingRequest,
    adapter: ModelAdapter,
    policy: DispatchPolicy,
    budget: EstimatedBudget,
    gate: Gate | None = None,
    executor: Executor | None = None,
    feedback_handler: FeedbackHandler | None = None,
    prompt_builder: Callable[[SemanticContext], str] | None = None,
) -> Function2Result:
    """Route one diagnostic task, validate DiagnosisResult, and handle its actions.

    M2 owns diagnostic prompts and hypothesis construction; M4 owns routing,
    budget and dispatch. Supply M2's prompt_builder for its reasoning adapter.
    The default JSON envelope is a fake-adapter placeholder with no diagnostic
    instructions or schema; it is not a real-provider prompt or an M2 replacement.
    The adapter supplies model output, not shell execution.
    Caller-owned configuration and metadata stay within M4's local interfaces.
    Failed planning/calls return no pipeline result and perform no action handling.

    BLOCK feedback is handed to M2's existing stub or an explicitly supplied
    local feedback handler once. Its revised actions are retained, never executed.
    This callback must not make unaccounted provider calls; future model feedback
    rounds must use the routed dispatch interface and the shared incident ledger.
    """
    if not isinstance(context, SemanticContext):
        raise TypeError("context must be a shared SemanticContext instance")
    # Revalidate mutable shared-model contents and isolate the caller's object.
    context = SemanticContext.model_validate(context.model_dump(mode="json"))
    request = RoutingRequest.model_validate(request)
    if len(request.tasks) != 1 or request.tasks[0].task_kind != "diagnostic_reasoning":
        raise ValueError("Function 2 requires exactly one diagnostic_reasoning task")
    if feedback_handler is not None and not callable(feedback_handler):
        raise ValueError("feedback_handler must be callable")
    if prompt_builder is not None and not callable(prompt_builder):
        raise ValueError("prompt_builder must be callable")

    task_id = request.tasks[0].task_id
    prompt = (
        prompt_builder(context.model_copy(deep=True))
        if prompt_builder is not None
        else json.dumps(
            {"output_contract": "DiagnosisResult", "context": context.model_dump(mode="json")},
            ensure_ascii=False,
        )
    )
    routed = dispatch(
        request,
        adapter=adapter,
        prompts={task_id: prompt},
        validators={task_id: _diagnosis_from_output},
        policy=policy,
        budget=budget,
    )
    if not routed.tasks or routed.tasks[0].status != "succeeded":
        return Function2Result(dispatch=routed)
    diagnosis = routed.tasks[0].output
    handled = process_diagnosis(
        context,
        diagnosis,
        gate=gate,
        executor=executor,
        feedback_handler=feedback_handler,
    )
    return Function2Result(dispatch=routed, pipeline=handled)
