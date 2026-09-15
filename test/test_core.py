"""Headless tests for the QGIS-free core. Run with any Python 3.9+, no QGIS needed."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import bc, gridio, keywords as kw
from core.par import ParFile
from core.progress import classify, MassProgress
from core.results import died_on_signal, discover


def test_keyword_registry():
    assert kw.canonical("SIM_TIME") == "sim_time"      # case-insensitive
    assert kw.canonical("dir") == "dirroot"            # alias resolves
    assert kw.canonical("nfp") == "fpfric"
    assert kw.canonical("SGClevee") is None            # commented out in pars.cpp
    assert "sim_time" in kw.suggest("sim_tme")
    assert "log" in kw.DENIED and "gzip" in kw.DENIED


def test_discharge_conversion_roundtrip():
    # the model multiplies by cellsize, so the deck value is per metre
    assert bc.to_model_discharge(100.0, 50.0) == 2.0
    assert bc.to_model_discharge(100.0, 50.0, 4) == 0.5
    assert abs(bc.from_model_discharge(bc.to_model_discharge(73.0, 25.0), 25.0) - 73.0) < 1e-9


def test_bdy_writes_value_before_time():
    d = tempfile.mkdtemp()
    s = bc.Series("inflow", "seconds", [0, 3600], [10.0, 50.0])
    rows = open(bc.write_bdy(os.path.join(d, "a.bdy"), [s])).read().splitlines()
    assert rows[0].startswith("#")          # exactly one skipped comment line
    assert rows[1] == "inflow"
    assert rows[2] == "2\tseconds"
    assert rows[3].split() == ["10", "0"]   # value first, then time
    assert rows[4].split() == ["50", "3600"]


def test_series_validation_catches_the_traps():
    bad_time = bc.Series("q", "seconds", [0, 100, 100], [1, 2, 3])
    assert any("non-increasing" in p for p in bc.validate_series(bad_time))
    bad_units = bc.Series("q", "hrs", [0, 1], [1, 2])
    assert any("not recognised" in p for p in bc.validate_series(bad_units))
    short = bc.Series("q", "seconds", [0, 10], [1, 2])
    assert any(p.startswith("WARN") for p in bc.validate_series(short, sim_time=1000))


def test_cross_validate_catches_name_mismatch():
    s = [bc.Series("Inflow", "seconds", [0, 1], [1, 2])]
    p = [bc.PointBC(1, 2, "QVAR", None, "inflow")]        # differs only in case
    assert any("not in the .bdy" in m for m in bc.cross_validate(p, [], s))


def test_grid_geometry():
    assert_dem = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                              "LISFLOOD-FP-code", "testing", "T001_buscot",
                              "buscot.dem.ascii")
    if os.path.exists(assert_dem):
        spec = gridio.read_header(assert_dem)
        assert (spec.ncols, spec.nrows, spec.cellsize) == (76, 48, 50.0)
        assert gridio.qx_spec(spec).ncols == spec.ncols + 1
        assert gridio.qy_spec(spec).nrows == spec.nrows + 1
    try:
        gridio.spec_from_geotransform((0, 50, 0, 1000, 0, -25), 10, 10)
        assert False, "non-square cells must be rejected"
    except gridio.NonSquareCellsError:
        pass


def test_par_validation():
    p = ParFile()
    p._entries["sim_tme"] = "3600"       # typo
    p._entries["DEMfile"] = "my dem.asc" # space in path
    p._entries["log"] = None             # denied
    p._entries["routing"] = None         # needs acceleration/SGC
    msgs = [str(i) for i in p.validate()]
    assert any("sim_time" in m for m in msgs)
    assert any("space" in m for m in msgs)
    assert any("log" in m for m in msgs)
    assert any("routing" in m for m in msgs)


def test_par_roundtrip():
    d = tempfile.mkdtemp()
    p = ParFile().set("DEMfile", "dem.asc").set("sim_time", 1000).set("acceleration")
    path = p.write(os.path.join(d, "m.par"))
    q = ParFile.parse(path)
    assert q.get("DEMfile") == "dem.asc"
    assert q.get("sim_time") == "1000"
    assert q.has("acceleration")


def test_progress_classification():
    k, d = classify("T(mins): M: 500.0, C: 5.3, M/C: 94.94, ETot: 17.6, EFin: 12.3")
    assert k == "progress" and d["efin"] == 12.3
    k, d = classify("Unknown parameter ignored: sim_tme.")
    assert k == "warn" and d["keyword"] == "sim_tme"
    assert classify("ERROR: Loading DEM. Aborting.")[0] == "error"


def test_signal_detection():
    assert died_on_signal(139) and died_on_signal(-11)
    assert not died_on_signal(0) and not died_on_signal(1)


def test_qvar_series_needs_conversion_too():
    """Regression: a QVAR series carries discharge in the .bdy and must be converted.

    Converting only the QFIX point value leaves QVAR hydrographs raw, and the model
    multiplies them by the cell size -- an end-to-end run asking for 40 m3/s delivered
    400 m3/s on a 10 m grid. Nothing in the model reports this.
    """
    cellsize = 10.0
    hydrograph = [0.0, 40.0, 0.0]                       # m3/s, as a user thinks of it
    converted = [bc.to_model_discharge(q, cellsize) for q in hydrograph]
    assert converted == [0.0, 4.0, 0.0]
    # what the model then applies internally is value * cellsize
    assert [v * cellsize for v in converted] == hydrograph


def test_edge_series_conversion_uses_cell_count():
    spec = gridio.GridSpec(60, 60, 0.0, 0.0, 10.0, -9999.0)
    n = bc.edge_cell_count("W", 0.0, 600.0, spec)
    assert n == 60
    # 40 m3/s spread over the whole 60-cell edge
    assert bc.to_model_discharge(40.0, spec.cellsize, n) == 40.0 / 600.0


def test_lowest_edge_cell_ignores_interior_minimum():
    # row 0 = north edge, row (nrows-1) = south edge, col 0 = west, col (ncols-1) = east
    elev = [
        [10,   9,   8,   7, 6],
        [5,  100, 0.5, 100, 5],
        [5,  100, 100, 100, 5],
        [4,   3,   1,   3, 4],
    ]
    spec = gridio.GridSpec(ncols=5, nrows=4, xll=0.0, yll=0.0, cellsize=10.0, nodata=-9999.0)
    # 0.5 is the lowest cell in the whole grid but sits in the interior, where
    # LISFLOOD-FP cannot apply a boundary condition at all -- must be ignored.
    assert bc.lowest_edge_cell(spec, elev, spec.nodata) == ("S", 3, 2)


def test_lowest_edge_cell_skips_nodata():
    elev = [
        [-9999, -9999, -9999],
        [-9999,     5, -9999],   # interior, non-nodata but must still be ignored
        [-9999,     1, -9999],   # south edge, the only real candidate
    ]
    spec = gridio.GridSpec(ncols=3, nrows=3, xll=0.0, yll=0.0, cellsize=1.0, nodata=-9999.0)
    assert bc.lowest_edge_cell(spec, elev, spec.nodata) == ("S", 2, 1)


def test_lowest_edge_cell_all_nodata_returns_none():
    elev = [[-9999, -9999], [-9999, -9999]]
    spec = gridio.GridSpec(ncols=2, nrows=2, xll=0.0, yll=0.0, cellsize=1.0, nodata=-9999.0)
    assert bc.lowest_edge_cell(spec, elev, spec.nodata) is None


def test_outflow_edge_bc_geometry_matches_cell():
    spec = gridio.GridSpec(ncols=5, nrows=4, xll=0.0, yll=0.0, cellsize=10.0, nodata=-9999.0)
    all_valid = [[0.0] * spec.ncols for _ in range(spec.nrows)]
    # south edge, column 2 -> x in [20, 30)
    single = bc.outflow_edge_bc(spec, "S", 3, 2, all_valid, spec.nodata, width=1)
    assert (single.edge, single.start, single.finish, single.type) == ("S", 20.0, 30.0, "FREE")
    assert single.value is None and single.series is None   # local water-surface slope

    # widening keeps it centred on the same cell
    wide = bc.outflow_edge_bc(spec, "S", 3, 2, all_valid, spec.nodata, width=3)
    assert (wide.start, wide.finish) == (10.0, 40.0)

    # west edge, row 1 (north-to-south indexing) -> y in [20, 30)
    west = bc.outflow_edge_bc(spec, "W", 1, 0, all_valid, spec.nodata, width=1)
    assert (west.start, west.finish) == (20.0, 30.0)


def test_outflow_edge_bc_does_not_widen_into_nodata():
    """Regression: widening used to walk into NODATA by index alone.

    LISFLOOD-FP turns a NODATA DEM cell into a ~1e7 m wall (nodata_elevation), so an
    opening that silently included one wasn't the width it claimed to be -- part of
    it was a dam. The window must stop at the edge of the real data instead.
    """
    spec = gridio.GridSpec(ncols=6, nrows=1, xll=0.0, yll=0.0, cellsize=10.0, nodata=-9999.0)
    # south == only row here; valid data only at columns 2 and 3
    elev = [[-9999, -9999, 5.0, 4.0, -9999, -9999]]
    bc_edge = bc.outflow_edge_bc(spec, "S", 0, 3, elev, spec.nodata, width=4)
    # requested 4 cells, but only 2 (columns 2-3, x in [20, 40)) are real data
    assert (bc_edge.start, bc_edge.finish) == (20.0, 40.0)
    assert bc.edge_cell_count("S", bc_edge.start, bc_edge.finish, spec) == 2


def test_par_blocks_gpu_keywords_without_cuda():
    p = ParFile()
    p._entries["cuda"] = None
    msgs = [str(i) for i in p.validate(caps={"cuda": False})]
    assert any("CUDA" in m for m in msgs)


# --- 1D channel network -----------------------------------------------------

def test_river_reproduces_reference_structure():
    """The writer must match the hand-authored CTBranchFine network exactly."""
    from core.river import point as P, write_river, validate
    segs = [
        [P(0, 5050, 1000, 0.035, 10, "QFIX", 200.0),
         P(4050, 5050, bctype="TRIB", bcvalue=1),
         P(8050, 5050, bctype="TRIB", bcvalue=2),
         P(10000, 5050, 1000, 0.035, 0, "HFIX", 0.929)],
        [P(0, 9050, 1000, 0.035, 14, "QFIX", 200.0), P(4050, 9050),
         P(4050, 5050, 1000, 0.035, 6, "QOUT", 0)],
        [P(2050, 1050, 1000, 0.035, 9.65685, "QFIX", 200.0), P(4050, 1050),
         P(6050, 3050, 1000, 0.035, 4.82843, "TRIB", 3),
         P(8050, 5050, 1000, 0.035, 2, "QOUT", 0)],
        [P(10000, 1050, 1000, 0.035, 9.65685, "QFIX", 200.0), P(8050, 1050),
         P(6050, 3050, 1000, 0.035, 4.82843, "QOUT", 2)],
    ]
    assert validate(segs) == []
    d = tempfile.mkdtemp()
    lines = open(write_river(os.path.join(d, "t.river"), segs)).read().splitlines()
    assert lines[0] == "Tribs 4"
    assert lines[1] == "4"                     # segment 0 point count
    assert lines[2].split()[2:] == ["1000", "0.035", "10", "QFIX", "200"]
    assert lines[3].split()[2:] == ["TRIB", "1"]       # no geometry, BC only
    assert lines[6] == "3"                     # segment 1 point count


def test_river_file_ends_with_newline():
    """The reader scans to '\\n' with fgetc, so a missing final newline overruns."""
    from core.river import point as P, write_river
    d = tempfile.mkdtemp()
    path = write_river(os.path.join(d, "t.river"),
                       [[P(0, 0, 10, 0.03, 5, "QFIX", 1.0), P(50, 0, 10, 0.03, 4)]])
    assert open(path, "rb").read().endswith(b"\n")


def test_river_rejects_unanswered_junction():
    from core.river import point as P, validate
    segs = [[P(0, 0, 10, 0.03, 5, "QFIX", 10.0), P(100, 0, 10, 0.03, 4, "QOUT", 1)],
            [P(0, 100, 10, 0.03, 5, "QFIX", 10.0), P(200, 200, 10, 0.03, 4, "HFIX", 1.0)]]
    problems = validate(segs)
    assert any("no point at those coordinates" in p for p in problems)


def test_river_rejects_bad_segment_reference():
    from core.river import point as P, validate
    segs = [[P(0, 0, 10, 0.03, 5, "QFIX", 1.0), P(50, 0, 10, 0.03, 4, "QOUT", 7)]]
    assert any("only 1 segments" in p for p in validate(segs))


def test_river_rejects_partial_geometry():
    from core.river import point as P, RiverError
    try:
        P(0, 0, width=10)                      # n and bed missing
        assert False, "partial cross-section geometry must be rejected"
    except RiverError:
        pass


def test_channel_discharge_is_not_converted():
    """Channel Q is m3/s; only .bci discharge is per metre of cell width."""
    from core.river import point as P, format_point
    line = format_point(P(0, 0, 20, 0.035, 10, "QFIX", 30.0))
    assert line.split()[-2:] == ["QFIX", "30"]     # written through unchanged
