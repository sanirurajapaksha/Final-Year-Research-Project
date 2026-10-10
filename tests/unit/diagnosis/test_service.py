from argus.contracts import DiagnosisResult, SemanticContext
from argus.diagnosis.service import diagnose


def test_diagnose_returns_a_diagnosis_result():
    assert isinstance(diagnose(SemanticContext()), DiagnosisResult)
