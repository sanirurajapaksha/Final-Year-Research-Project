"""DRAFT step: rival hypotheses for the loop to test.

RuleGenerator is the no-LLM fallback: it pairs the top candidates with a small table of common
faults. `validate` holds the rules every generator must obey, so LLMGenerator (step 7) reuses it.
"""

from argus.diagnosis.core.models import DiagContext, HypothesisSpec
from argus.diagnosis.core.readonly import is_read_only

# (layer, fault, test template, what the test shows if the fault is real)
SIGNATURES = [
    ("app-config", "missing or wrong dependency address env var",
     "kubectl get deployment {svc} -n {ns} -o yaml", "env var for a callee is absent or points nowhere"),
    ("k8s-network", "Service selects no ready pods",
     "kubectl get endpoints {svc} -n {ns}", "no ready addresses"),
    ("resources", "container OOMKilled or crash-looping",
     "kubectl describe pods -n {ns} -l app={svc}", "Last State: Terminated (OOMKilled) or CrashLoopBackOff"),
]


