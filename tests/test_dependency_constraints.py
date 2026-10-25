from pathlib import Path


def test_runtime_security_dependency_floors_are_declared():
    requirements = Path(__file__).resolve().parents[1] / "requirements.txt"
    declared = set(requirements.read_text(encoding="utf-8").splitlines())

    assert "Django>=5.2.17,<5.3" in declared
    assert "djangorestframework>=3.17.2" in declared
    assert "sqlparse>=0.6.0" in declared
    assert "urllib3>=2.8.0" in declared
