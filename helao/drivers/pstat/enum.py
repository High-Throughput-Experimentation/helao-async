from enum import Enum


class Gamry_modes(str, Enum):
    CA = "CA"
    CP = "CP"
    CV = "CV"
    LSV = "LSV"
    EIS = "EIS"
    OCV = "OCV"
    PV = "PV"


# https://www.gamry.com/support/technical-support/frequently-asked-questions/fixed-vs-autoranging/
# class Gamry_IErange(str, Enum):
#     #NOTE: The ranges listed below are for 300 mA or 30 mA models. For 750 mA models, multiply the ranges by 2.5. For 600 mA models, multiply the ranges by 2.0.
#     auto = "auto"
#     mode0 = "3pA"
#     mode1 = "30pA"
#     mode2 = "300pA"
#     mode3 = "3nA"
#     mode4 = "30nA"
#     mode5 = "300nA"
#     mode6 = "3uA"
#     mode7 = "30uA"
#     mode8 = "300uA"
#     mode9 = "3mA"
#     mode10 = "30mA"
#     mode11 = "300mA"
#     mode12 = "3A"
#     mode13 = "30A"
#     mode14 = "300A"
#     mode15 = "3kA"


# for IFC1010
class Gamry_IErange_IFC1010(str, Enum):
    # NOTE: The ranges listed below are for 300 mA or 30 mA models. For 750 mA models, multiply the ranges by 2.5. For 600 mA models, multiply the ranges by 2.0.
    auto = "auto"
    # mode0 = "N/A"
    # mode1 = "N/A"
    # mode2 = "N/A"
    # mode3 = "N/A"
    mode4 = "10nA"
    mode5 = "100nA"
    mode6 = "1uA"
    mode7 = "10uA"
    mode8 = "100uA"
    mode9 = "1mA"
    mode10 = "10mA"
    mode11 = "100mA"
    mode12 = "1A"
    # mode13 = "N/A"
    # mode14 = "N/A"
    # mode15 = "N/A"


class Gamry_IErange_REF600(str, Enum):
    auto = "auto"
    # mode0 = "N/A"
    mode1 = "60pA"
    mode2 = "600pA"
    mode3 = "6nA"
    mode4 = "60nA"
    mode5 = "600nA"
    mode6 = "6uA"
    mode7 = "60uA"
    mode8 = "600uA"
    mode9 = "6mA"
    mode10 = "60mA"
    mode11 = "600mA"
    # mode12 = "N/A"
    # mode13 = "N/A"
    # mode14 = "N/A"
    # mode15 = "N/A"


# G750 is 7.5nA to 750mA
class Gamry_IErange_PCI4G300(str, Enum):
    auto = "auto"
    # mode0 = "N/A"
    # mode1 = "N/A"
    # mode2 = "N/A"
    mode3 = "3nA"
    mode4 = "30nA"
    mode5 = "300nA"
    mode6 = "3uA"
    mode7 = "30uA"
    mode8 = "300uA"
    mode9 = "3mA"
    mode10 = "30mA"
    mode11 = "300mA"
    # mode12 = "N/A"
    # mode13 = "N/A"
    # mode14 = "N/A"
    # mode15 = "N/A"


class Gamry_IErange_PCI4G750(str, Enum):
    auto = "auto"
    # mode0 = "N/A"
    # mode1 = "N/A"
    # mode2 = "N/A"
    mode3 = "7.5nA"
    mode4 = "75nA"
    mode5 = "750nA"
    mode6 = "7.5uA"
    mode7 = "75uA"
    mode8 = "750uA"
    mode9 = "7.5mA"
    mode10 = "75mA"
    mode11 = "750mA"
    # mode12 = "N/A"
    # mode13 = "N/A"
    # mode14 = "N/A"
    # mode15 = "N/A"


class Gamry_IErange_dflt(str, Enum):
    auto = "auto"
    mode0 = "mode0"
    mode1 = "mode1"
    mode2 = "mode2"
    mode3 = "mode3"
    mode4 = "mode4"
    mode5 = "mode5"
    mode6 = "mode6"
    mode7 = "mode7"
    mode8 = "mode8"
    mode9 = "mode9"
    mode10 = "mode10"
    mode11 = "mode11"
    mode12 = "mode12"
    mode13 = "mode13"
    mode14 = "mode14"
    mode15 = "mode15"
