"""The hexagon's data-browser filesystem face (P7h).

:class:`BrowserSource` satisfies
:class:`~helao.hexagon.ports.browser_source.BrowserSourcePort` by **delegating
to the two shared modules** ``helao/core/servers/data_browser/readers.py`` and
``sources.py``. One class over two modules, matching the port: they are the two
faces of one boundary -- find the files, then read one -- and a caller needs
both or neither.

Nothing is reimplemented. Three behaviours would be lost by a second
implementation, each measured in the modules themselves:

* **Format dispatch is overridable.** ``read_dataset(locator, fmt)`` uses the
  extension only when ``fmt`` is ``None``; analysis outputs are named after an
  S3 key and carry an extension that does not describe their contents.
* **The walk is tolerant.** ``sources`` reads sequence/experiment/action YAML
  as it goes and a malformed one yields a row with blank fields rather than
  aborting the scan -- a browser that indexes nothing because one run is
  half-written is useless at exactly the moment it is needed.
* **Unavailability is a row, not an omission.** A process or analysis whose
  data file is not present locally is still indexed, with ``available``
  false -- so the operator sees that it exists and is elsewhere, instead of
  wondering where it went.

Stateless: ``root`` and ``source`` ride on each call, mirroring the module
functions, so one instance serves every source on a page.

Under ``adapters/vis/`` because ``adapters/native/`` may not import
``helao.core.servers.*`` (test_boundaries.py:131-143).
"""

from typing import Optional

from helao.core.servers.data_browser import readers, sources

__all__ = ["BrowserSource"]


class BrowserSource:
    """:class:`BrowserSourcePort` over ``readers`` and ``sources``."""

    # --- readers -------------------------------------------------------------

    def make_zip_locator(self, zip_path: str, member: str) -> str:
        """Delegate to :func:`readers.make_zip_locator`."""
        return readers.make_zip_locator(zip_path, member)

    def parse_locator(self, locator: str) -> tuple:
        """Delegate to :func:`readers.parse_locator`."""
        return readers.parse_locator(locator)

    def read_dataset(self, locator: str, fmt: Optional[str] = None) -> tuple:
        """Delegate to :func:`readers.read_dataset`.

        ``ValueError`` for an unsupported format propagates: the caller turns
        it into a per-file "skipped" reason, and swallowing it here would drop
        the file with no explanation.
        """
        return readers.read_dataset(locator, fmt)

    # --- sources -------------------------------------------------------------

    def build_source_index(self, root: str, source) -> object:
        """Delegate to :func:`sources.build_source_index`."""
        return sources.build_source_index(root, source)

    def get_index(
        self,
        root: str,
        source,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> object:
        """Delegate to :func:`sources.get_index`."""
        return sources.get_index(root, source, date_start, date_end)
