"""Krypton emission lines for wavelength calibration, from NIST.

Source: NIST Physical Reference Data, *Strong Lines of Krypton (Kr)*,
https://physics.nist.gov/PhysRefData/Handbook/Tables/kryptontable2_a.htm
retrieved 2026-09-07. Values are transcribed programmatically from that
table's **Air** section, never by hand -- a mistyped line position would bend
a fitted axis by exactly the amount of the typo, silently.

**These are AIR wavelengths.** The NIST table splits at ~2000 A: below it the
values are vacuum, above it air. Everything here is from the air section, so a
calibration fitted against them yields an air-wavelength axis. Do not mix
these with a vacuum line list.

Angstroms in the table, nanometres here (a factor of 10), because every other
wavelength in this codebase is nm.

Culled to **427-893 nm**, the specified output range of the Ocean Insight KR-2
krypton lamp this station calibrates against. The full table runs to 40685 A;
a silicon detector is blind past ~1100 nm, so the infrared lines could never
appear and would only offer false matches to the line matcher.

Both Kr I and Kr II are kept. Which species a lamp shows depends on its
discharge conditions, and the four strongest lines in this window are split
between them -- Kr II at 435.5477 and 473.9002 nm, Kr I at 811.29012 and
877.67505 nm, all relative intensity 1000.

Relative intensities are the table's own. They are for SELECTING which lines
a given exposure can be expected to show; they are not fit weights. Canonical
practice weights a wavelength solution by centroid uncertainty, not by
brightness -- a bright line may well be saturated, and a saturated line has a
flat top and a poor centroid.
"""

from typing import Final

