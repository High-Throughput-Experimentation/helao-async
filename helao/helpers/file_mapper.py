import os
from pathlib import Path
from typing import Union

from ruamel.yaml import YAML
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
            i for i, v in enumerate(self.inputparts) if v.startswith("RUNS_")
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

    def locate(self, p: str):
        for state in self.states:
            testp = Path(os.path.join(self.prestr, f"RUNS_{state}", p))
            if testp.exists():
                return testp
        return None

    def read_hlo(self, p: str):
        lp = self.locate(p)
        if lp is None:
            raise FileNotFoundError
        else:
            return read_hlo(lp.__str__())

    def read_yml(self, p: str):
        lp = self.locate(p)
        if lp is None:
            raise FileNotFoundError
        else:
            yaml = YAML(typ="safe")
            return yaml.load(lp)

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
