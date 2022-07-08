from helaocore.models.sample import _BaseSample
from helao.helpers.print_message import print_message


def update_vol(BS: _BaseSample, delta_vol_ml: float, dilute: bool):
    """_summary_

    Args:
        BS (_BaseSample): _description_
        delta_vol_ml (float): _description_
        dilute (bool): _description_
    """
    if hasattr(BS, "volume_ml"):
        old_vol = BS.volume_ml
        tot_vol = old_vol + delta_vol_ml
        if tot_vol <= 0:
            print_message(
                {},
                "model",
                "new volume is <= 0, setting it to zero and setting status to destroyed",
                error=True,
            )
            BS.zero_volume()
            tot_vol = 0
        BS.volume_ml = tot_vol
        if dilute:
            if hasattr(BS, "dilution_factor"):
                old_df = BS.dilution_factor
                if old_vol <= 0:
                    print_message(
                        {}, "model", "previous volume is <= 0, setting new df to 0.", error=True
                    )
                    new_df = -1
                else:
                    new_df = tot_vol / (old_vol / old_df)
                BS.dilution_factor = new_df
                print_message(
                    {}, "model", f"updated sample dilution-factor: {BS.dilution_factor}", info=True
                )