from workflow_sample.processor import process_order


def test_process_order_returns_status():
    result = process_order(
        {
            "id": "ord_1",
            "payload": '{"campaign": "spring", "source": "email"}',
            "value": "101",
            "status": "pending",
            "data": {
                "attributes": {
                    "items": [
                        {"kind": "book", "quantity": 2, "price": 12, "region": "us"},
                    ]
                }
            },
        }
    )

    assert result["status"] == "review"
    assert result["payload_keys"] == ["campaign", "source"]


def test_process_order_ignores_invalid_payload_metadata():
    result = process_order(
        {
            "id": "ord_2",
            "payload": "{invalid",
            "value": "5",
            "status": "new",
            "data": {"attributes": {"items": []}},
        }
    )

    assert result["payload_keys"] == []
