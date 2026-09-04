from pathlib import Path


def test_sandbox_fresh_script_is_direct_and_resumable() -> None:
    text = Path("scripts/run_stage7h_sandbox_fresh.py").read_text(encoding="utf-8")
    assert "Temporary stage:  NONE" in text
    assert "UNPARTITIONED + CLUSTERED" in text
    assert "--reset" in text
    assert "_existing_valid_final" in text
    assert "load_table_from_file" in text
    assert "__stage7h_" not in text
    assert "STAGE_7H_SANDBOX_RAW_STATUS=PASS" in text
