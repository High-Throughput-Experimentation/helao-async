"""Unit tests for helao.framework.models.active_params.ActiveParams model."""

from uuid import UUID
from helao.framework.models.active_params import ActiveParams
from helao.framework.models.file import FileConnParams
from helao.framework.models.action import ActionModel


def test_active_params_construction():
    """Test that ActiveParams can be constructed from a representative kwargs dict."""
    # Create a minimal ActionModel for testing
    action = ActionModel(
        action_name="test_action",
    )

    # Create FileConnParams for the test
    file_uuid = UUID('12345678-1234-5678-1234-567812345678')
    file_conn = FileConnParams(
        file_conn_key=file_uuid,
        file_type="hlo",
    )

    # Construct ActiveParams
    aux_uuid = UUID('87654321-4321-8765-4321-876543218765')
    params = ActiveParams(
        action=action,
        file_conn_params_dict={file_uuid: file_conn},
        aux_listen_uuids=[aux_uuid],
    )

    # Assert fields round-trip
    assert params.action.action_name == "test_action"
    assert file_uuid in params.file_conn_params_dict
    assert params.file_conn_params_dict[file_uuid].file_type == "hlo"
    assert aux_uuid in params.aux_listen_uuids


def test_active_params_as_dict():
    """Test that ActiveParams.as_dict() works (from HelaoDict)."""
    action = ActionModel(
        action_name="test_action",
        server_key="test_server",
    )

    file_uuid = UUID('12345678-1234-5678-1234-567812345678')
    file_conn = FileConnParams(
        file_conn_key=file_uuid,
        file_type="hlo",
    )

    aux_uuid = UUID('87654321-4321-8765-4321-876543218765')
    params = ActiveParams(
        action=action,
        file_conn_params_dict={file_uuid: file_conn},
        aux_listen_uuids=[aux_uuid],
    )

    # as_dict should return a serializable dict
    d = params.as_dict()
    assert isinstance(d, dict)
    assert "action" in d
    assert "file_conn_params_dict" in d
    assert "aux_listen_uuids" in d
