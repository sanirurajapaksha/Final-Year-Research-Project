from sre_agent.contracts import DiagnosisResult, SemanticContext
from sre_agent.diagnosis.service import diagnose


def test_diagnose_returns_a_diagnosis_result():
    assert isinstance(diagnose(SemanticContext()), DiagnosisResult)
