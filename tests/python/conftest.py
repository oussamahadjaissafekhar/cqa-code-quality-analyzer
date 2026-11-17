import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help="Rewrite golden fixtures (never enable this in CI).",
    )


@pytest.fixture()
def update_goldens(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--update-goldens"))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def sample_repo() -> Path:
    return FIXTURES / "repos" / "sample"


@pytest.fixture()
def frozen_clock() -> datetime:
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


@pytest.fixture()
def fallback_parser():
    from cqa.parsers.fallback_python import FallbackParser

    return FallbackParser()


@pytest.fixture()
def sample_result(sample_repo: Path, fallback_parser, frozen_clock):
    from cqa.app import AnalyzeOptions, run_analyze

    return run_analyze(
        AnalyzeOptions(
            path=str(sample_repo),
            fail_on="high",
            no_cache=True,
            clock=frozen_clock,
        ),
        parser=fallback_parser,
    )
