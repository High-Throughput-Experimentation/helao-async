"""Data-browser filesystem port (P7h; Q8 answer 1, which inverted the default).

Q8's default listed ``readers`` beside ``param_forms`` as pure logic. Measured,
that is backwards: ``readers.py`` is the *only* fs-touching module of the
browser trio (``open()`` and ``zipfile.ZipFile`` at ``:49-52``) and
``data_browser/state.py:112`` reaches the filesystem *through* it. ``sources.py``
is a 386-line directory walk. So the browser's port covers **both fs faces** --
reading a dataset and walking the run tree -- and ``state`` is the pure caller
that stays a plain module.

Two clauses worth stating at the seam:

* **A locator is a string, and the two forms are part of the contract.** A
  loose file is its absolute path; a zip member is
  ``"zip::<zip_path>::<member>"``. :meth:`make_zip_locator` and
  :meth:`parse_locator` are on the port for that reason -- an index row's
  ``locator`` crosses this boundary and a caller that hand-assembles one has
  reimplemented the format. (A zip path containing ``::`` is unsupported; a
  non-issue on normal filesystems.)
* **``fmt`` overrides the extension, and must stay overridable.** Analysis
  outputs are named after an S3 key and carry an extension that does not match
  their format, so dispatch by extension alone silently reads the wrong parser.

Ports may import only ``helao.hexagon.domain.*``/``helao.hexagon.ports.*``/
``helao.core.drivers.helao_driver`` (test_boundaries.py:78-82), which excludes
pandas -- so the index is ``object``, not ``DataFrame``. That is the ordinary
opaque-return rule and it costs nothing: the index is handed straight back to
``state.load_selected``, never inspected across the seam.

The concrete face is ``adapters/vis/browser_source.py``; ``adapters/native/``
may not import ``helao.core.servers.*`` (test_boundaries.py:131-143), which is
where both modules live.
"""

from typing import Optional, Protocol, runtime_checkable

__all__ = ["BrowserSourcePort"]


@runtime_checkable
class BrowserSourcePort(Protocol):
    """Structural mirror of the public functions of ``readers`` + ``sources``."""

    # --- readers: the dataset-read face -------------------------------------

    def make_zip_locator(self, zip_path: str, member: str) -> str:
        """Build the locator for one member of a zip archive."""
        ...

    def parse_locator(self, locator: str) -> tuple:
        """Return ``('file', path)`` or ``('zip', zip_path, member)``."""
        ...

    def read_dataset(self, locator: str, fmt: Optional[str] = None) -> tuple:
        """Read any supported column-bearing file into ``(meta, {column: list})``.

        ``fmt`` (``"hlo"``/``"json"``/``"parquet"``) overrides extension-based
        dispatch. Raises ``ValueError`` for an unsupported format -- the one
        place in the browser that does raise, because the caller
        (``state.load_selected``) turns it into a per-file "skipped" reason
        rather than dropping the file silently.
        """
        ...

    # --- sources: the tree-walk face ----------------------------------------

    def build_source_index(self, root: str, source) -> object:
        """Construct the indexer for one source. Opaque return."""
        ...

    def get_index(
        self,
        root: str,
        source,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> object:
        """Walk one source's ``YY.WW/MMDD`` tree into a candidate index.

        Opaque return (a pandas frame with ``sources.INDEX_COLUMNS``), scoped
        by a lexicographic ``YY.WW/MMDD`` range; ``None`` bounds are open.
        """
        ...
