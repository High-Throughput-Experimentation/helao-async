__all__ = ["sample_model_unit_test"]

import colorama
from colorama import Fore, Style
import sys
import traceback


from helao.core.models.sample import (
    LiquidSample,
    GasSample,
    SolidSample,
    AssemblySample,
    NoneSample,
    SampleList,
)

colorama.init(strip=not sys.stdout.isatty())  # strip colors if stdout is redirected


def sample_model_unit_test():
    success = True
    try:
        fail_msg = f"{Style.BRIGHT}{Fore.RED}failed:{Style.RESET_ALL}"
        passed_msg = f"{Style.BRIGHT}{Fore.GREEN}passed{Style.RESET_ALL}."
        testcounter = 1

        print("\x1b[2J")  # clear screen

        print(" --- testing single sample models ---")

        test_liquid = LiquidSample()
        test_gas = GasSample()
        test_solid = SolidSample()
        test_assembly = AssemblySample(parts=[NoneSample()])
        test_assembly2 = AssemblySample(
            parts=[test_gas, test_solid, test_liquid, test_assembly]
        )

        # testing some basic sampple functions
        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert test_liquid.sample_type == "liquid", fail_msg
            print(passed_msg)
        except AssertionError:
            print(fail_msg, "sample_type is not liquid.")
            success = False

        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert test_gas.sample_type == "gas", fail_msg
            print(passed_msg)
        except AssertionError:
            print(fail_msg, "sample_type is not gas.")
            success = False

        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert test_solid.sample_type == "solid", fail_msg
            print(passed_msg)
        except AssertionError:
            print(fail_msg, "sample_type is not solid.")
            success = False

        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert test_solid.machine_name == "legacy", fail_msg
            print(passed_msg)
        except AssertionError:
            print(fail_msg, "machine_name is not legacy.")
            success = False

        print(" --- testing sample assembly ---")

        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert test_assembly.sample_type == "assembly", fail_msg
            print(passed_msg)
        except AssertionError:
            print(fail_msg, "sample_type is not assembly.")
            success = False

        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert test_assembly2.sample_type == "assembly", fail_msg
            print(passed_msg)
        except AssertionError:
            print(fail_msg, "sample_type is not assembly.")
            success = False

        print(" --- testing sample list ---")

        try:
            print(f"sample_model test {testcounter} ", end="")
            test_sample_list = SampleList(
                samples=[
                    test_liquid,
                    test_gas,
                    test_solid,
                    test_assembly,
                    test_assembly2,
                ]
            )
            print(passed_msg)
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            print(fail_msg, "cannot convert list of model dicts to model list")
            print(
                repr(e),
                tb,
            )
            return False

        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert test_sample_list.samples[0].sample_type == "liquid", fail_msg
            print(passed_msg)
        except AssertionError:
            print(fail_msg, "sample_type is not liquid.")
            success = False

        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert test_sample_list.samples[1].sample_type == "gas", fail_msg
            print(passed_msg)
        except AssertionError:
            print(fail_msg, "sample_type is not gas.")
            success = False

        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert test_sample_list.samples[2].sample_type == "solid", fail_msg
            print(passed_msg)
        except AssertionError:
            print(fail_msg, "sample_type is not solid.")
            success = False

        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert test_sample_list.samples[2].machine_name == "legacy", fail_msg
            print(passed_msg)
        except AssertionError:
            print(fail_msg, "machine_name is not legacy.")
            success = False

        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert test_sample_list.samples[3].sample_type == "assembly", fail_msg
            print(passed_msg)
        except AssertionError:
            print(fail_msg, "sample_type is not assembly.")
            success = False

        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert type(test_sample_list.samples[0]) == type(test_liquid), fail_msg
            print(passed_msg)
            # print(type(test_sample_list.samples[0]))
        except AssertionError:
            print(fail_msg, "sample_type is not liquid.")
            print(type(test_sample_list.samples[0]))
            success = False

        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert type(test_sample_list.samples[1]) == type(test_gas), fail_msg
            print(passed_msg)
        except AssertionError:
            print(fail_msg, "sample_type is not gas.")
            print(type(test_sample_list.samples[1]))
            success = False

        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert type(test_sample_list.samples[2]) == type(test_solid), fail_msg
            print(passed_msg)
            # print(type(test_sample_list.samples[2]))
        except AssertionError:
            print(fail_msg, "sample_type is not solid.")
            print(type(test_sample_list.samples[2]))
            success = False

        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert type(test_sample_list.samples[3]) == type(test_assembly), fail_msg
            print(passed_msg)
            # print(type(test_sample_list.samples[2]))
        except AssertionError:
            print(fail_msg, "sample_type is not solid.")
            print(type(test_sample_list.samples[3]))
            success = False

        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert type(test_sample_list.samples[4]) == type(test_assembly2), fail_msg
            print(passed_msg)
            # print(type(test_sample_list.samples[2]))
        except AssertionError:
            print(fail_msg, "sample_type is not solid.")
            print(type(test_sample_list.samples[4]))
            success = False

        print(" --- testing sample list when converted from dict---")
        # testing sample list basemodel functions
        try:
            print(f"sample_model test {testcounter} ", end="")
            test_sample_list = SampleList(
                samples=[
                    test_liquid.model_dump(),
                    test_gas.model_dump(),
                    test_solid.model_dump(),
                    test_assembly.model_dump(),
                    test_assembly2.model_dump(),
                ]
            )
            print(passed_msg)
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            print(fail_msg, "cannot convert list of model dicts to model list")
            print(
                repr(e),
                tb,
            )
            return False

        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert test_sample_list.samples[0].sample_type == "liquid", fail_msg
            print(passed_msg)
        except AssertionError:
            print(fail_msg, "sample_type is not liquid.")
            success = False

        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert test_sample_list.samples[1].sample_type == "gas", fail_msg
            print(passed_msg)
        except AssertionError:
            print(fail_msg, "sample_type is not gas.")
            success = False

        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert test_sample_list.samples[2].sample_type == "solid", fail_msg
            print(passed_msg)
        except AssertionError:
            print(fail_msg, "sample_type is not solid.")
            success = False

        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert test_sample_list.samples[2].machine_name == "legacy", fail_msg
            print(passed_msg)
        except AssertionError:
            print(fail_msg, "machine_name is not legacy.")
            success = False

        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert test_sample_list.samples[3].sample_type == "assembly", fail_msg
            print(passed_msg)
        except AssertionError:
            print(fail_msg, "sample_type is not assembly.")
            success = False

        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert type(test_sample_list.samples[0]) == type(test_liquid), fail_msg
            print(passed_msg)
            # print(type(test_sample_list.samples[0]))
        except AssertionError:
            print(fail_msg, "sample_type is not liquid.")
            print(type(test_sample_list.samples[0]))
            success = False

        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert type(test_sample_list.samples[1]) == type(test_gas), fail_msg
            print(passed_msg)
        except AssertionError:
            print(fail_msg, "sample_type is not gas.")
            print(type(test_sample_list.samples[1]))
            success = False

        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert type(test_sample_list.samples[2]) == type(test_solid), fail_msg
            print(passed_msg)
            # print(type(test_sample_list.samples[2]))
        except AssertionError:
            print(fail_msg, "sample_type is not solid.")
            print(type(test_sample_list.samples[2]))
            success = False

        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert type(test_sample_list.samples[3]) == type(test_assembly), fail_msg
            print(passed_msg)
            # print(type(test_sample_list.samples[2]))
        except AssertionError:
            print(fail_msg, "sample_type is not solid.")
            print(type(test_sample_list.samples[3]))
            success = False

        try:
            print(f"sample_model test {testcounter} ", end="")
            testcounter += 1
            assert type(test_sample_list.samples[4]) == type(test_assembly2), fail_msg
            print(passed_msg)
        except AssertionError:
            print(fail_msg, "sample_type is not solid.")
            print(type(test_sample_list.samples[4]))
            success = False

        return success

    except Exception as e:
        tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        print(
            repr(e),
            tb,
        )
        return False

    return success