#: ``(wavelength_nm_air, relative_intensity, species)``, ascending.
KR_LINES_AIR_NM: Final[list[tuple[float, int, str]]] = [
    (427.396940, 150, "Kr I"),  # 4273.9694 A
    (428.296740, 15, "Kr I"),  # 4282.9674 A
    (429.292300, 200, "Kr II"),  # 4292.9230 A
    (430.049000, 70, "Kr II"),  # 4300.4900 A
    (431.781000, 150, "Kr II"),  # 4317.8100 A
    (431.855130, 70, "Kr I"),  # 4318.5513 A
    (431.957940, 150, "Kr I"),  # 4319.5794 A
    (432.298000, 50, "Kr II"),  # 4322.9800 A
    (435.135970, 15, "Kr I"),  # 4351.3597 A
    (435.547700, 1000, "Kr II"),  # 4355.4770 A
    (436.264160, 80, "Kr I"),  # 4362.6416 A
    (436.969000, 70, "Kr II"),  # 4369.6900 A
    (437.612160, 130, "Kr I"),  # 4376.1216 A
    (438.654000, 100, "Kr II"),  # 4386.5400 A
    (439.996630, 30, "Kr I"),  # 4399.9663 A
    (442.519010, 15, "Kr I"),  # 4425.1901 A
    (443.168500, 150, "Kr II"),  # 4431.6850 A
    (443.681200, 200, "Kr II"),  # 4436.8120 A
    (445.391750, 100, "Kr I"),  # 4453.9175 A
    (446.369000, 130, "Kr I"),  # 4463.6900 A
    (447.501400, 250, "Kr II"),  # 4475.0140 A
    (448.988000, 130, "Kr II"),  # 4489.8800 A
    (450.235430, 100, "Kr I"),  # 4502.3543 A
    (452.314000, 130, "Kr II"),  # 4523.1400 A
    (455.661000, 70, "Kr II"),  # 4556.6100 A
    (457.720900, 250, "Kr II"),  # 4577.2090 A
    (458.297800, 100, "Kr II"),  # 4582.9780 A
    (459.280000, 50, "Kr II"),  # 4592.8000 A
    (461.529200, 150, "Kr II"),  # 4615.2920 A
    (461.916600, 300, "Kr II"),  # 4619.1660 A
    (463.388500, 250, "Kr II"),  # 4633.8850 A
    (465.887600, 700, "Kr II"),  # 4658.8760 A
    (468.040600, 150, "Kr II"),  # 4680.4060 A
    (469.130100, 30, "Kr II"),  # 4691.3010 A
    (469.436000, 70, "Kr II"),  # 4694.3600 A
    (473.900200, 1000, "Kr II"),  # 4739.0020 A
    (476.243500, 100, "Kr II"),  # 4762.4350 A
    (476.574400, 300, "Kr II"),  # 4765.7440 A
    (481.176000, 100, "Kr II"),  # 4811.7600 A
    (482.518000, 100, "Kr II"),  # 4825.1800 A
    (483.207700, 250, "Kr II"),  # 4832.0770 A
    (484.661200, 250, "Kr II"),  # 4846.6120 A
    (485.720000, 50, "Kr II"),  # 4857.2000 A
    (494.559000, 100, "Kr II"),  # 4945.5900 A
    (502.240000, 70, "Kr II"),  # 5022.4000 A
    (508.652000, 80, "Kr II"),  # 5086.5200 A
    (512.573000, 130, "Kr II"),  # 5125.7300 A
    (520.832000, 150, "Kr II"),  # 5208.3200 A
    (530.866000, 70, "Kr II"),  # 5308.6600 A
    (533.341000, 150, "Kr II"),  # 5333.4100 A
    (546.817000, 70, "Kr II"),  # 5468.1700 A
    (556.222530, 80, "Kr I"),  # 5562.2253 A
    (557.028940, 300, "Kr I"),  # 5570.2894 A
    (558.038730, 13, "Kr I"),  # 5580.3873 A
    (564.956180, 15, "Kr I"),  # 5649.5618 A
    (568.189000, 130, "Kr II"),  # 5681.8900 A
    (569.035000, 70, "Kr II"),  # 5690.3500 A
    (583.285660, 15, "Kr I"),  # 5832.8566 A
    (587.091600, 500, "Kr I"),  # 5870.9160 A
    (599.222000, 70, "Kr II"),  # 5992.2200 A
    (599.385020, 10, "Kr I"),  # 5993.8502 A
    (605.612630, 10, "Kr I"),  # 6056.1263 A
    (642.018000, 100, "Kr II"),  # 6420.1800 A
    (642.102700, 15, "Kr I"),  # 6421.0270 A
    (645.628890, 30, "Kr I"),  # 6456.2889 A
    (657.007000, 50, "Kr II"),  # 6570.0700 A
    (669.922960, 10, "Kr I"),  # 6699.2296 A
    (690.467880, 15, "Kr I"),  # 6904.6788 A
    (721.313000, 80, "Kr II"),  # 7213.1300 A
    (722.410400, 15, "Kr I"),  # 7224.1040 A
    (728.725800, 13, "Kr I"),  # 7287.2580 A
    (728.978000, 130, "Kr II"),  # 7289.7800 A
    (740.702000, 130, "Kr II"),  # 7407.0200 A
    (742.554100, 10, "Kr I"),  # 7425.5410 A
    (743.578000, 70, "Kr II"),  # 7435.7800 A
    (748.686200, 15, "Kr I"),  # 7486.8620 A
    (752.446000, 100, "Kr II"),  # 7524.4600 A
    (758.741360, 150, "Kr I"),  # 7587.4136 A
    (760.154570, 300, "Kr I"),  # 7601.5457 A
    (764.116000, 50, "Kr II"),  # 7641.1600 A
    (768.524590, 150, "Kr I"),  # 7685.2459 A
    (769.454010, 200, "Kr I"),  # 7694.5401 A
    (773.569000, 80, "Kr II"),  # 7735.6900 A
    (774.682700, 25, "Kr I"),  # 7746.8270 A
    (785.482340, 130, "Kr I"),  # 7854.8234 A
    (791.342510, 30, "Kr I"),  # 7913.4251 A
    (792.859880, 30, "Kr I"),  # 7928.5988 A
    (793.322000, 70, "Kr II"),  # 7933.2200 A
    (797.362000, 40, "Kr II"),  # 7973.6200 A
    (798.240100, 15, "Kr I"),  # 7982.4010 A
    (805.950480, 250, "Kr I"),  # 8059.5048 A
    (810.436550, 700, "Kr I"),  # 8104.3655 A
    (811.290120, 1000, "Kr I"),  # 8112.9012 A
    (813.296700, 10, "Kr I"),  # 8132.9670 A
    (819.005660, 500, "Kr I"),  # 8190.0566 A
    (820.272000, 70, "Kr II"),  # 8202.7200 A
    (821.836500, 13, "Kr I"),  # 8218.3650 A
    (826.324260, 500, "Kr I"),  # 8263.2426 A
    (827.235300, 15, "Kr I"),  # 8272.3530 A
    (828.105220, 250, "Kr I"),  # 8281.0522 A
    (829.810990, 800, "Kr I"),  # 8298.1099 A
    (841.243000, 15, "Kr I"),  # 8412.4300 A
    (850.887280, 500, "Kr I"),  # 8508.8728 A
    (876.411000, 25, "Kr I"),  # 8764.1100 A
    (877.675050, 1000, "Kr I"),  # 8776.7505 A
    (892.869340, 300, "Kr I"),  # 8928.6934 A
]

#: The lamp these were culled for.
LAMP_NAME: Final[str] = "Ocean Insight KR-2"
LAMP_RANGE_NM: Final[tuple[float, float]] = (427.0, 893.0)

#: The medium the wavelengths are referenced to. Recorded in every calibration
#: fitted against them so an axis can never be silently compared against a
#: vacuum-referenced one.
MEDIUM: Final[str] = "air"
