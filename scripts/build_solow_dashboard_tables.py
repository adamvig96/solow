#!/usr/bin/env python3
"""
Build Solow growth decomposition tables for dashboard consumption.

Outputs:
- mart_growth_yoy.csv
- mart_growth_cumulative.csv
- qa_summary.json
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

COUNTRY_TOTAL_CODE = "TOT"
INDUSTRY_SECTION_PATTERN = r"[A-U]"
METHOD_VERSION = "solow_v1"


@dataclass(frozen=True)
class OutputPaths:
    yoy: Path
    cumulative: Path
    qa: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build YoY and cumulative Solow decomposition tables."
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Directory containing EU KLEMS CSV files (default: %(default)s).",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs/solow_dashboard",
        help="Directory where output tables are written (default: %(default)s).",
    )
    return parser.parse_args()


def get_output_paths(output_dir: Path) -> OutputPaths:
    return OutputPaths(
        yoy=output_dir / "mart_growth_yoy.csv",
        cumulative=output_dir / "mart_growth_cumulative.csv",
        qa=output_dir / "qa_summary.json",
    )


def load_base_panel(data_dir: Path) -> pd.DataFrame:
    national_path = data_dir / "national_accounts.csv"
    capital_path = data_dir / "capital_accounts.csv"

    national_cols = [
        "nace_r2_code",
        "geo_code",
        "geo_name",
        "nace_r2_name",
        "year",
        "COMP",
        "VA_CP",
        "VA_Q",
        "H_EMP",
    ]
    capital_cols = ["nace_r2_code", "geo_code", "year", "Kq_GFCF"]

    national = pd.read_csv(
        national_path,
        usecols=national_cols,
        dtype={"nace_r2_code": "string", "geo_code": "string"},
    )
    capital = pd.read_csv(
        capital_path,
        usecols=capital_cols,
        dtype={"nace_r2_code": "string", "geo_code": "string"},
    )

    panel = national.merge(
        capital, on=["geo_code", "nace_r2_code", "year"], how="inner", validate="1:1"
    )
    panel = panel.loc[panel["geo_code"].str.len() == 2].copy()
    panel["year"] = panel["year"].astype(int)
    return panel


def build_country_series(panel: pd.DataFrame) -> pd.DataFrame:
    country = panel.loc[panel["nace_r2_code"] == COUNTRY_TOTAL_CODE].copy()
    country = country.rename(columns={"geo_code": "country_code", "geo_name": "country_name"})
    country["industry_code"] = pd.Series([pd.NA] * len(country), dtype="string")
    country["industry_name"] = pd.Series([pd.NA] * len(country), dtype="string")
    country["series_type"] = "country_macro"
    return country


def build_country_industry_series(panel: pd.DataFrame) -> pd.DataFrame:
    industry = panel.loc[panel["nace_r2_code"].str.fullmatch(INDUSTRY_SECTION_PATTERN)].copy()
    industry = industry.rename(columns={"geo_code": "country_code", "geo_name": "country_name"})
    industry["industry_code"] = industry["nace_r2_code"].astype("string")
    industry["industry_name"] = industry["nace_r2_name"].astype("string")
    industry["series_type"] = "country_industry"
    return industry


def compute_alpha(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    out["labor_share_raw"] = np.where(out["VA_CP"] > 0, out["COMP"] / out["VA_CP"], np.nan)
    out.loc[out["COMP"] < 0, "labor_share_raw"] = np.nan
    out["alpha_observed"] = (1.0 - out["labor_share_raw"]).clip(0.0, 1.0)

    out["series_key"] = out["industry_code"].fillna("__COUNTRY__")
    series_median = out.groupby(["country_code", "series_key"])["alpha_observed"].transform(
        "median"
    )
    country_year_median = out.groupby(["country_code", "year"])["alpha_observed"].transform(
        "median"
    )
    global_median = float(out["alpha_observed"].median(skipna=True))

    out["alpha"] = out["alpha_observed"]
    out["alpha_source"] = np.where(out["alpha_observed"].notna(), "observed", "missing")

    fill_series = out["alpha"].isna() & series_median.notna()
    out.loc[fill_series, "alpha"] = series_median[fill_series]
    out.loc[fill_series, "alpha_source"] = "series_median"

    fill_country_year = out["alpha"].isna() & country_year_median.notna()
    out.loc[fill_country_year, "alpha"] = country_year_median[fill_country_year]
    out.loc[fill_country_year, "alpha_source"] = "country_year_median"

    fill_global = out["alpha"].isna()
    out.loc[fill_global, "alpha"] = global_median
    out.loc[fill_global, "alpha_source"] = "global_median"

    return out


def compute_yoy(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out = out.sort_values(["country_code", "series_key", "year"]).reset_index(drop=True)
    grp = out.groupby(["country_code", "series_key"], sort=False)

    for src_col, dst_col in [("VA_Q", "g_y"), ("Kq_GFCF", "g_k"), ("H_EMP", "g_l")]:
        lag_col = f"{src_col}_lag"
        out[lag_col] = grp[src_col].shift(1)
        out[dst_col] = np.nan
        valid = (out[src_col] > 0) & (out[lag_col] > 0)
        out.loc[valid, dst_col] = 100.0 * (
            np.log(out.loc[valid, src_col]) - np.log(out.loc[valid, lag_col])
        )

    out = out.drop(columns=["VA_Q_lag", "Kq_GFCF_lag", "H_EMP_lag"])

    alpha_lag = grp["alpha"].shift(1)
    out["alpha_avg"] = np.where(alpha_lag.notna(), 0.5 * (out["alpha"] + alpha_lag), out["alpha"])
    out["alpha_avg"] = out["alpha_avg"].clip(0.0, 1.0)

    valid_decomp = (
        out["g_y"].notna() & out["g_k"].notna() & out["g_l"].notna() & out["alpha_avg"].notna()
    )
    out["contrib_k"] = np.where(valid_decomp, out["alpha_avg"] * out["g_k"], np.nan)
    out["contrib_l"] = np.where(valid_decomp, (1.0 - out["alpha_avg"]) * out["g_l"], np.nan)
    out["contrib_tfp"] = np.where(
        valid_decomp, out["g_y"] - out["contrib_k"] - out["contrib_l"], np.nan
    )
    out["residual"] = np.where(
        valid_decomp,
        out["g_y"] - (out["contrib_k"] + out["contrib_l"] + out["contrib_tfp"]),
        np.nan,
    )

    yoy = out.loc[valid_decomp].copy()
    yoy["method_version"] = METHOD_VERSION
    return yoy


def compute_cumulative(yoy: pd.DataFrame) -> pd.DataFrame:
    out = yoy.copy()
    out = out.sort_values(["country_code", "series_key", "year"]).reset_index(drop=True)
    grp = out.groupby(["country_code", "series_key"], sort=False)

    first_yoy_year = grp["year"].transform("min")
    out["base_year"] = first_yoy_year - 1

    out["cum_g_y"] = grp["g_y"].cumsum()
    out["cum_contrib_k"] = grp["contrib_k"].cumsum()
    out["cum_contrib_l"] = grp["contrib_l"].cumsum()
    out["cum_contrib_tfp"] = grp["contrib_tfp"].cumsum()
    out["cum_residual"] = out["cum_g_y"] - (
        out["cum_contrib_k"] + out["cum_contrib_l"] + out["cum_contrib_tfp"]
    )

    out["method_version"] = METHOD_VERSION
    return out


def select_yoy_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "country_code",
        "country_name",
        "industry_code",
        "industry_name",
        "series_type",
        "year",
        "alpha",
        "alpha_avg",
        "alpha_source",
        "g_y",
        "g_k",
        "g_l",
        "contrib_k",
        "contrib_l",
        "contrib_tfp",
        "residual",
        "method_version",
    ]
    return df.loc[:, cols].copy()


def select_cumulative_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "country_code",
        "country_name",
        "industry_code",
        "industry_name",
        "series_type",
        "base_year",
        "year",
        "cum_g_y",
        "cum_contrib_k",
        "cum_contrib_l",
        "cum_contrib_tfp",
        "cum_residual",
        "method_version",
    ]
    return df.loc[:, cols].copy()


def build_qa_summary(yoy: pd.DataFrame, cumulative: pd.DataFrame) -> Dict[str, object]:
    alpha_source_counts = (
        yoy["alpha_source"].value_counts(dropna=False).sort_index().to_dict()  # type: ignore[arg-type]
    )

    yoy_max_abs_residual = float(yoy["residual"].abs().max())
    cumulative_max_abs_residual = float(cumulative["cum_residual"].abs().max())

    summary: Dict[str, object] = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "method_version": METHOD_VERSION,
        "rows": {
            "yoy_total": int(len(yoy)),
            "yoy_country_macro": int((yoy["series_type"] == "country_macro").sum()),
            "yoy_country_industry": int((yoy["series_type"] == "country_industry").sum()),
            "cumulative_total": int(len(cumulative)),
        },
        "coverage": {
            "countries_in_yoy": int(yoy["country_code"].nunique()),
            "industries_in_yoy": int(yoy.loc[yoy["industry_code"].notna(), "industry_code"].nunique()),
            "years_min": int(yoy["year"].min()),
            "years_max": int(yoy["year"].max()),
        },
        "alpha_source_counts": alpha_source_counts,
        "identity_checks": {
            "yoy_max_abs_residual": yoy_max_abs_residual,
            "cumulative_max_abs_residual": cumulative_max_abs_residual,
        },
    }
    return summary


def write_outputs(paths: OutputPaths, yoy: pd.DataFrame, cumulative: pd.DataFrame, qa: Dict[str, object]) -> None:
    paths.yoy.parent.mkdir(parents=True, exist_ok=True)
    yoy.to_csv(paths.yoy, index=False)
    cumulative.to_csv(paths.cumulative, index=False)
    paths.qa.write_text(json.dumps(qa, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    paths = get_output_paths(output_dir)

    base_panel = load_base_panel(data_dir)
    country = build_country_series(base_panel)
    industry = build_country_industry_series(base_panel)
    model_input = pd.concat([country, industry], ignore_index=True)

    with_alpha = compute_alpha(model_input)
    yoy = compute_yoy(with_alpha)
    cumulative = compute_cumulative(yoy)

    yoy_out = select_yoy_columns(yoy)
    cumulative_out = select_cumulative_columns(cumulative)
    qa = build_qa_summary(yoy_out, cumulative_out)
    write_outputs(paths, yoy_out, cumulative_out, qa)

    print(f"[DONE] Wrote {len(yoy_out):,} YoY rows to {paths.yoy}")
    print(f"[DONE] Wrote {len(cumulative_out):,} cumulative rows to {paths.cumulative}")
    print(f"[DONE] Wrote QA summary to {paths.qa}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
