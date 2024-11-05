from helaocore.models.sample import _BaseSample
from helao.helpers.print_message import print_message


def update_vol(BS: _BaseSample, delta_vol_ml: float, dilute: bool):
    """
    Updates the volume of a sample and optionally adjusts its dilution factor.

    Parameters:
    BS (_BaseSample): The sample object which contains volume and dilution factor attributes.
    delta_vol_ml (float): The change in volume to be applied to the sample, in milliliters.
    dilute (bool): A flag indicating whether to adjust the dilution factor based on the new volume.

    Behavior:
    - If the sample has a 'volume_ml' attribute, the volume is updated by adding 'delta_vol_ml'.
    - If the resulting total volume is less than or equal to zero, the volume is set to zero and the sample status is set to destroyed.
    - If 'dilute' is True and the sample has a 'dilution_factor' attribute, the dilution factor is recalculated based on the new volume.
    - Appropriate messages are printed to indicate changes and errors.

    Notes:
    - If the previous volume is less than or equal to zero, the new dilution factor is set to -1.
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