import importlib

import main


def route_paths():
    return {route.path for route in main.app.routes}


def test_messaging_owns_core_routes():
    paths = route_paths()
    assert "/account/{slot}/start" in paths
    assert "/inbox/{slot}/messages/{user_id}" in paths
    assert "/crm/state" in paths
    assert "/internal/v1/notifications" in paths
    assert "/internal/v1/operational-summary" in paths


def test_business_implementations_are_not_present():
    for module in ("features.candidate_store", "features.data_room_store", "core.recruitment_mail_api"):
        try:
            importlib.import_module(module)
        except ModuleNotFoundError:
            continue
        raise AssertionError(f"Business module leaked into Messaging: {module}")


def test_legacy_business_bridge_is_registered():
    paths = route_paths()
    assert "/candidates/{legacy_path:path}" in paths
    assert "/data-room/{legacy_path:path}" in paths
    assert "/api/{legacy_path:path}" in paths


def test_operations_auth_routes_are_not_registered():
    paths = route_paths()
    assert "/auth/reset-password" not in paths
    assert "/auth/handler-kit" not in paths
