"""The vis WS decoder reconstructs a typed DataPackageModel from a JSON frame.

Framework action servers relay ws_data as JSON (BaseAPI._ws_relay sends
DataPackageModel.as_dict()). The vis decoder must rebuild the model so the
(legacy-ported) vis code keeps object access AND a typed HloStatus — a plain
json.loads dict would leave status a str and never match VALID_DATA_STATUS.
"""
import json
from uuid import UUID

from helao.framework.adapters.vis_subscriber import _decode_data_package
from helao.framework.models.data import DataModel, DataPackageModel
from helao.framework.models.hlostatus import HloStatus


def test_decode_reconstructs_typed_data_package():
    conn = UUID("00000000-0000-0000-0000-0000000000ff")
    pkg = DataPackageModel(
        action_uuid=UUID("00000000-0000-0000-0000-0000000000aa"),
        action_name="acquire_data",
        datamodel=DataModel(
            data={conn: {"t_s": [0.0, 0.1], "Ewe_V": [0.5, 0.6]}},
            status=HloStatus.active,
        ),
    )
    # what BaseAPI._ws_relay send_json puts on the wire, received as JSON text
    raw = json.dumps(pkg.as_dict())

    decoded = _decode_data_package(raw)

    assert isinstance(decoded, DataPackageModel)
    assert decoded.action_name == "acquire_data"
    # typed status (enum), so `status in VALID_DATA_STATUS` (HloStatus members) matches
    assert decoded.datamodel.status is HloStatus.active
    # data survives with its per-connection payload (keys re-coerced to UUID)
    assert decoded.datamodel.data[conn]["t_s"] == [0.0, 0.1]
