from app.dify_client import DifyWorkflowClient, build_dify_client_from_env
from app.models import JobStatus


def test_dify_workflow_client_parses_success_result() -> None:
    client = DifyWorkflowClient(base_url="https://dify.local", api_key="test")
    result = client._parse_generation_result(
        "AI_TEST",
        {
            "data": {
                "outputs": {
                    "result": {
                        "status": "success",
                        "internal_api_cost": 0.88,
                        "images": [
                            {
                                "slot": "main",
                                "title": "Selected",
                                "direction": "female",
                                "style_id": "style_010",
                                "style_name": "Medium Hair",
                                "color_id": "color_003",
                                "color_name": "Cool Brown",
                                "temp_image_url": "https://temp.local/main.jpg",
                            },
                            {
                                "slot": "natural",
                                "title": "Natural",
                                "direction": "female",
                                "style_id": "style_011",
                                "style_name": "Short Hair",
                                "color_id": "color_003",
                                "color_name": "Cool Brown",
                                "temp_image_url": "https://temp.local/natural.jpg",
                            },
                            {
                                "slot": "advanced",
                                "title": "Advanced",
                                "direction": "female",
                                "style_id": "style_010",
                                "style_name": "Medium Hair",
                                "color_id": "color_004",
                                "color_name": "Black Tea Brown",
                                "temp_image_url": "https://temp.local/advanced.jpg",
                            },
                        ],
                    }
                }
            }
        },
    )

    assert result.status == JobStatus.SUCCESS
    assert len(result.images) == 3
    assert result.internal_api_cost == 0.88


def test_dify_workflow_client_parses_invalid_json_result_as_failure() -> None:
    client = DifyWorkflowClient(base_url="https://dify.local", api_key="test")
    result = client._parse_generation_result(
        "AI_TEST",
        {"data": {"outputs": {"result": "{not-json"}}},
    )

    assert result.status == JobStatus.FAILED
    assert result.error_code == "DIFY_RESULT_INVALID_JSON"


def test_dify_workflow_client_parses_failed_result() -> None:
    client = DifyWorkflowClient(base_url="https://dify.local", api_key="test")
    result = client._parse_generation_result(
        "AI_TEST",
        {
            "data": {
                "outputs": {
                    "result": {
                        "status": "failed",
                        "internal_api_cost": 0.12,
                        "error_code": "IMAGE_GENERATION_FAILED",
                        "error_message": "model failed",
                    }
                }
            }
        },
    )

    assert result.status == JobStatus.FAILED
    assert result.internal_api_cost == 0.12
    assert result.error_code == "IMAGE_GENERATION_FAILED"


def test_dify_workflow_client_accepts_main_image_when_recommendations_fail() -> None:
    client = DifyWorkflowClient(base_url="https://dify.local", api_key="test")
    result = client._parse_generation_result(
        "AI_TEST",
        {
            "data": {
                "outputs": {
                    "result": {
                        "status": "success",
                        "internal_api_cost": 0.66,
                        "images": [
                            {
                                "slot": "main",
                                "temp_image_url": "https://temp.local/main.jpg",
                            }
                        ],
                    }
                }
            }
        },
    )

    assert result.status == JobStatus.SUCCESS
    assert len(result.images) == 1
    assert result.images[0].slot == "main"
    assert result.internal_api_cost == 0.66


def test_dify_workflow_client_rejects_wrong_image_slots() -> None:
    client = DifyWorkflowClient(base_url="https://dify.local", api_key="test")
    result = client._parse_generation_result(
        "AI_TEST",
        {
            "data": {
                "outputs": {
                    "result": {
                        "status": "success",
                        "images": [
                            {"slot": "main", "temp_image_url": "https://temp.local/main.jpg"},
                            {"slot": "advanced", "temp_image_url": "https://temp.local/advanced.jpg"},
                            {"slot": "natural", "temp_image_url": "https://temp.local/natural.jpg"},
                        ],
                    }
                }
            }
        },
    )

    assert result.status == JobStatus.FAILED
    assert result.error_code == "DIFY_RESULT_INVALID_SCHEMA"


def test_dify_workflow_client_rejects_missing_temp_image_url() -> None:
    client = DifyWorkflowClient(base_url="https://dify.local", api_key="test")
    result = client._parse_generation_result(
        "AI_TEST",
        {
            "data": {
                "outputs": {
                    "result": {
                        "status": "success",
                        "images": [
                            {"slot": "main", "temp_image_url": "https://temp.local/main.jpg"},
                            {"slot": "natural", "temp_image_url": ""},
                            {"slot": "advanced", "temp_image_url": "https://temp.local/advanced.jpg"},
                        ],
                    }
                }
            }
        },
    )

    assert result.status == JobStatus.FAILED
    assert result.error_code == "DIFY_RESULT_INVALID_SCHEMA"


def test_build_dify_client_uses_timeout_from_env(monkeypatch) -> None:
    monkeypatch.setenv("DIFY_BASE_URL", "https://dify.local")
    monkeypatch.setenv("DIFY_API_KEY", "test")
    monkeypatch.setenv("DIFY_TIMEOUT_SECONDS", "90")

    client = build_dify_client_from_env()

    assert isinstance(client, DifyWorkflowClient)
    assert client.timeout_seconds == 90
