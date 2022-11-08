""" General calculation server

Calc server is used for in-sequence data processing. 

"""

__all__ = ["makeApp"]

import json
from typing import Optional
from fastapi import Body

from helaocore.models.file import HloHeaderModel, HloFileGroup
from helao.helpers.premodels import Action
from helao.servers.base import makeActionServ
from helao.drivers.data.calc_driver import Calc
from helao.helpers.config_loader import config_loader


def makeApp(confPrefix, servKey, helao_root):
    config = config_loader(confPrefix, helao_root)
    app = makeActionServ(
        config=config,
        server_key=servKey,
        server_title=servKey,
        description="Calculation server",
        version=0.1,
        driver_class=Calc,
    )

    @app.post(f"/{servKey}/calc_uvis_abs")
    async def calc_uvis_abs(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        ev_parts: list = [1.5, 2.0, 2.5, 3.0],
        bin_width: int = 3,
        window_length: int = 45,
        poly_order: int = 4,
        lower_wl: float = 370,
        upper_wl: float = 1020,
        max_mthd_allowed: float = 1.2,
        max_limit: float = 0.99,
        min_mthd_allowed: float = -0.2,
        min_limit: float = 0.01,
        delta: float = 1.0,
    ):
        active = await app.base.setup_and_contain_action(action_abbr="calcAbs")
        datadict, arraydict = app.driver.calc_uvis_abs(active)
        await active.enqueue_data_dflt(datadict=datadict)
        for k, ad in arraydict.items():
            # convert ad to strings
            datalist = ad["data"]
            smplabs = ad["sample_label"]
            uuidlst = ad["action_uuids"]
            fulllst = [smplabs, uuidlst] + datalist
            jsondata = json.dumps(fulllst)
            header = HloHeaderModel(
                action_name=active.action.action_name,
                column_headings=["sample_label", "action_uuid"]
                + [str(i) for i in range(len(datalist))],
                optional={"wl": ad["wavelength"]},
                epoch_ns=app.base.get_realtime_nowait(),
            )
            abbr = active.action.action_abbr
            subi = active.action.orch_submit_order
            acti = active.action.action_order
            retry = active.action.action_retry
            split = active.action.action_split
            suffix = f"{k}.hlo"
            await active.write_file(
                output_str=jsondata,
                file_type="helao_calc__file",
                filename=f"{abbr}.{subi}.{acti}.{retry}.{split}__{suffix}",
                file_group=HloFileGroup.helao_files,
                header=header.clean_dict(),
                file_sample_label=ad["sample_label"],
                json_data_keys=list(ad.keys()),
                action=active.action,
            )
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
