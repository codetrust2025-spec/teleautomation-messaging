"""Which lane a Marketing change takes, driven through the real script.

The pin lane exists because a release pin changes two files by one line each and
leaves every Marketing input identical. Answering `pin` lets the workflow skip
Marketing's own suite, image build and container checks.

The half that matters is the second class: anything that is not exactly that
shape must keep the full pipeline, because the pin lane's whole argument is
"nothing in Marketing changed".
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pin_lane.sh"

COMPOSE = "docker-compose.production.yml"
CONTRACT = "tests/test_production_compose_contract.py"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash is required to run the lane script"
)


def lane(*paths: str) -> str:
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        input="\n".join(paths),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


class TestARealPinIsRecognised:
    def test_the_two_files_a_pin_touches(self) -> None:
        assert lane(COMPOSE, CONTRACT) == "pin"

    def test_order_does_not_matter(self) -> None:
        assert lane(CONTRACT, COMPOSE) == "pin"


class TestAnythingElseKeepsTheFullPipeline:
    @pytest.mark.parametrize(
        "path,why",
        [
            ("main.py", "Marketing backend"),
            ("messaging/telegram_client.py", "Marketing runtime"),
            ("dashboard/src/App.jsx", "Marketing dashboard"),
            ("requirements.txt", "dependencies"),
            ("Dockerfile", "image"),
            ("docker-compose.yml", "local infrastructure"),
            ("docker-compose.staging.yml", "staging topology"),
            ("docker-compose.dual.yml", "cross-service topology"),
            ("nginx/production.conf.template", "reverse proxy"),
            ("scripts/fix_and_deploy.sh", "the deploy script"),
            ("scripts/pin_lane.sh", "the lane rule itself"),
            (".github/workflows/ci.yml", "the pipeline itself"),
        ],
    )
    def test_it_takes_the_full_lane(self, path: str, why: str) -> None:
        assert lane(path) == "full", why

    def test_a_pin_carrying_one_extra_file_is_not_a_pin(self) -> None:
        """The extra file is the whole risk: it makes 'nothing in Marketing
        changed' false while the diff still looks like a pin."""
        assert lane(COMPOSE, CONTRACT, "main.py") == "full"

    def test_a_pin_carrying_a_compose_change_elsewhere_is_not_a_pin(self) -> None:
        assert lane(COMPOSE, CONTRACT, "docker-compose.staging.yml") == "full"

    @pytest.mark.parametrize("path", [COMPOSE, CONTRACT])
    def test_moving_only_one_of_the_pair_is_not_a_pin(self, path: str) -> None:
        """Anchor and contract test move in the same commit by design. One
        without the other is not the shape fix_and_deploy.sh produces, and could
        pin a build to a commit the contract still expects to be the previous
        one."""
        assert lane(path) == "full"


class TestItFailsSafe:
    def test_no_paths_means_full(self) -> None:
        assert lane() == "full"

    def test_blank_input_means_full(self) -> None:
        assert lane("", "  ") == "full"

    def test_a_disqualifying_last_path_is_not_dropped(self) -> None:
        """Input arrives here without a trailing newline. A `read` loop that
        does not allow for that silently loses the final entry, which is the
        one place a lost path grants the fast lane instead of denying it."""
        assert lane(COMPOSE, CONTRACT, "core/migrations/030_x.sql") == "full"

    @pytest.mark.parametrize(
        "path",
        [
            "x/docker-compose.production.yml",
            "docker-compose.production.yml.bak",
            "tests/test_production_compose_contract.py.orig",
        ],
    )
    def test_matching_is_exact_not_substring(self, path: str) -> None:
        assert lane(path) == "full"
