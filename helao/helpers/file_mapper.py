import os
from pathlib import Path
from typing import Union

from helao.helpers.yml_tools import yml_load
from helao.helpers.read_hlo import read_hlo


class FileMapper:
    def __init__(self, save_path: Union[str, Path]):
        if isinstance(save_path, str):
            save_path = Path(save_path)
        if save_path.is_file():
            self.inputfile = save_path.absolute()
            self.inputdir = self.inputfile.parent
        else:
            self.inputfile = None
            self.inputdir = save_path.absolute()
        self.inputparts = list(self.inputdir.parts)
        self.runpos = [
            i
            for i, v in enumerate(self.inputparts)
            if v.startswith("RUNS_") or v == "PROCESSES"
        ][0]
        self.prestr = os.path.join(*self.inputparts[: self.runpos])

        # list all files at save_path level and deeper, relative to RUNS_*
        self.states = ["ACTIVE", "FINISHED", "SYNCED", "DIAG"]
        self.relstrs = []
        for state in self.states:
            stateparts = list(self.inputparts)
            stateparts[self.runpos] = f"RUNS_{state}"
            stateglob = Path(os.path.join(*stateparts)).rglob("*")
            for p in stateglob:
                if p.is_file():
                    self.relstrs.append(os.path.join(*p.parts[self.runpos + 1 :]))
        prcparts = list(self.inputparts)
        prcparts[self.runpos] = "PROCESSES"
        prcglob = Path(os.path.join(*prcparts)).rglob("*")
        for p in prcglob:
            if p.is_file():
                self.relstrs.append(os.path.join(*p.parts[self.runpos + 1 :]))

    def locate(self, p: str):
        if "PROCESSES" in p:
            return p
        for state in self.states:
            testp = Path(os.path.join(self.prestr, f"RUNS_{state}", p))
            if testp.exists():
                return testp
        return None

    def read_hlo(self, p: str, retries: int = 3):
        lp = self.locate(p)
        if lp is None:
            raise FileNotFoundError
        else:
            retry_counter = 0
            read_success = False
            while (not read_success) or (retry_counter <= retries):
                try:
                    hlo_tup = read_hlo(lp.__str__())
                    read_success = True
                    return hlo_tup
                except ValueError:  # retry read_hlo in case file not fully written
                    retry_counter += 1
            return None

    def read_yml(self, p: str):
        lp = self.locate(p)
        if lp is None:
            raise FileNotFoundError
        else:
            print(lp)
            return dict(yml_load(Path(lp)))

    def read_lines(self, p: str):
        lp = self.locate(p)
        if lp is None:
            raise FileNotFoundError
        else:
            lines = lp.read_text().split("\n")
            return lines

    def read_bytes(self, p: str):
        lp = self.locate(p)
        if lp is None:
            raise FileNotFoundError
        else:
            return lp.read_bytes()
