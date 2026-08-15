from app.ai.input import AI_VIEW_VERSION as INPUT_VERSION
from app.ai.versions import AI_VIEW_VERSION
from app.ai.view import AI_VIEW_VERSION as VIEW_VERSION


def test_ai_view_version_has_one_source_of_truth() -> None:
    assert INPUT_VERSION == VIEW_VERSION == AI_VIEW_VERSION == "ai-view-v6"
