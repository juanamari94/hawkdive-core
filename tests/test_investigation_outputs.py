import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from hawkdive.investigations import Evidence, Finding, Observation, Outcome, WorkerInput, WorkerOutput


def test_evidence_has_a_text_explanation():
    evidence = Evidence(
        source='metrics', query='memory_usage',
        starts_at='2026-10-14T10:00:00Z', ends_at='2026-10-14T10:05:00Z',
        reasoning='Memory reached 512 MiB before the restart.', source_url='https://example.test/metrics',
    )
    assert evidence.reasoning == 'Memory reached 512 MiB before the restart.'


def test_worker_input_has_uuid_identity_and_a_typed_alert_trigger():
    investigation_id, attempt_id = uuid4(), uuid4()
    request = WorkerInput.model_validate_json(json.dumps({
        'investigation_id': str(investigation_id), 'attempt_id': str(attempt_id),
        'trigger': {'integration': 'grafana', 'occurrence_id': 1, 'reference': '/issues/1', 'alert': {}},
    }))
    assert request.investigation_id == investigation_id
    assert request.attempt_id == attempt_id
    assert request.trigger.occurrence_id == 1


def test_worker_output_does_not_require_or_accept_execution_identity():
    identifier, reference = uuid4(), uuid4()
    raw = {'id': str(identifier), 'kind': 'FINDING',
           'content': {'summary': 'Memory exhaustion occurred.', 'observation_ids': [str(reference)]}}
    output = WorkerOutput.model_validate_json(json.dumps(raw))
    assert output.id == identifier
    assert isinstance(output.content, Finding)
    assert output.content.observation_ids == [reference]
    with pytest.raises(ValidationError):
        WorkerOutput.model_validate_json(json.dumps({**raw, 'attempt_id': str(uuid4())}))


def test_output_kind_must_match_its_typed_content():
    with pytest.raises(ValidationError):
        WorkerOutput.model_validate_json(json.dumps({
            'id': str(uuid4()), 'kind': 'OUTCOME', 'content': {'summary': 'This is an observation.'},
        }))


def test_output_identifiers_must_be_uuids():
    with pytest.raises(ValidationError):
        WorkerOutput.model_validate_json(json.dumps({
            'id': 'not-a-uuid', 'kind': 'OBSERVATION', 'content': {'summary': 'Memory increased.'},
        }))


@pytest.mark.parametrize('model, values', [
    (Finding, {'summary': 'Unsupported finding', 'observation_ids': []}),
    (Outcome, {'conclusion': 'Unsupported conclusion', 'finding_ids': []}),
    (Observation, {'summary': '   '}),
])
def test_invalid_outputs_are_rejected_by_application_validation(model, values):
    with pytest.raises(ValidationError):
        model.model_validate(values)


def test_model_output_schemas_do_not_include_length_keywords():
    for model in (Evidence, Observation, Finding, Outcome, WorkerOutput):
        schema = json.dumps(model.model_json_schema())
        assert all(keyword not in schema for keyword in ('minLength', 'maxLength', 'minItems', 'maxItems'))
