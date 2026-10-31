import os
from datetime import datetime

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import pandas as pd


def _resolve_output_path(output_dir=None, output_name=None):
    output_dir = output_dir or os.path.join(os.getcwd(), "output")
    os.makedirs(output_dir, exist_ok=True)

    if output_name is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_name = f"supercoins_report_{timestamp}.xlsx"

    return os.path.join(output_dir, output_name)


def analyze_products(products, output_dir=None, output_name=None):

    df = pd.DataFrame(products)

    if df.empty:
        return df

    df["supercoins"] = pd.to_numeric(
        df["supercoins"], errors="coerce"
    )

    df = df.sort_values(
        "supercoins",
        ascending=False,
        na_position="last"
    )

    output_path = _resolve_output_path(output_dir=output_dir, output_name=output_name)

    try:
        df.to_excel(output_path, index=False)
        print(f"Saved Excel snapshot: {output_path}")
    except Exception as exc:
        print(f"Could not write Excel report because the file is open elsewhere or the write failed: {output_path}")
        print(f"Write error: {exc}")
        backup_name = output_name or os.path.basename(output_path)
        backup_name = backup_name.replace(".xlsx", "_backup.xlsx")
        backup_path = os.path.join(os.path.dirname(output_path), backup_name)
        try:
            df.to_excel(backup_path, index=False)
            print(f"Saved backup report to: {backup_path}")
        except Exception as backup_exc:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            fallback_path = os.path.join(
                os.path.dirname(output_path),
                f"supercoins_report_fallback_{timestamp}.xlsx",
            )
            df.to_excel(fallback_path, index=False)
            print(f"Saved fallback report to: {fallback_path}")
            print(f"Backup write error: {backup_exc}")

    return df