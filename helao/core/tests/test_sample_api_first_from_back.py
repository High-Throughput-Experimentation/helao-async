"""get_samples(sample_no=-count) must return the first sample, not skip it."""

import sqlite3
import types

import pytest

from helao.core.models.sample import LiquidSample
from helao.helpers.sample_api import LiquidSampleAPI


@pytest.mark.asyncio
async def test_negative_sample_no_equal_to_count_returns_first(tmp_path):
    serv = types.SimpleNamespace(helaodirs=types.SimpleNamespace(db_root=str(tmp_path)))
    api = LiquidSampleAPI(serv)
    await api.init_db()

    async def _open():
        api._con = sqlite3.connect(":memory:")
        api._cur = api._con.cursor()
        api._cur.execute(f"create table {api._sample_type} (idx integer)")
        api._cur.executemany(f"insert into {api._sample_type} values (?)", [(1,), (2,)])

    api._open_db = _open
    api._df_to_sample = lambda df: LiquidSample(sample_no=int(df.idx.iloc[-1]))
    got = await api.get_samples([LiquidSample(sample_no=-2)])
    assert [s.sample_no for s in got] == [1]
