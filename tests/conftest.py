import os
import tempfile

_db = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db}"
os.environ["DATA_PROVIDER"] = "yahoo"
os.environ["RUN_SCHEDULER"] = "false"
os.environ["WEB_PASSWORD"] = ""
os.environ["ANTHROPIC_API_KEY"] = "test-key"

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from app.db import Base, engine, init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    init_db()
    yield


def make_candles(n=600, freq="1h", start_price=2400.0, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    close = start_price + np.cumsum(rng.normal(0, 3, n))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + rng.uniform(0, 2, n)
    low = np.minimum(open_, close) - rng.uniform(0, 2, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": 1.0}, index=idx).rename_axis("ts")
