# M4 token-counting proposal

Status: Proposal for W2-08. Decisions are pending. W2-08 remains incomplete.
No tokenizer was installed and no token measurements were made for this document.

## Current behaviour and decisions

[M4 F1](m4-F1-telemetry-compression.md) and `src/argus/orchestration/service.py` measure UTF-8 bytes.
`original_size` and `compressed_size` must keep that meaning.
A byte count measures encoded storage size. A token count measures how a
particular tokenizer splits text into token IDs. There is no fixed conversion
between the two. Unicode, punctuation, whitespace, and repeated text can affect
token boundaries. A smaller TSV byte count does not prove fewer tokens.

No model, provider, tokenizer, encoding, or tokenizer package version is
confirmed in the repository. All of these choices are **pending**.
[Architecture](../architecture.md) lists the provider and models as open.
`src/argus/llm/README.md` also leaves provider and client choices open.
[M4 F2](m4-F2-model-routing-execution.md) does not agree on model choices or budget values.
`pyproject.toml` declares no tokenizer dependency. The existing minimal F1
experiment used no model and makes no token-savings claim.

M4 contract v1 integration is now implemented: `alert_time` is copied unchanged,
and one shared JSON-encoded TSV header is retained. Every record, duplicate,
field and original record order must be preserved. Do not drop, merge,
deduplicate or select rows. PP1 measurements remain UTF-8 byte counts.
This integration does not implement token counting or establish token savings.
This is supporting documentation, not a third function specification.
PP1 may report UTF-8 byte counts now; tokenizer selection is not a blocker
for byte evaluation. The [byte evaluation](../../experiments/2026-10-13_m4_contract_v1/NOTES.md)
records a separate result on one synthetic scenario.

## Proposed interface

Use a small local measurement helper, separate from shared contracts:

```python
def count_tokens(text: str) -> int:
    """Count text tokens with the explicitly selected tokenizer."""
```

This is a proposed signature, not implemented code. Configure the tokenizer
explicitly when creating the helper or adapter. Expose its identity alongside
the helper so the evaluation runner can save it with every result. Do not
silently select a default model or change tokenizer between the two counts.
The proposed location and owner must be agreed with the shared LLM work.

Count plain payload text, without adding prompt wrappers or special tokens.
This convention needs team confirmation, including treatment of strings that
look like special tokens. Full request usage is a separate measurement and can
include messages, tools, and provider formatting.

One tokenizer's count is exact only for the selected encoding and counting
rules. It is not exact for every model. If several models are evaluated, use
each model's confirmed tokenizer mapping or label the count as an estimate.
Payload counts alone must not be presented as billed API usage or cost savings.

## Exact measurement inputs

The proposed evaluation runner should use the same validated batch and actual
compressor output:

```python
baseline = json.dumps(batch.records, ensure_ascii=False)
result = compress(batch)
baseline_tokens = count_tokens(baseline)
tsv_tokens = count_tokens(result.content)
```

Count the exact baseline string above, including its default JSON spaces,
key order, and Unicode handling. Do not count the fixture file, the entire
batch model, pretty JSON, or a second serialization with different settings.
Count the final TSV content exactly as returned, including its header, JSON
cell values, CSV quoting, tabs, and CRLF line endings. Do not trim or normalize
it. If saved text is read back, preserve line endings or decode saved bytes.

For each measured result, record:

- Input identity and hash, source commit, and whether source files had changes.
- Exact baseline and final payload artifacts or hashes, serialization rules,
  and separate UTF-8 byte counts.
- Both token counts and the tokenizer package name and exact version,
  encoding name, vocabulary revision or hash where available, model mapping,
  and special-token rules. Record any model identity as pending if unknown;
  do not invent one or claim that an unmapped encoding is model-exact.
- Measurement date, command, environment, and counting latency.

Proposed reporting: output/input token ratio and
`(input_tokens - output_tokens) / input_tokens` for token reduction.
When the baseline token count is zero, report ratios as undefined.
Keep negative savings and larger outputs visible. No target is approved.

## Dependency agreement

Accurate model-specific counting needs access to that model's tokenizer.
A new package may be needed once the choice is made. Do not substitute a
byte-based estimate and call it an exact token count.
[CONTRIBUTING.md](../../CONTRIBUTING.md) requires team agreement before
adding any dependency and an exact version pin in `pyproject.toml`.
No package or version is proposed as approved here. Shared contracts do not
need to change for this local measurement proposal.

## Questions before implementation

1. Which provider and model identities are used for development and evaluation?
2. Which tokenizer and encoding match each model? Which package, exact version,
   and vocabulary revision does the team approve?
3. Are we measuring payload text only? What are the agreed special-token rules,
   and how will full request usage be measured separately if needed?
4. Where should the helper live, who owns it, and how is tokenizer selection
   passed to the evaluation runner? What behaviour is agreed for an unavailable
   tokenizer or unknown model mapping? No fallback policy is introduced here.
5. M1 accepts the current JSON-encoded TSV rules with one shared header.
   All records and fields must remain unchanged, including duplicates and order.
   Does the team approve the proposed baseline comparison for token evaluation?
6. Which data, repeat counts, metrics, and acceptance criteria define W2-08?
   Is there an agreed token budget or target? None is assumed here.

## Proposed meaningful tests

- After approval, check a few independently verified token ID sequences for
  the pinned tokenizer, covering ordinary text and Unicode. Check empty text
  under the agreed plain-text rules and repeatability for identical input.
- Use a recording fake counter to prove the evaluation runner passes the
  exact JSON baseline and final TSV, without whitespace or newline changes.
  Include quoted cells, Unicode, and empty records. This tests measurement
  inputs rather than repeating the existing TSV round-trip tests.
- Check that both counts use the same tokenizer identity and that every saved
  result contains the required tokenizer metadata.
- Check zero-baseline reporting and negative savings without division errors
  or hidden results. Do not assert TSV always uses fewer tokens.
- Test the agreed unavailable-tokenizer and unknown-mapping behaviour after
  the team decides it. Do not invent new error rules in advance.

## Sample evaluation plan

1. Confirm the decisions above before installing or implementing anything.
2. Start with `data/fixtures/telemetry_sample.json` as a smoke test. Add agreed
   cases for nested records, duplicates, Unicode, sparse fields, empty records,
   and larger mixed telemetry. The hand-written fixture is not a benchmark.
3. Validate each batch, keep it unchanged, call the actual compressor, and count
   the exact two payloads with the same approved tokenizer. Check preservation
   using the existing tests before interpreting savings.
4. Save a new dated folder under `experiments/` with config, payload artifacts,
   per-sample counts, tokenizer identity, and notes. Preserve historical results.
5. Report per-sample bytes and tokens separately, including cases where TSV
   grows. For a summary, state the aggregation rule; a total output/input ratio
   differs from an average of individual ratios. Repeat timing runs only under
   the agreed evaluation rules.
6. For multiple approved tokenizers, report separate results for each. Do not
   transfer one tokenizer's savings to another model or infer API cost savings.
   Review results against the agreed acceptance criteria before any completion
   decision. This proposal does not mark W2-08 complete.

AI assistance: Codex read the repository instructions, F1 spec, dependency
file, compressor, and recorded model decisions, then drafted this proposal.
The original proposal changed no packages, application code, shared contracts,
or dependencies. The later contract integration updates M4 code and tests,
with no new dependencies or changes to historical experiment evidence.
