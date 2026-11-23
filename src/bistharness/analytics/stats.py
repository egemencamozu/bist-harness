"""Small deterministic statistics toolkit shared by every scenario (pure, no IO).

Conventions: inputs are 1-D sequences of floats; NaN values are dropped (pairwise for two-sample/paired functions).
Every function returns None fields instead of raising when the sample is too small, so callers can report
INSUFFICIENT_SAMPLE instead of crashing. Randomised procedures take an explicit seed (default 42).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy import stats as sps

ArrayLike = Sequence[float] | np.ndarray


def _clean(x: ArrayLike) -> np.ndarray:
    a = np.asarray(x, dtype=float)
    return a[~np.isnan(a)]


def _pairs(x: ArrayLike, y: ArrayLike) -> tuple[np.ndarray, np.ndarray]:
    a, b = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if a.shape != b.shape:
        raise ValueError("x and y must have the same length")
    ok = ~(np.isnan(a) | np.isnan(b))
    return a[ok], b[ok]


def _f(v: float) -> float | None:
    return None if v is None or not math.isfinite(v) else float(v)


@dataclass(frozen=True)
class Summary:
    n: int
    mean: float | None
    median: float | None
    std: float | None  # sample standard deviation (ddof=1)
    min: float | None
    max: float | None
    positive_rate: float | None  # share of values > 0


def summarize(x: ArrayLike) -> Summary:
    a = _clean(x)
    n = len(a)
    if n == 0:
        return Summary(0, None, None, None, None, None, None)
    return Summary(
        n=n,
        mean=_f(a.mean()),
        median=_f(float(np.median(a))),
        std=_f(a.std(ddof=1)) if n > 1 else None,
        min=_f(a.min()),
        max=_f(a.max()),
        positive_rate=_f(float((a > 0).mean())),
    )


@dataclass(frozen=True)
class TestResult:
    method: str
    n: int
    statistic: float | None
    p_value: float | None  # two-sided


def t_test_mean(x: ArrayLike, mu: float = 0.0) -> TestResult:
    """One-sample two-sided t-test of mean == mu (closed form, equal to scipy.stats.ttest_1samp)."""
    a = _clean(x)
    n = len(a)
    if n < 2:
        return TestResult("one_sample_t", n, None, None)
    sd = float(a.std(ddof=1))
    if sd == 0.0:
        return TestResult("one_sample_t", n, None, None)
    t = (float(a.mean()) - mu) / (sd / math.sqrt(n))
    return TestResult("one_sample_t", n, _f(t), _f(2 * float(sps.t.sf(abs(t), n - 1))))


def welch_t_test(x: ArrayLike, y: ArrayLike) -> TestResult:
    """Two-sided Welch t-test of mean(x) == mean(y); n is len(x) (closed form, equal to scipy's equal_var=False)."""
    a, b = _clean(x), _clean(y)
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return TestResult("welch_t", na, None, None)
    va, vb = float(a.var(ddof=1)) / na, float(b.var(ddof=1)) / nb
    if va + vb == 0.0:
        return TestResult("welch_t", na, None, None)
    t = (float(a.mean()) - float(b.mean())) / math.sqrt(va + vb)
    df = (va + vb) ** 2 / (va**2 / (na - 1) + vb**2 / (nb - 1))
    return TestResult("welch_t", na, _f(t), _f(2 * float(sps.t.sf(abs(t), df))))


def binomial_test(k: int, n: int, p0: float) -> TestResult:
    """Exact two-sided binomial test of success probability == p0 (statistic = observed rate)."""
    if n <= 0 or not 0.0 < p0 < 1.0:
        return TestResult("binomial_exact", n, None, None)
    r = sps.binomtest(int(k), int(n), float(p0))
    return TestResult("binomial_exact", n, _f(k / n), _f(r.pvalue))


def wilson_interval(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float] | None:
    """Wilson score interval for a proportion (default 95%)."""
    if n <= 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def bootstrap_mean_ci(
    x: ArrayLike, *, n_boot: int = 2000, alpha: float = 0.05, seed: int = 42
) -> tuple[float, float] | None:
    """Percentile bootstrap CI of the mean (deterministic for a fixed seed)."""
    a = _clean(x)
    if len(a) < 2:
        return None
    rng = np.random.default_rng(seed)
    means = a[rng.integers(0, len(a), size=(n_boot, len(a)))].mean(axis=1)
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return (float(lo), float(hi))


def permutation_test_mean_diff(x: ArrayLike, y: ArrayLike, *, n_perm: int = 5000, seed: int = 42) -> TestResult:
    """Two-sided permutation test of mean(x) - mean(y) (labels shuffled, deterministic for a fixed seed)."""
    a, b = _clean(x), _clean(y)
    if len(a) < 1 or len(b) < 1:
        return TestResult("permutation_mean_diff", len(a), None, None)
    observed = a.mean() - b.mean()
    pooled = np.concatenate([a, b])
    rng = np.random.default_rng(seed)
    hits = 0
    for _ in range(n_perm):
        p = rng.permutation(pooled)
        if abs(p[: len(a)].mean() - p[len(a) :].mean()) >= abs(observed) - 1e-15:
            hits += 1
    return TestResult("permutation_mean_diff", len(a), _f(observed), (hits + 1) / (n_perm + 1))


def bonferroni(p_values: Sequence[float | None]) -> list[float | None]:
    m = sum(p is not None for p in p_values)
    return [None if p is None else min(1.0, p * m) for p in p_values]


def benjamini_hochberg(p_values: Sequence[float | None]) -> list[float | None]:
    """BH-adjusted p-values (step-up, monotone), None entries are ignored and kept as None."""
    idx = [i for i, p in enumerate(p_values) if p is not None]
    m = len(idx)
    out: list[float | None] = [None] * len(p_values)
    if m == 0:
        return out
    order = sorted(idx, key=lambda i: (p_values[i], i))
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        p = p_values[i]
        assert p is not None
        running = min(running, p * m / rank)
        out[i] = min(1.0, running)
    return out


@dataclass(frozen=True)
class Correlation:
    n: int
    pearson: float | None
    pearson_p: float | None
    spearman: float | None
    spearman_p: float | None


def correlation(x: ArrayLike, y: ArrayLike) -> Correlation:
    a, b = _pairs(x, y)
    if len(a) < 3 or a.std() == 0 or b.std() == 0:
        return Correlation(len(a), None, None, None, None)
    pr = sps.pearsonr(a, b)
    sr = sps.spearmanr(a, b)
    return Correlation(len(a), _f(pr.statistic), _f(pr.pvalue), _f(sr.statistic), _f(sr.pvalue))


@dataclass(frozen=True)
class OLS:
    n: int
    beta: float | None
    alpha: float | None
    r2: float | None
    beta_se: float | None


def ols_beta(y: ArrayLike, x: ArrayLike) -> OLS:
    """Simple regression y = alpha + beta * x."""
    yy, xx = _pairs(y, x)
    n = len(xx)
    if n < 3 or xx.var() == 0:
        return OLS(n, None, None, None, None)
    xm, ym = xx.mean(), yy.mean()
    sxx = float(((xx - xm) ** 2).sum())
    beta = float(((xx - xm) * (yy - ym)).sum()) / sxx
    alpha = ym - beta * xm
    resid = yy - alpha - beta * xx
    sst = float(((yy - ym) ** 2).sum())
    r2 = 1 - float((resid**2).sum()) / sst if sst > 0 else None
    se = math.sqrt(float((resid**2).sum()) / (n - 2) / sxx)
    return OLS(n, _f(beta), _f(alpha), _f(r2) if r2 is not None else None, _f(se))


def greedy_non_overlapping(positions: Sequence[int], gap: int) -> int:
    """How many events remain when each kept event blocks the next `gap` positions (independent-sample count)."""
    kept, last = 0, None
    for p in sorted(positions):
        if last is None or p - last >= gap:
            kept += 1
            last = p
    return kept
