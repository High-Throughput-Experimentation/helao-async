"""mask_secrets: credential-like keys masked at any depth, input untouched."""

import copy

from helao.ui.shared.mask import MASK, mask_secrets


def test_masks_nested_secret_keys_and_keeps_others():
    cfg = {
        "host": "h",
        "server_key": "SYNC",
        "params": {
            "aws_secret_access_key": "s3cr3t",
            "api_key": "k",
            "db": {"Password": "p", "user": "u"},
            "tokens": [{"refresh_token": "t"}],
        },
    }
    before = copy.deepcopy(cfg)
    out = mask_secrets(cfg)
    assert cfg == before
    assert out["host"] == "h" and out["server_key"] == "SYNC"
    assert out["params"]["aws_secret_access_key"] == MASK
    assert out["params"]["api_key"] == MASK
    assert out["params"]["db"] == {"Password": MASK, "user": "u"}
    # a list under a masked key name is masked whole
    assert out["params"]["tokens"] == MASK


def test_scalars_and_lists_pass_through():
    assert mask_secrets(3) == 3
    assert mask_secrets([{"credential": 1}, 2]) == [{"credential": MASK}, 2]
