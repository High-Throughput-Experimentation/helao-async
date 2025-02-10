__all__ = ["unpack_samples_helper"]

from typing import List, Tuple

from helao.core.models.sample import (
                            SampleModel,
                            SampleType
                           )

def unpack_samples_helper(samples: List[SampleModel] = []) -> Tuple[List[SampleModel],List[SampleModel]]:
    """
    Unpacks a list of samples into separate lists based on their sample type.

    This function takes a list of samples, which can include nested assembly samples,
    and recursively unpacks them into separate lists for liquid, solid, and gas samples.

    Args:
        samples (List[SampleModel]): A list of samples to be unpacked. Each sample can be of type
                                        liquid, solid, gas, or assembly. Assembly samples can contain
                                        other samples, including nested assemblies.

    Returns:
        Tuple[List[SampleModel], List[SampleModel], List[SampleModel]]: A tuple containing three lists:
            - liquid_list: List of liquid samples.
            - solid_list: List of solid samples.
            - gas_list: List of gas samples.
    """
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
