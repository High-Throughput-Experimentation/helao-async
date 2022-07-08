__all__ = ["unpack_samples_helper"]

from typing import List, Tuple

from helaocore.models.sample import (
                            SampleUnion,
                            SampleType
                           )

def unpack_samples_helper(samples: List[SampleUnion] = []) -> Tuple[List[SampleUnion],List[SampleUnion]]:
    liquid_list = []
    solid_list = []
    gas_list = []
    # assembly_list = []

    for sample in samples:
        if sample.sample_type == SampleType.assembly:
            for part in sample.parts:
                if part.sample_type == SampleType.assembly:
                    # recursive unpacking
                    tmp_liquid_list, tmp_solid_list, tmp_gas_list = \
                        unpack_samples_helper(samples = [part])
                    for s in tmp_liquid_list:
                        liquid_list.append(s)
                    for s in tmp_gas_list:
                        gas_list.append(s)
                    for s in tmp_solid_list:
                        solid_list.append(s)
                elif part.sample_type == SampleType.solid:
                    solid_list.append(part)
                elif part.sample_type == SampleType.liquid:
                    liquid_list.append(part)
                elif part.sample_type == SampleType.gas:
                    gas_list.append(part)

        elif sample.sample_type == SampleType.solid:
            solid_list.append(sample)
        elif sample.sample_type == SampleType.liquid:
            liquid_list.append(sample)
        elif sample.sample_type == SampleType.gas:
            gas_list.append(sample)

    return liquid_list, solid_list, gas_list
