import uuid
from datetime import UTC, datetime

from app.processing.ledger import compute_ledger_hash
from app.schemas.ledger import LedgerStep


def _step(**overrides) -> LedgerStep:
    defaults = {
        "step_id": uuid.uuid4(),
        "type": "raman.snv",
        "version": "1.0.0",
        "params": {"ddof": 0},
        "order": 1,
        "applied_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return LedgerStep(**defaults)


def test_hash_stable_regardless_of_param_key_insertion_order():
    raw_file_id = uuid.uuid4()
    step_a = _step(params={"a": 1, "b": 2})
    step_b = _step(step_id=uuid.uuid4(), params={"b": 2, "a": 1})

    assert compute_ledger_hash(raw_file_id, 1, [step_a]) == compute_ledger_hash(
        raw_file_id, 1, [step_b]
    )


def test_hash_changes_when_params_value_changes():
    raw_file_id = uuid.uuid4()
    step_a = _step(params={"a": 1})
    step_b = _step(params={"a": 2})

    assert compute_ledger_hash(raw_file_id, 1, [step_a]) != compute_ledger_hash(
        raw_file_id, 1, [step_b]
    )


def test_hash_stable_when_only_step_id_or_applied_at_differ():
    raw_file_id = uuid.uuid4()
    step_a = _step()
    step_b = _step(
        step_id=uuid.uuid4(),
        applied_at=datetime(2020, 1, 1, tzinfo=UTC),
    )

    assert compute_ledger_hash(raw_file_id, 1, [step_a]) == compute_ledger_hash(
        raw_file_id, 1, [step_b]
    )


def test_hash_changes_when_raw_file_id_changes():
    step = _step()
    assert compute_ledger_hash(uuid.uuid4(), 1, [step]) != compute_ledger_hash(uuid.uuid4(), 1, [step])


def test_hash_stable_regardless_of_input_list_order_when_order_field_matches():
    raw_file_id = uuid.uuid4()
    step_1 = _step(order=1, type="raman.snv")
    step_2 = _step(order=2, type="raman.msc", params={"reference_source": {"type": "array", "values": [1]}})

    hash_forward = compute_ledger_hash(raw_file_id, 1, [step_1, step_2])
    hash_reversed = compute_ledger_hash(raw_file_id, 1, [step_2, step_1])

    assert hash_forward == hash_reversed
