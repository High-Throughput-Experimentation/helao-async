import os
from pathlib import Path
from typing import Union

from helao.helpers.yml_tools import yml_load
from helao.helpers.read_hlo import read_hlo


class FileMapper:
    """
    FileMapper is a class that helps in mapping and locating files within a specified directory structure.
    It provides methods to locate, read, and process files based on their paths and states.

    Attributes:
        inputfile (Path or None): The absolute path of the input file if it exists, otherwise None.
        inputdir (Path): The absolute path of the input directory.
        inputparts (list): A list of parts of the input directory path.
        runpos (int): The position of the "RUNS_*" or "PROCESSES" directory in the path.
        prestr (str): The path string up to the "RUNS_*" or "PROCESSES" directory.
        states (list): A list of states used to identify different run directories.
        relstrs (list): A list of relative paths of files within the "RUNS_*" or "PROCESSES" directories.

    Methods:
        __init__(save_path: Union[str, Path]):
            Initializes the FileMapper with the given save path.
        
        locate(p: str) -> Union[str, None]:
            Locates the file path based on the given relative path and returns the absolute path if found.
        
        read_hlo(p: str, retries: int = 3) -> Union[tuple, None]:
            Reads an HLO file from the given relative path with a specified number of retries.
        
        read_yml(p: str) -> dict:
            Reads a YAML file from the given relative path and returns its contents as a dictionary.
        
        read_lines(p: str) -> list:
            Reads a text file from the given relative path and returns its contents as a list of lines.
        
        read_bytes(p: str) -> bytes:
            Reads a binary file from the given relative path and returns its contents as bytes.
    """
    def __init__(self, save_path: Union[str, Path]):
        """
        Initializes the FileMapper object with the given save path.

        Args:
            save_path (Union[str, Path]): The path where files are saved. It can be a string or a Path object.

        Attributes:
            inputfile (Path or None): The absolute path of the input file if save_path is a file, otherwise None.
            inputdir (Path): The absolute path of the directory containing the input file or the save_path directory.
            inputparts (list): A list of parts of the input directory path.
            runpos (int): The position of the "RUNS_*" or "PROCESSES" directory in the input directory path.
            prestr (str): The path string up to the "RUNS_*" or "PROCESSES" directory.
            states (list): A list of states used to identify different run states.
            relstrs (list): A list of relative paths of all files at the save_path level and deeper, relative to "RUNS_*" or "PROCESSES".
        """
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
        """
        Locate the file path based on the given string `p`.

        This method checks if the string `p` contains the substring "PROCESSES".
        If it does, the method returns `p` as is. Otherwise, it iterates through
        the `states` attribute, constructs a potential file path by joining
        `prestr`, "RUNS_" followed by the current state, and `p`. If the constructed
        path exists, it returns this path. If no valid path is found, it returns None.

        Args:
            p (str): The file path or partial file path to locate.

        Returns:
            str or None: The located file path if found, otherwise None.
        """
        if "PROCESSES" in p:
            return p
        for state in self.states:
            testp = Path(os.path.join(self.prestr, f"RUNS_{state}", p))
            if testp.exists():
                return testp
        return None

    def read_hlo(self, p: str, retries: int = 3):
        """
        Reads an HLO file from the specified path with retry logic.

        Args:
            p (str): The path to the HLO file.
            retries (int, optional): The number of times to retry reading the file in case of a ValueError. Defaults to 3.

        Returns:
            tuple: The contents of the HLO file if read successfully.

        Raises:
            FileNotFoundError: If the file cannot be located.
            ValueError: If the file cannot be read after the specified number of retries.
        """
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
        """
        Reads a YAML file from the specified path and returns its contents as a dictionary.

        Args:
            p (str): The path to the YAML file.

        Returns:
            dict: The contents of the YAML file as a dictionary.

        Raises:
            FileNotFoundError: If the file cannot be located.
        """
        lp = self.locate(p)
        if lp is None:
            raise FileNotFoundError
        else:
            print(lp)
            return dict(yml_load(Path(lp)))

    def read_lines(self, p: str):
        """
        Reads the contents of a file and returns them as a list of lines.

        Args:
            p (str): The path to the file.

        Returns:
            list: A list of strings, each representing a line in the file.

        Raises:
            FileNotFoundError: If the file cannot be located.
        """
        lp = self.locate(p)
        if lp is None:
            raise FileNotFoundError
        else:
            lines = lp.read_text().split("\n")
            return lines

    def read_bytes(self, p: str):
        """
        Reads the content of a file as bytes.

        Args:
            p (str): The path to the file.

        Returns:
            bytes: The content of the file.

        Raises:
            FileNotFoundError: If the file cannot be located.
        """
        lp = self.locate(p)
        if lp is None:
            raise FileNotFoundError
        else:
            return lp.read_bytes()
