import os
import argparse
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

TRADING_DAYS = 252
RISK_FREE_ANNUAL = 0.06
TEST_TICKERS = ["BBRI.JK", "BMRI.JK", "BBCA.JK"]


# =====================================================================
# 2. Data
# =====================================================================
def get_data(ticker, start, end):
    """Download harga harian. Fallback ke data simulasi bila download gagal."""
    try:
        import yfinance as yf
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        if df is None or df.empty:
            raise ValueError(f"Data kosong untuk {ticker}")
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df[["Close"]].dropna()
    except Exception as e:
        print(f"[WARN] {ticker}: gagal download ({type(e).__name__}). Pakai data simulasi.")
        return _generate_dummy(ticker, start, end)


def _generate_dummy(ticker, start, end):
    """Data simulasi (BUKAN data asli) dengan fase tren naik/turun bergantian."""
    tanggal = pd.bdate_range(start=start, end=end)
    n = len(tanggal)
    rng = np.random.default_rng(sum(ord(c) for c in ticker))
    drift = np.repeat(rng.normal(0.0003, 0.0012, n // 120 + 1), 120)[:n]  # rezim tren
    ret = drift + rng.normal(0, 0.014, n)
    harga0 = {"BBRI.JK": 4000, "BMRI.JK": 6500, "BBCA.JK": 8000}.get(ticker, 5000)
    return pd.DataFrame({"Close": harga0 * np.exp(np.cumsum(ret))}, index=tanggal)


# =====================================================================
# 3. Sinyal
# =====================================================================
def generate_signals(df, short, long):
    """Tambahkan MA, sinyal mentah, posisi (setelah shift), dan titik beli/jual."""
    if short >= long:
        raise ValueError("MA pendek harus lebih kecil dari MA panjang")

    out = df.copy()
    out["ma_short"] = out["Close"].rolling(short).mean()
    out["ma_long"] = out["Close"].rolling(long).mean()

    # sinyal mentah: 1 jika MA pendek di atas MA panjang (NaN -> 0)
    valid = out["ma_long"].notna()
    out["signal"] = ((out["ma_short"] > out["ma_long"]) & valid).astype(int)

    # posisi riil: eksekusi di hari berikutnya
    out["position"] = out["signal"].shift(1).fillna(0).astype(int)

    # titik beli/jual untuk plot (di hari sinyal muncul)
    perubahan = out["signal"].diff().fillna(0)
    out["buy"] = perubahan == 1
    out["sell"] = perubahan == -1
    return out


# =====================================================================
# 4. Performance
# =====================================================================
def _max_drawdown(ret):
    cum = (1 + ret).cumprod()
    return ((cum - cum.cummax()) / cum.cummax()).min()


def _sharpe(ret, risk_free=RISK_FREE_ANNUAL):
    std = ret.std()
    if std == 0 or np.isnan(std):
        return np.nan
    return (ret.mean() * TRADING_DAYS - risk_free) / (std * np.sqrt(TRADING_DAYS))


def _trade_returns(ret, position):
    """Return per trade = compounding return selama satu periode posisi=1 berturut-turut."""
    hasil = []
    grup = (position != position.shift()).cumsum()
    for _, idx in position.groupby(grup):
        if idx.iloc[0] == 1:
            hasil.append((1 + ret.loc[idx.index]).prod() - 1)
    return hasil


def hitung_performance(sig):
    """Hitung semua metrik untuk strategy dan buy-and-hold pada DataFrame sinyal."""
    ret = sig["Close"].pct_change().fillna(0)
    ret_strategy = ret * sig["position"]

    trades = _trade_returns(ret, sig["position"])
    win_rate = np.mean([t > 0 for t in trades]) if trades else np.nan

    return {
        "total_return_strategy": (1 + ret_strategy).prod() - 1,
        "total_return_bnh": (1 + ret).prod() - 1,
        "sharpe_strategy": _sharpe(ret_strategy),
        "sharpe_bnh": _sharpe(ret),
        "max_dd_strategy": _max_drawdown(ret_strategy),
        "max_dd_bnh": _max_drawdown(ret),
        "win_rate": win_rate,
        "jumlah_trade": len(trades),
    }


def cetak_performance(label, p):
    wr = "n/a" if np.isnan(p["win_rate"]) else f"{p['win_rate']*100:.1f}%"
    print(f"  [{label}]")
    print(f"    Total return  strategy {p['total_return_strategy']*100:8.2f}%   |  BnH {p['total_return_bnh']*100:8.2f}%")
    print(f"    Sharpe ratio  strategy {p['sharpe_strategy']:8.2f}    |  BnH {p['sharpe_bnh']:8.2f}")
    print(f"    Max drawdown  strategy {p['max_dd_strategy']*100:8.2f}%   |  BnH {p['max_dd_bnh']*100:8.2f}%")
    print(f"    Win rate {wr}   |   Jumlah trade {p['jumlah_trade']}")


# =====================================================================
# 5. Plot
# =====================================================================
def buat_plot(sig, ticker, short, long, outfile):
    ret = sig["Close"].pct_change().fillna(0)
    cum_strategy = (1 + ret * sig["position"]).cumprod() - 1
    cum_bnh = (1 + ret).cumprod() - 1

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 9), sharex=True)

    ax1.plot(sig.index, sig["Close"], label="Harga", color="black", linewidth=1)
    ax1.plot(sig.index, sig["ma_short"], label=f"MA{short}", linewidth=1)
    ax1.plot(sig.index, sig["ma_long"], label=f"MA{long}", linewidth=1)
    ax1.scatter(sig.index[sig["buy"]], sig["Close"][sig["buy"]],
                marker="^", color="green", s=70, label="Beli", zorder=5)
    ax1.scatter(sig.index[sig["sell"]], sig["Close"][sig["sell"]],
                marker="v", color="red", s=70, label="Jual", zorder=5)
    ax1.set_title(f"{ticker}: Harga, MA, dan Sinyal Beli/Jual")
    ax1.set_ylabel("Harga (Rp)")
    ax1.legend(loc="upper left")
    ax1.grid(alpha=0.3)

    ax2.plot(cum_strategy.index, cum_strategy * 100, label="Strategy MA Crossover")
    ax2.plot(cum_bnh.index, cum_bnh * 100, label="Buy-and-Hold")
    ax2.axhline(0, color="black", linewidth=0.8, linestyle="--")
    ax2.set_title("Cumulative Return: Strategy vs Buy-and-Hold")
    ax2.set_ylabel("Cumulative Return (%)")
    ax2.set_xlabel("Tanggal")
    ax2.legend(loc="upper left")
    ax2.grid(alpha=0.3)

    plt.tight_layout()
    os.makedirs(os.path.dirname(outfile), exist_ok=True)
    plt.savefig(outfile, dpi=120)
    plt.close(fig)
    print(f"  [OK] Grafik disimpan: {outfile}")


