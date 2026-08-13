from app.shadow_audit_snapshot import snapshot_quality


def test_shadow_snapshot_quality_empty() -> None:
    assert snapshot_quality([])["count"] == 0
