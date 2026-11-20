"""Formats that are read by turning them into a table first, then profiled like any CSV.

  xls / ods          spreadsheets (xlrd / odfpy), one worksheet at a time
  stata / sas        .dta, .sas7bdat, .xpt (pandas, no extra package)
  spss               .sav / .zsav (pyreadstat: in the Docker worker; not in the Vercel bundle, which is near its size limit)
  netcdf / hdf5      scientific arrays: NetCDF-3 (scipy), NetCDF-4 and HDF5 (h5py). Variables that share a length become
                     columns; a gridded variable (time x lat x lon) becomes a long table with one row per cell.
  xmltable           an XML file of repeated records (<row>...</row>), read with the standard-library parser

A sample reads only the first rows wherever the format allows it.
"""
from __future__ import annotations

from pathlib import Path

from ..fetch import FetchError

LABELS = {"xls": "Excel 97-2003", "ods": "OpenDocument spreadsheet", "stata": "Stata", "sas": "SAS", "spss": "SPSS",
          "netcdf": "NetCDF", "hdf5": "HDF5", "xmltable": "XML records"}
_NEEDS = {"xls": ("xlrd", "xlrd"), "ods": ("odf", "odfpy"), "spss": ("pyreadstat", "pyreadstat"), "hdf5": ("h5py", "h5py")}
MAX_CELLS = 20_000_000  # a gridded variable bigger than this is subsampled (every n-th cell), and the report says so


def _need(kind: str) -> None:
    mod, pkg = _NEEDS.get(kind, (None, None))
    if not mod:
        return
    import importlib.util

    if importlib.util.find_spec(mod) is None:
        raise FetchError(f"{LABELS[kind]} files need the {pkg} package, which this deployment doesn't include. Run it with the Docker "
                         f"worker (it has {pkg}), or save the file as CSV or Excel (.xlsx) and upload that.", "format")


def sheets(path: Path, kind: str) -> list[str]:
    import pandas as pd

    _need(kind)
    with pd.ExcelFile(path, engine={"xls": "xlrd", "ods": "odf"}[kind]) as xf:
        return [str(s) for s in xf.sheet_names]


def to_csv(path: Path, kind: str, *, sheet: str | None = None, row_limit: int | None = None, log=lambda line: None) -> tuple[Path, dict]:
    """Convert to CSV next to the file. Returns (csv path, notes for the report)."""
    _need(kind)
    out = path.with_name(path.name + ".csv")
    notes: dict = {"converted_from": LABELS.get(kind, kind)}
    try:
        df, extra = _frame(path, kind, sheet=sheet, row_limit=row_limit, log=log)
    except FetchError:
        raise
    except Exception as exc:
        raise FetchError(f"Couldn't read {path.name} as {LABELS.get(kind, kind)}: {type(exc).__name__}: {exc}", "format") from exc
    if df is None or df.empty or not len(df.columns):
        raise FetchError(f"{path.name} has no rows that can be read as a table.", "not_data")
    notes.update(extra)
    df.to_csv(out, index=False)
    log(f"Converted {LABELS.get(kind, kind)} to a table: {len(df):,} rows x {len(df.columns)} columns")
    return out, notes


def _frame(path: Path, kind: str, *, sheet, row_limit, log):
    import pandas as pd

    if kind in ("xls", "ods"):
        return pd.read_excel(path, sheet_name=sheet if sheet is not None else 0, engine={"xls": "xlrd", "ods": "odf"}[kind],
                             nrows=row_limit), {}
    if kind == "stata":
        if row_limit:
            with pd.read_stata(path, chunksize=row_limit, convert_categoricals=True) as it:
                return next(iter(it)), {}
        return pd.read_stata(path), {}
    if kind == "sas":
        fmt = "xport" if path.name.lower().endswith(".xpt") else "sas7bdat"
        enc = "infer" if fmt == "sas7bdat" else "latin-1"  # "infer" reads the encoding stored in sas7bdat; XPORT has none
        if fmt == "xport" and b"LIBV8" in path.open("rb").read(80):  # SAS transport v8: pandas reads only v5
            import importlib.util

            if importlib.util.find_spec("pyreadstat") is None:
                raise FetchError("This is a SAS transport file version 8, which needs pyreadstat (in the Docker worker). Export it as "
                                 "version 5 (.xpt), sas7bdat or CSV, or run it with the worker.", "format")
            import pyreadstat

            df, _meta = pyreadstat.read_xport(str(path), row_limit=row_limit or 0)
            return df, {}
        if row_limit:
            with pd.read_sas(path, format=fmt, chunksize=row_limit, encoding=enc) as it:
                return next(iter(it)), {}
        return pd.read_sas(path, format=fmt, encoding=enc), {}
    if kind == "spss":
        import pyreadstat

        df, _meta = pyreadstat.read_sav(str(path), row_limit=row_limit or 0, apply_value_formats=True)
        return df, {}
    if kind == "xmltable":
        return xml_table(path, row_limit=row_limit), {}
    if kind in ("netcdf", "hdf5"):
        return arrays_table(path, row_limit=row_limit, log=log)
    raise FetchError(f"No converter for {kind}.", "format")