# =====================================================================
# 6. Out-of-sample test
# =====================================================================
def out_of_sample_test(sig, train_ratio=0.7):
    """
    Split KRONOLOGIS (bukan acak): 70% awal = in-sample, 30% akhir = out-of-sample.
    MA hanya memakai data masa lalu, jadi sinyal yang sudah dihitung pada seluruh
    deret tidak membocorkan data masa depan ke segmen mana pun.
    """
    titik = int(len(sig) * train_ratio)
    in_sample, out_sample = sig.iloc[:titik], sig.iloc[titik:]
    return hitung_performance(in_sample), hitung_performance(out_sample), sig.index[titik]


def optimasi_in_sample(df, train_ratio=0.7, shorts=(5, 10, 20), longs=(30, 50, 100)):
    """
    Opsional: cari kombinasi (short, long) terbaik berdasarkan Sharpe IN-SAMPLE saja,
    lalu parameter itu dievaluasi di out-of-sample. Ini cara yang jujur untuk
    menguji apakah hasil optimasi benar-benar bertahan di data yang belum pernah dilihat.
    """
    titik = int(len(df) * train_ratio)
    terbaik, skor_terbaik = None, -np.inf 
    for s in shorts:
        for l in longs:
            if s >= l:
                continue
            p = hitung_performance(generate_signals(df, s, l).iloc[:titik])
            if not np.isnan(p["sharpe_strategy"]) and p["sharpe_strategy"] > skor_terbaik:
                terbaik, skor_terbaik = (s, l), p["sharpe_strategy"]
    return terbaik


# =====================================================================
# Orkestrasi
# =====================================================================
def run_backtest(ticker, start, end, short, long, outdir=".", optimize=False):
    print("\n" + "=" * 70)
    print(f"BACKTEST {ticker}  |  {start} s/d {end}  |  MA{short}/MA{long}")
    print("=" * 70)

    df = get_data(ticker, start, end)

    if optimize:
        terbaik = optimasi_in_sample(df)
        if terbaik:
            short, long = terbaik
            print(f"  Parameter terbaik (in-sample): MA{short}/MA{long}")

    sig = generate_signals(df, short, long)

    print("\n  --- Seluruh periode ---")
    cetak_performance("FULL", hitung_performance(sig))

    p_in, p_out, tgl_split = out_of_sample_test(sig)
    print(f"\n  --- Out-of-sample test (split di {tgl_split.date()}) ---")
    cetak_performance("IN-SAMPLE (70% awal)", p_in)
    cetak_performance("OUT-OF-SAMPLE (30% akhir)", p_out)

    nama = ticker.replace(".JK", "")
    buat_plot(sig, ticker, short, long, os.path.join(outdir, "output", f"backtest_{nama}.png"))
    return sig


def main():
    ap = argparse.ArgumentParser(description="MA Crossover Backtest")
    ap.add_argument("--ticker", help="contoh: BBRI.JK (kosong = test BBRI, BMRI, BBCA)")
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--short", type=int, default=20)
    ap.add_argument("--long", type=int, default=50)
    ap.add_argument("--optimize", action="store_true",
                    help="pilih MA terbaik dari data in-sample lalu uji di out-of-sample")
    ap.add_argument("--outdir", default=".")
    a = ap.parse_args()

    daftar = [a.ticker] if a.ticker else TEST_TICKERS
    for t in daftar:
        run_backtest(t, a.start, a.end, a.short, a.long, a.outdir, a.optimize)


if __name__ == "__main__":
    main()
