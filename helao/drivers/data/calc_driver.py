import os
import numpy as np
import pandas as pd


from helaocore.error import ErrorCodes
from helaocore.models.data import DataModel
from helaocore.models.file import FileConnParams, HloHeaderModel
from helaocore.models.sample import SampleInheritance, SampleStatus
from helaocore.models.hlostatus import HloStatus
from helao.helpers.premodels import Action
from helao.helpers.active_params import ActiveParams
from helao.helpers.sample_api import UnifiedSampleDataAPI
from helao.servers.base import Base


class Calc:
    """_summary_"""

    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        pass