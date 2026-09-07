"""Read new MPR points and assemble them into HELAO columns.

The OLE COM API has no streaming and no buffer drain: data is polled out of
the growing MPR file, one point at a time, through
``MeasureNumberOfPoints`` plus ``MeasureDcValue`` / ``MeasureEisValue`` /
``MeasureValueByCode``. The cursor is what turns that into something a poll
loop can use -- it remembers how many points it has already handed back, so
the driver calls ``read_new`` every tick and concatenates.

It is also where the derived columns are computed, which is the part worth
being careful about because a mistake is a wrong number under a right column
name:

* ``P_W`` is ``|Ewe * I|``. Not an approximation -- that is EC-Lab's own
  definition of variable 70, so fetching it would cost a call per point to
  learn the same number.
* ``cycle`` comes from status index 10, passed in by the caller, because it
  is a channel-level value rather than a per-point one.
* ``R_ohm`` is ``Re(Z)`` and ``X_ohm`` is ``MeasureEisValue``'s fourth
  element, which section 5.2.14 states is already ``-Im(Z)`` -- exactly what
  the eclib path computes as ``-modulus * sin(phase)``.
* ``process`` is reconstructed from the frequency: the same section states a
  non-EIS index returns frequency zero.

One deliberate accommodation. The manual describes ``MeasureDcValue`` as
returning an array "starting from the selected index", then lists three
values. Whether it yields one point or every remaining point is an at-station
probe. ``read_new`` advances by the length of what it actually received, so a
bulk return needs no change here -- it just gets faster.
"""

from .olecom_client import OleComClient, OleComError
from .technique import ColumnPlan, columns

__all__ = ["MprCursor", "empty_frame"]

#: Values MeasureDcValue returns, in order (section 5.2.13).
DC_FIELDS = ("t_s", "Ewe_V", "I_A")

#: Values MeasureEisValue returns, in order (section 5.2.14). The fourth is
#: already negated -- the manual says "the imaginary value is actually -Im(Z)".
EIS_FIELDS = ("t_s", "f_Hz", "R_ohm", "X_ohm")


def empty_frame(plan: ColumnPlan) -> dict[str, list[float]]:
    """A column dict with every declared column present and no rows.

    Every column present matters: a consumer that only ever sees the columns
    a particular poll happened to produce would key off a shape that changes
    between ticks.
    """
    return {name: [] for name in columns(plan)}


class MprCursor:
    """Hands back the MPR points not yet returned, as HELAO columns."""

    def __init__(self, client: OleComClient, plan: ColumnPlan, mpr_path: str):
        self.client = client
        self.plan = plan
        self.mpr_path = mpr_path
        self._n_read = 0

    @property
    def n_read(self) -> int:
        """How many points this cursor has already returned."""
        return self._n_read

    def reset(self, mpr_path: str) -> None:
        """Point at a new file and rewind.

        A multi-technique ``.mps`` -- CAOCV, or anything bracketed by TTL
        triggers -- writes one MPR per technique, so advancing to the next
        technique means resetting rather than constructing a new cursor and
        losing the plan.
        """
        self.mpr_path = mpr_path
        self._n_read = 0

    def read_new(self, cycle: float = 0.0) -> dict[str, list[float]]:
        """Every point since the last call.

        Args:
            cycle: Status index 10 at this poll, stamped across the points
                read. Ignored by plans that do not emit a ``cycle`` column.

        Returns:
            A column dict. Empty lists -- not an empty dict -- when there is
            nothing new, so a caller can extend unconditionally.
        """
        frame = empty_frame(self.plan)
        try:
            total = self.client.measure_number_of_points(self.mpr_path)
        except OleComError:
            # The file does not exist yet. Normal in the moments between
            # RunChannel and EC-Lab creating it; not a fault to report.
            return frame
        index = self._n_read
        while index < total:
            read = self._read_point(frame, index, cycle)
            if read == 0:
                # A point the file claims to hold but will not serve. Stop
                # rather than spin: the next poll retries from here.
                break
            index += read
        self._n_read = index
        return frame

    def _read_point(self, frame: dict, index: int, cycle: float) -> int:
        """Append the point(s) at ``index``. Returns how many were appended."""
        if self.plan.kind == "eis":
            return self._read_eis_point(frame, index)
        return self._read_dc_point(frame, index, cycle)

    def _read_dc_point(self, frame: dict, index: int, cycle: float) -> int:
        try:
            values = self.client.measure_dc_value(self.mpr_path, index)
        except OleComError:
            return 0
        # A bulk return arrives as a multiple of the three DC fields; a
        # single-point return is exactly three. Either advances correctly.
        stride = len(DC_FIELDS)
        count = max(len(values) // stride, 1)
        for offset in range(count):
            chunk = values[offset * stride : (offset + 1) * stride]
            point = dict(zip(DC_FIELDS, chunk))
            for name in ("t_s", "Ewe_V", "I_A"):
                if name in frame:
                    frame[name].append(point[name])
            if "P_W" in frame:
                frame["P_W"].append(abs(point["Ewe_V"] * point["I_A"]))
            if "cycle" in frame:
                frame["cycle"].append(cycle)
        return count

    def _read_eis_point(self, frame: dict, index: int) -> int:
        try:
            values = self.client.measure_eis_value(self.mpr_path, index)
        except OleComError:
            return 0
        point = dict(zip(EIS_FIELDS, values))
        for name in EIS_FIELDS:
            if name in frame:
                frame[name].append(point[name])
        if "process" in frame:
            frame["process"].append(1.0 if point["f_Hz"] else 0.0)
        for name, code in self.plan.var_codes.items():
            try:
                frame[name].append(
                    self.client.measure_value_by_code(self.mpr_path, code, index)
                )
            except OleComError:
                # A variable this technique does not record. NaN rather than a
                # gap, so every column stays the same length -- a short column
                # would misalign every row after it.
                frame[name].append(float("nan"))
        return 1
