"""Rendered-parity lane (P7j): computed styles and drawn pixels, in a browser.

The three older ``helao/core/tests/browser_check_*.py`` scripts assert that
elements and roles are *present*. That catches a page that failed to render;
it cannot catch either of the two failures this package exists for:

* **A stale Reflex bundle.** The compiled CSS contains only the utilities that
  existed at build time, so a bundle built before a slice that changed
  ``class_name=`` usage renders the new controls **completely unstyled, with no
  error on either side**. The element is present, the role is right, the text
  is right -- and the button is grey. Only a computed style can see this.
* **WebGL context eviction.** Chrome allows 16 live contexts per page and
  silently evicts the oldest past that. An evicted chart never draws again
  while every other signal reads healthy: data arrives, the view is mounted,
  the append fires, and nothing is logged server-side. Only a drawn pixel can
  see this.

Both failures are invisible to a source grep, which is why a grep is banned as
a gate for either of them.

**Every style assertion in this package is paired with a content assertion**,
and that pairing is not decoration -- it is the anti-vacuity rule for the whole
lane. A blank page has computed styles too: ``getComputedStyle`` on a page that
rendered nothing returns perfectly good values for the ``<body>`` that is
there, and a contrast ratio computed between two defaults will happily clear
any floor. So a measurement is only ever recorded after the element count it
came from has been asserted greater than zero.

Not pytest modules, deliberately, and for the same reason the older checks are
not: they launch orchestration groups and drive browsers, the class of thing
that hangs a collected session (see ``run_tests.py``'s per-file rule).

**Exactly how ``run_tests.py`` treats them, since it is easy to get wrong.**
It globs ``test_*.py``, so a file named ``check_*.py`` is not discovered at
all -- it is *not* reported as ``NOTESTS``, which is the verdict for a
discovered file that defines nothing collectable. Verified: the three older
``browser_check_*.py`` scripts do not appear in ``run_tests.py --list``
either. The naming here is ``check_*`` rather than ``*_check`` only for
sorting; both are equally invisible to the sweep, which is the intent.

The pure logic underneath -- the matrix, the diff, the colour math, the ink
bands, and the config pair the diff depends on -- *is* pytest-tested, in
``helao/core/tests/test_browser_parity.py``, which the sweep does collect. So
the half that can be checked without a browser rides the normal suite, and only
the half that genuinely needs one is manual.

Entry point: ``run_browser_parity.py`` at the repo root.
"""
