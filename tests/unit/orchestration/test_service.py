from sre_agent.contracts import CompressedTelemetry, ExecutionResult, ProposedAction
from sre_agent.orchestration.service import compress, execute


def test_compress_returns_compressed_telemetry(sample_batch):
    assert isinstance(compress(sample_batch), CompressedTelemetry)


def test_execute_returns_an_execution_result():
    action = ProposedAction(command="kubectl get pods -n demo", is_write=False)
    assert isinstance(execute(action), ExecutionResult)