# ---------------------------------------------------------------- XML records
def xml_table(path: Path, *, row_limit: int | None = None):
    """The most repeated element under the root, one row each, children/attributes as columns. None if it isn't record-like."""
    import xml.etree.ElementTree as ET
    from collections import Counter

    import pandas as pd

    root = ET.parse(path).getroot()

    def tag(e):
        return e.tag.rsplit("}", 1)[-1]

    candidates = [root, *list(root)[:50]]
    best, best_n = None, 0
    for parent in candidates:
        counts = Counter(tag(c) for c in parent)
        if counts:
            name, n = counts.most_common(1)[0]
            if n > best_n:
                best, best_n = (parent, name), n
    if not best or best_n < 2:
        return None
    parent, name = best
    rows = []
    for el in parent:
        if tag(el) != name:
            continue
        row = {f"@{k.rsplit('}', 1)[-1]}": v for k, v in el.attrib.items()}
        for c in el:
            if len(c) == 0:
                row[tag(c)] = (c.text or "").strip()
            for k, v in c.attrib.items():
                row[f"{tag(c)}@{k.rsplit('}', 1)[-1]}"] = v
        if not row and (el.text or "").strip():
            row[name] = el.text.strip()
        rows.append(row)
        if row_limit and len(rows) >= row_limit:
            break
    df = pd.DataFrame(rows)
    for c in df.columns:  # numbers stay numbers; text columns are left alone
        try:
            df[c] = pd.to_numeric(df[c])
        except (ValueError, TypeError):
            pass
    return df


def is_xml_table(path: Path) -> bool:
    try:
        df = xml_table(path, row_limit=50)
    except Exception:
        return False
    return df is not None and len(df) >= 2 and len(df.columns) >= 1


# ---------------------------------------------------------------- NetCDF / HDF5
def _variables(path: Path):
    """name -> (array-like, attrs, dims or None). NetCDF-3 via scipy; NetCDF-4/HDF5 via h5py."""
    with open(path, "rb") as fh:
        head = fh.read(8)
    if head[:3] == b"CDF":
        from scipy.io import netcdf_file

        nc = netcdf_file(str(path), "r", mmap=False, maskandscale=True)
        return {k: (v.data, dict(v._attributes), tuple(v.dimensions)) for k, v in nc.variables.items()}, nc.close
    _need("hdf5")
    import h5py

    f = h5py.File(path, "r")
    out = {}

    def visit(name, obj):
        if isinstance(obj, h5py.Dataset) and obj.shape and obj.dtype.kind in "biufcSUOV" and not name.split("/")[-1].startswith("_nc"):
            dims = None
            if "DIMENSION_LIST" in obj.attrs:
                try:
                    dims = tuple(f[ref[0]].name.rsplit("/", 1)[-1] for ref in obj.attrs["DIMENSION_LIST"])
                except Exception:
                    dims = None
            out[name] = (obj, {k: obj.attrs[k] for k in obj.attrs if k not in ("DIMENSION_LIST", "REFERENCE_LIST")}, dims)

    f.visititems(visit)
    return out, f.close


