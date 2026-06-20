"""Bokeh document builder for the data browser visualizer."""
from socket import gethostname

from bokeh.layouts import column, row
from bokeh.models import (
    Button, ColumnDataSource, DataTable, Div, RadioButtonGroup,
    Select, Spacer, TableColumn, Tabs, TabPanel, TextInput,
)
from bokeh.palettes import Category10
from bokeh.plotting import figure

from helao.core.servers.data_browser import sources, state as dbstate

INDEX_TABLE_COLS = ["source", "sequence", "experiment", "node", "technique",
                    "sample", "run_type", "file_name", "file_type", "date", "available"]
FILTER_COLS = ["source", "sequence", "experiment", "node", "technique",
               "sample", "run_type", "file_name", "date"]
PALETTE = Category10[10]


def build_document(vis):
    """Build the data-browser UI on vis.doc. Returns vis.doc."""
    doc = vis.doc
    root = str(vis.helaodirs.root)
    params = (getattr(vis, "server_cfg", {}) or {}).get("params", {})
    max_points = params.get("max_points", 50000)

    ui = _UI(vis, root, max_points)
    doc.add_root(ui.layout)
    return doc


class _UI:
    """Holds widgets + mutable selection state and wires callbacks."""

    def __init__(self, vis, root, max_points):
        self.vis = vis
        self.root = root
        self.max_points = max_points
        self.index_df = None
        self.selected = []  # list[SelectedDataset]

        # --- header ---
        header = Div(
            text=f"<b>Data Browser on {gethostname().lower()}</b>",
            styles={"font-size": "180%", "color": "#2471A3"}, width=1000, height=32)

        # --- control bar ---
        self.group_sel = RadioButtonGroup(labels=list(sources.GROUPS.keys()), active=0)
        self.source_sel = Select(title="Source",
                                 options=sources.GROUPS["RUNS"],
                                 value=sources.GROUPS["RUNS"][0], width=160)
        self.date_start = TextInput(title="From (YY.WW/MMDD)", width=140)
        self.date_end = TextInput(title="To (YY.WW/MMDD)", width=140)
        self.scan_btn = Button(label="Scan", button_type="primary", width=80)
        self.status = Div(text="", width=600)

        self.group_sel.on_change("active", self._on_group_change)
        self.scan_btn.on_click(self._on_scan)

        control = row(self.group_sel, self.source_sel, self.date_start,
                      self.date_end, column(Spacer(height=18), self.scan_btn))

        # --- index (full width) ---
        self.filter_in = TextInput(title="Filter index", width=300)
        self.filter_in.on_change("value", lambda a, o, n: self._refresh_index_table())
        self.index_source = ColumnDataSource(data={c: [] for c in INDEX_TABLE_COLS})
        self.index_table = DataTable(
            source=self.index_source,
            columns=[TableColumn(field=c, title=c) for c in INDEX_TABLE_COLS],
            height=380, selectable="checkbox", sizing_mode="stretch_width")
        self.add_btn = Button(label="+ Add selected to plot",
                              button_type="success", width=300)
        self.clear_btn = Button(label="Clear plot", width=300)
        self.add_btn.on_click(self._on_add)
        self.clear_btn.on_click(self._on_clear)
        buttons = row(self.add_btn, self.clear_btn)

        self.right = self._build_right()

        self.layout = column(
            header, control, self.filter_in, self.index_table, buttons, self.right,
            sizing_mode="stretch_width")

    def _build_right(self):
        # axis controls
        self.x_sel = Select(title="X", options=[], width=180)
        self.y_sel = Select(title="Y", options=[], width=180)
        self.type_sel = Select(title="Type", options=["line", "scatter"],
                               value="line", width=120)
        for w in (self.x_sel, self.y_sel, self.type_sel):
            w.on_change("value", self._on_axis_change)
        self.plot = figure(height=380, tools="pan,box_zoom,wheel_zoom,reset,save",
                           sizing_mode="stretch_width")
        plot_panel = TabPanel(
            child=column(row(self.x_sel, self.y_sel, self.type_sel), self.plot,
                         sizing_mode="stretch_width"),
            title="Plot")
        # table panel (Task 13)
        self.summary_source = ColumnDataSource(data={c: [] for c in dbstate.SUMMARY_COLS})
        self.summary_table = DataTable(
            source=self.summary_source,
            columns=[TableColumn(field=c, title=c) for c in dbstate.SUMMARY_COLS],
            height=180, selectable=True, sizing_mode="stretch_width")
        self.summary_source.selected.on_change("indices", self._on_summary_select)
        self.rows_source = ColumnDataSource(data={})
        self.rows_table = DataTable(source=self.rows_source, columns=[],
                                    height=200, sizing_mode="stretch_width")
        table_panel = TabPanel(
            child=column(Div(text="<b>Trace summary</b> (select a row to view data)"),
                         self.summary_table,
                         Div(text="<b>Data rows</b>"), self.rows_table,
                         sizing_mode="stretch_width"),
            title="Table")
        self.tabs = Tabs(tabs=[plot_panel, table_panel], sizing_mode="stretch_width")
        return self.tabs

    def _refresh_axes(self):
        cols = dbstate.available_columns(self.selected)
        self.x_sel.options = cols
        self.y_sel.options = cols
        if cols:
            if self.x_sel.value not in cols:
                self.x_sel.value = cols[0]
            if self.y_sel.value not in cols:
                self.y_sel.value = cols[1] if len(cols) > 1 else cols[0]

    def _on_axis_change(self, attr, old, new):
        self._rebuild_plot()

    def _rebuild_plot(self):
        self.plot.renderers = []
        if self.plot.legend:
            self.plot.legend.items = []
        xcol, ycol = self.x_sel.value, self.y_sel.value
        if not xcol or not ycol:
            return
        for i, ds in enumerate(self.selected):
            tr = dbstate.build_trace(ds, xcol, ycol)
            if tr is None:
                continue
            tr = dbstate.downsample(tr, self.max_points)
            src = ColumnDataSource(data=tr)
            color = PALETTE[i % len(PALETTE)]
            if self.type_sel.value == "scatter":
                self.plot.scatter("x", "y", source=src, color=color, legend_label=ds.label)
            else:
                self.plot.line("x", "y", source=src, color=color, legend_label=ds.label)
        self.plot.xaxis.axis_label = xcol
        self.plot.yaxis.axis_label = ycol

    def _rebuild_tables(self):
        xcol, ycol = self.x_sel.value, self.y_sel.value
        rows = [dbstate.summary_row(ds, xcol, ycol) for ds in self.selected]
        if rows:
            self.summary_source.data = {c: [r[c] for r in rows] for c in dbstate.SUMMARY_COLS}
        else:
            self.summary_source.data = {c: [] for c in dbstate.SUMMARY_COLS}
        self.rows_source.data = {}
        self.rows_table.columns = []

    def _on_summary_select(self, attr, old, new):
        if not new or new[0] >= len(self.selected):
            return
        ds = self.selected[new[0]]
        self.rows_source.data = {k: list(v) for k, v in ds.data.items()}
        self.rows_table.columns = [TableColumn(field=k, title=k) for k in ds.data]

    # ---- callbacks ----
    def _current_source(self):
        return self.source_sel.value

    def _on_group_change(self, attr, old, new):
        group = list(sources.GROUPS.keys())[new]
        opts = sources.GROUPS[group]
        self.source_sel.options = opts
        self.source_sel.value = opts[0]

    def _on_scan(self):
        ds = self.date_start.value.strip() or None
        de = self.date_end.value.strip() or None
        try:
            self.index_df = sources.get_index(self.root, self._current_source(), ds, de)
        except Exception as exc:
            self.index_df = None
            self.status.text = f"<span style='color:#c0392b'>scan failed: {exc}</span>"
            self.vis.print_message(f"data_browser scan failed: {exc}", error=True)
            return
        self.status.text = f"indexed {len(self.index_df)} datasets from {self._current_source()}"
        self._refresh_index_table()

    def _filtered_df(self):
        if self.index_df is None:
            return None
        q = self.filter_in.value.strip().lower()
        if not q:
            return self.index_df
        cols = FILTER_COLS
        mask = self.index_df[cols].astype(str).apply(
            lambda r: q in " ".join(r.values).lower(), axis=1)
        return self.index_df[mask]

    def _refresh_index_table(self):
        df = self._filtered_df()
        if df is None:
            self.index_source.data = {c: [] for c in INDEX_TABLE_COLS}
            return
        self.index_source.selected.indices = []
        self.index_source.data = {c: list(df[c].astype(str)) for c in INDEX_TABLE_COLS}

    def _on_add(self):
        df = self._filtered_df()
        if df is None:
            return
        picks = list(self.index_source.selected.indices)
        datasets, skipped = dbstate.load_selected(df.reset_index(drop=True), picks)
        self.selected.extend(datasets)
        for label, reason in skipped:
            self.vis.print_message(f"data_browser skipped {label}: {reason}")
        self._on_selection_changed()

    def _on_clear(self):
        self.selected = []
        self._on_selection_changed()

    def _on_selection_changed(self):
        self._refresh_axes()
        self._rebuild_plot()
        self._rebuild_tables()
        self.status.text = f"{len(self.selected)} dataset(s) selected"
