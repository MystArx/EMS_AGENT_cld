import json
from pathlib import Path

def test_mdl_schema_generated():
    path = Path("data/schemas_from_mdl.json")
    assert path.exists()

    data = json.loads(path.read_text())
    assert "entities" in data
    assert len(data["entities"]) > 0