def _clean(arr, attrs: dict):
    import numpy as np

    a = np.asarray(arr)
    if a.dtype.kind == "S":
        return np.char.decode(a, "utf-8", errors="replace")
    if a.dtype.kind in "iuf":
        fill = attrs.get("_FillValue", attrs.get("missing_value"))
        scale, offset = attrs.get("scale_factor"), attrs.get("add_offset")
        if fill is not None or scale is not None or offset is not None:
            a = a.astype("float64")
            if fill is not None:
                a[a == np.asarray(fill).ravel()[0]] = np.nan
            if scale is not None:
                a = a * float(np.asarray(scale).ravel()[0])
            if offset is not None:
                a = a + float(np.asarray(offset).ravel()[0])
    return a


def arrays_table(path: Path, *, row_limit: int | None = None, log=lambda line: None):
    import numpy as np
    import pandas as pd

    variables, close = _variables(path)
    try:
        if not variables:
            raise FetchError(f"{path.name} has no data variables.", "not_data")
        # 1. A compound (record) dataset is already a table, e.g. HDF5 tables written by PyTables or pandas.
        compound = [(k, v) for k, (v, _a, _d) in variables.items() if getattr(v, "dtype", None) is not None and v.dtype.names and len(v.shape) == 1]
        if compound:
            name, ds = max(compound, key=lambda kv: kv[1].shape[0])
            data = ds[: row_limit] if row_limit else ds[()]
            df = pd.DataFrame.from_records(np.asarray(data))
            for c in df.columns:
                if df[c].dtype == object and len(df) and isinstance(df[c].iloc[0], bytes):
                    df[c] = df[c].str.decode("utf-8", errors="replace")
            return df, {"array_layout": f"records from {name}", "variables": len(variables)}
        shapes = {k: tuple(v.shape) for k, (v, _a, _d) in variables.items()}
        biggest = max(variables, key=lambda k: int(np.prod(shapes[k])))
        nd = len(shapes[biggest])
        # 2. Gridded data: the largest variable with 2+ dimensions, and every variable on the same grid, become one long table.
        if nd >= 2:
            grid = shapes[biggest]
            on_grid = [k for k in variables if shapes[k] == grid and variables[k][0].dtype.kind in "biuf"]
            dims = variables[biggest][2] or tuple(f"dim_{i}" for i in range(nd))
            cells = int(np.prod(grid))
            step = max(1, -(-cells // MAX_CELLS))
            if row_limit:
                step = max(step, -(-cells // max(1, row_limit)))
            idx = np.arange(0, cells, step)
            if row_limit:
                idx = idx[:row_limit]
            coords = np.unravel_index(idx, grid)
            df = pd.DataFrame()
            for i, d in enumerate(dims):
                coord = variables.get(d) or next((variables[k] for k in variables if k.rsplit("/", 1)[-1] == d), None)
                if coord is not None and tuple(coord[0].shape) == (grid[i],):
                    df[d] = _clean(coord[0][()], coord[1])[coords[i]]
                else:
                    df[d] = coords[i]
            for k in on_grid[:40]:
                flat = _clean(variables[k][0][()], variables[k][1]).reshape(-1)
                df[k.rsplit("/", 1)[-1]] = flat[idx]
            note = f"every {step:,}th of {cells:,} grid cells" if step > 1 else f"all {cells:,} grid cells"
            log(f"Gridded variable {biggest} {grid}: read {note}")
            return df, {"array_layout": f"grid {biggest} {list(grid)} ({note})", "variables": len(variables)}
        # 3. Series: the most common 1-D length; every variable of that length is a column.
        from collections import Counter

        lengths = Counter(shapes[k][0] for k in variables if len(shapes[k]) == 1 and shapes[k][0] > 1)
        if not lengths:
            raise FetchError(f"{path.name} has only single values, no series to tabulate.", "not_data")
        n = lengths.most_common(1)[0][0]
        take = slice(0, min(n, row_limit) if row_limit else n)
        df = pd.DataFrame({k.rsplit("/", 1)[-1]: _clean(variables[k][0][take], variables[k][1])
                           for k in variables if shapes[k] == (n,)})
        return df, {"array_layout": f"{len(df.columns)} variables of length {n:,}", "variables": len(variables)}
    finally:
        try:
            close()
        except Exception:
            pass
