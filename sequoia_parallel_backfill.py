"""Windows 友好的 Sequoia-X 首次全市场并行回填。

上游 ``DataEngine.backfill`` 是单连接串行实现；本脚本复用上游同一个
``_bs_fetch_batch`` worker，分批并行抓取并写入同一张 ``stock_daily`` 表。
可安全重跑：已经更新到今天的股票自动跳过，写库使用 INSERT OR IGNORE。
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import date, timedelta
from multiprocessing import Pool, freeze_support

import pandas as pd

from config import SEQUOIA_X_DB
from sequoia_x.core.config import Settings
from sequoia_x.data.engine import DataEngine, _bs_fetch_batch


def pending_tasks(engine: DataEngine, end: str) -> list[tuple[str, str, str, str]]:
    symbols = engine.get_all_symbols()
    with sqlite3.connect(engine.db_path) as conn:
        last_dates = dict(
            conn.execute(
                "SELECT symbol, MAX(date) FROM stock_daily GROUP BY symbol"
            ).fetchall()
        )

    tasks = []
    for symbol in symbols:
        last = last_dates.get(symbol)
        if last and last >= end:
            continue
        start = engine.start_date
        if last:
            start = (date.fromisoformat(last) + timedelta(days=1)).isoformat()
        tasks.append((symbol, engine._to_baostock_code(symbol), start, end))
    return tasks


def write_rows(db_path: str, rows: list[list[str]]) -> int:
    if not rows:
        return 0
    frame = pd.DataFrame(
        rows,
        columns=["symbol", "date", "open", "high", "low", "close", "volume", "turnover"],
    )
    for column in ["open", "high", "low", "close", "volume", "turnover"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["close"])
    frame = frame.loc[frame["volume"] > 0]
    records = list(frame.itertuples(index=False, name=None))
    with sqlite3.connect(db_path, timeout=60) as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO stock_daily
                (symbol, date, open, high, low, close, volume, turnover)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            records,
        )
        conn.commit()
    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sequoia-X 并行历史回填")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--per-worker", type=int, default=60)
    parser.add_argument("--end", default=date.today().isoformat())
    args = parser.parse_args()

    settings = Settings(
        db_path=str(SEQUOIA_X_DB),
        start_date="2024-01-01",
        feishu_webhook_url="disabled://local-research",
    )
    engine = DataEngine(settings)
    tasks = pending_tasks(engine, args.end)
    if not tasks:
        print("Sequoia-X 数据库已经完整更新。")
        return

    round_size = max(1, args.workers * args.per_worker)
    total_rows = 0
    total_tasks = len(tasks)
    with Pool(min(args.workers, total_tasks)) as pool:
        for offset in range(0, total_tasks, round_size):
            current = tasks[offset : offset + round_size]
            chunks = [current[i:: args.workers] for i in range(args.workers)]
            chunks = [chunk for chunk in chunks if chunk]
            batches = pool.map(_bs_fetch_batch, chunks)
            rows = [row for batch in batches for row in batch]
            total_rows += write_rows(str(SEQUOIA_X_DB), rows)
            done = min(offset + len(current), total_tasks)
            print(f"进度 {done}/{total_tasks}，累计写入 {total_rows} 条日线")

    with sqlite3.connect(SEQUOIA_X_DB) as conn:
        summary = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(date), MAX(date) FROM stock_daily"
        ).fetchone()
    print(f"完成：rows={summary[0]}, symbols={summary[1]}, range={summary[2]}..{summary[3]}")


if __name__ == "__main__":
    freeze_support()
    main()
