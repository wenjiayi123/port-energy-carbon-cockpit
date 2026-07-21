from fastapi import APIRouter

from app.rl.dataset import list_datasets

router = APIRouter(tags=["scenarios"])


@router.get("")
def list_scenarios() -> list[dict[str, object]]:
    return [
        {
            "id": item["id"],
            "name": item.get("metadata", {}).get("name", item["id"]),
            "description": item.get("metadata", {}).get("scope_note", "Dataset-backed offline benchmark"),
            "dataset_sha256": item.get("sha256"),
            "train_rows": item.get("train_rows"),
            "test_rows": item.get("test_rows"),
            "valid": item.get("valid", False),
        }
        for item in list_datasets()
    ]
