"""
The authoritative LISFLOOD-FP .par keyword registry.

Generated from LISFLOOD-FP-code/pars.cpp -- every `read_*_param` call site, with
`//`-commented lines stripped (which is why `SGClevee` is absent: it is commented
out at pars.cpp:829 and the model does not accept it).

This exists because LISFLOOD-FP **silently ignores keywords it does not recognise**
(pars.cpp:1030). A typo such as `sim_tme` does not fail the run -- it makes the model
quietly fall back to the default and produce a plausible, wrong answer. Validating
against this registry turns that class of silent error into a loud one.

Keyword matching in the model is case-insensitive (STRCMPi), so lookups here are too,
but the canonical spelling is preserved for writing decks.
"""

from collections import namedtuple

K = namedtuple("K", "kind group help")

#: kind is one of: flag (no value), str, float, int
#: group is one of: files, run, solver, physics, subgrid, output, gpu, other
KEYWORDS = {
    '1Dfriction':                K('flag', 'physics', 'Use the 1D friction term.'),
    'acc_nugrid':                K('flag', 'gpu', 'Non-uniform grid acceleration solver. GPU only.'),
    'acceleration':              K('flag', 'solver', 'Local inertial (ACC) floodplain solver. The recommended default.'),
    'adaptoff':                  K('flag', 'solver', 'Original Qlim formulation with a fixed timestep.'),
    'ascheader':                 K('str', 'files', 'Six-line replacement ASCII header for outputs.'),
    'ascii_out':                 K('flag', 'output', 'ASCII raster output. Forced on if no format is selected.'),
    'bcifile':                   K('str', 'files', 'Boundary condition locations (.bci).'),
    'bdyfile':                   K('str', 'files', 'Time varying boundary data (.bdy).'),
    'binary_out':                K('flag', 'output', 'Binary raster output.'),
    'binarystartfile':           K('str', 'files', 'Initial condition as a LISFLOOD binary raster.'),
    'calcarea':                  K('flag', 'output', 'Track flooded area.'),
    'calcmeandepth':             K('flag', 'output', 'Track mean depth.'),
    'calcvolume':                K('flag', 'output', 'Track volume.'),
    'cfl':                       K('float', 'physics', 'CFL number. Default 0.7 for acceleration.'),
    'ch_dynamic':                K('flag', 'solver', 'Full dynamic steady-state channel initialisation.'),
    'ch_start_h':                K('float', 'physics', 'Uniform channel starting depth, m.'),
    'chainageoff':               K('flag', 'physics', 'Disable chainage calculation.'),
    'chanmask':                  K('str', 'files', 'Channel mask grid (>0 = masked).'),
    'checkpoint':                K('float', 'run', 'Checkpoint every N hours of wall-clock time. Default 1.0 if no value given.'),
    'comp_out':                  K('flag', 'run', 'Print computation time estimates to stdout.'),
    'cuda':                      K('flag', 'gpu', 'Run the GPU version. Requires a CUDA build.'),
    'damfile':                   K('str', 'files', 'Dam parameter table.'),
    'dammask':                   K('str', 'files', 'Dam mask grid (cell value = dam id).'),
    'debug':                     K('flag', 'run', 'Write additional debug grids.'),
    'DEMfile':                   K('str', 'files', 'Ground elevation ASCII grid. Required; defines the domain geometry.'),
    'depthoff':                  K('flag', 'output', 'Disable water depth (.wd) output.'),
    'depththresh':               K('float', 'physics', 'Wet/dry depth threshold, m.'),
    'dg2':                       K('flag', 'solver', 'Second-order discontinuous Galerkin solver. Needs DG2 slope preprocessing.'),
    'dg2depththresh':            K('float', 'gpu', 'DG2 depth threshold. Requires dg2.'),
    'dg2thindepth_tstep':        K('float', 'gpu', 'DG2 thin depth timestep. Requires dg2.'),
    'dhlin':                     K('float', 'physics', 'Linearisation depth.'),
    'diffusive':                 K('flag', 'solver', 'Diffusive 1D channel solver.'),
    'diffusive_froude_thresh':   K('float', 'physics', 'Froude threshold to switch to diffusive.'),
    'dir':                       K('str', 'run', 'Alias for dirroot.'),
    'dirroot':                   K('str', 'run', "Results directory. Pre-create it to avoid the model's unquoted mkdir."),
    'dist_routing':              K('flag', 'solver', 'Slope dependent routing velocity.'),
    'drain_nodata':              K('flag', 'physics', 'Remove water arriving in NODATA cells.'),
    'drycheckoff':               K('flag', 'physics', 'Disable the dry checking routine.'),
    'dynamicrainfile':           K('str', 'files', 'NetCDF spatio-temporal rainfall. Requires a NetCDF-enabled build.'),
    'dynsw':                     K('flag', 'solver', 'Alias for ch_dynamic.'),
    'elevoff':                   K('flag', 'output', 'Disable water surface elevation (.elev) output.'),
    'epsilon':                   K('float', 'gpu', 'Adaptation error threshold (adaptive GPU solvers).'),
    'evaporation':               K('str', 'files', 'Evaporation time series, mm/day.'),
    'fpfric':                    K('float', 'physics', "Uniform floodplain Manning's n. Default 0.06."),
    'fv1':                       K('flag', 'solver', 'First-order finite volume 2D shallow water solver.'),
    'fv2':                       K('flag', 'gpu', 'FV2 solver. GPU only.'),
    'gaugefile':                 K('str', 'files', 'Virtual discharge gauge sections.'),
    'gravity':                   K('float', 'physics', 'Gravitational acceleration.'),
    'gzip':                      K('flag', 'run', 'gzip each output via an unquoted shell call. The plugin blocks this.'),
    'hazard':                    K('flag', 'output', 'Write the full hazard grid set.'),
    'htol':                      K('float', 'physics', 'Channel solver depth tolerance.'),
    'hwfv1':                     K('flag', 'gpu', 'Adaptive HWFV1 solver. GPU only, with a separate .par dialect.'),
    'inf':                       K('float', 'physics', 'Alias for infiltration.'),
    'infilfile':                 K('str', 'files', 'Spatially distributed infiltration grid, in mm/hr.'),
    'infiltration':              K('float', 'physics', 'Uniform infiltration rate, m/s.'),
    'initial_tstep':             K('float', 'run', 'Initial and maximum timestep, seconds.'),
    'kill':                      K('float', 'run', 'Abort the run after N hours of wall-clock time. Exits cleanly, writing final outputs.'),
    'krivodonovathresh':         K('float', 'gpu', 'Krivodonova shock detector threshold.'),
    'L':                         K('int', 'gpu', 'Maximum refinement level (adaptive GPU solvers).'),
    'latlong':                   K('flag', 'physics', 'Lat/long grid. Only valid with the subgrid model.'),
    'limitslopes':               K('flag', 'gpu', 'Slope limiter. Requires dg2/fv2/mwdg2.'),
    'linklist':                  K('str', 'files', 'Explicit subgrid-to-2D link list.'),
    'loadcheck':                 K('str', 'files', 'Explicit checkpoint file to restart from.'),
    'log':                       K('flag', 'run', 'Redirect stdout to a log file. The plugin blocks this: it hides run progress.'),
    'manningfile':               K('str', 'files', "Floodplain Manning's n grid. NODATA cells fall back to fpfric."),
    'massint':                   K('float', 'run', 'Mass balance / stage write interval, seconds. Drives plugin progress resolution.'),
    'max_Froude':                K('float', 'physics', 'Cap velocity by Froude number. Needs a _CALCULATE_Q_MODE=1 build.'),
    'maxdepthonly':              K('flag', 'output', 'Write only the maximum depth grid.'),
    'maxint':                    K('float', 'run', 'Interval to write and reset the max depth grid (subgrid path only).'),
    'mint_hk':                   K('flag', 'physics', 'Update max/time grids only at massint (faster).'),
    'momentumthresh':            K('float', 'physics', 'Momentum threshold.'),
    'multiriverfile':            K('str', 'files', 'List of .river files.'),
    'mwdg2':                     K('flag', 'gpu', 'Adaptive MWDG2 solver. GPU only, with a separate .par dialect.'),
    'netcdf_out':                K('flag', 'output', 'NetCDF output. Requires a NetCDF-enabled build.'),
    'nfp':                       K('float', 'physics', 'Alias for fpfric.'),
    'nodata_elevation':          K('float', 'physics', 'Elevation substituted for DEM NODATA cells. Default 1e7.'),
    'output_precision':          K('int', 'output', 'Decimal places in ASCII rasters. Default 3.'),
    'overpass':                  K('float', 'run', 'Single overpass output time, seconds.'),
    'overpassfile':              K('str', 'files', 'List of satellite overpass times (seconds).'),
    'porfile':                   K('str', 'files', 'Porosity file.'),
    'profiles':                  K('flag', 'output', 'Write channel profile files.'),
    'Qfile':                     K('str', 'files', 'Parsed but unused by the model.'),
    'qlimfact':                  K('float', 'physics', 'Relax the Q limit by this factor.'),
    'qloutput':                  K('flag', 'output', 'Write flow limiter grids.'),
    'qoutput':                   K('flag', 'output', 'Write discharge grids (.Qx/.Qy). These are edge-centred.'),
    'rainfall':                  K('str', 'files', 'Uniform rainfall time series, mm/hr. A time series, not a raster.'),
    'rainfallmask':              K('str', 'files', 'Distributed rainfall multiplier grid. Header must match the DEM exactly.'),
    'rainfallrouting':           K('str', 'files', 'Legacy: rainfall time series plus routing enabled.'),
    'resettimeinit':             K('float', 'run', 'Reset time-of-initial-inundation at this time, seconds.'),
    'resroot':                   K('str', 'run', 'Results filename prefix. Default "res".'),
    'riverfile':                 K('str', 'files', '1D channel network (.river).'),
    'Roe':                       K('flag', 'solver', 'Full 2D shallow water Roe solver.'),
    'Roe_slow':                  K('flag', 'solver', 'Ghost-cell variant of the Roe solver.'),
    'routesfthresh':             K('float', 'physics', 'Slope at which routing replaces the shallow water solution.'),
    'routing':                   K('flag', 'solver', 'Shallow flow routing. Requires acceleration or the subgrid model.'),
    'routing_mass_check':        K('flag', 'solver', 'Routing with a per-cell mass check (slower).'),
    'routingspeed':              K('float', 'physics', 'Routing velocity, m/s.'),
    'saveint':                   K('float', 'run', 'Raster save interval, seconds.'),
    'saveint_max':               K('flag', 'run', 'Write and reset max depth at each saveint.'),
    'SGC2':                      K('float', 'subgrid', 'Additional shape parameter.'),
    'SGC_enable':                K('flag', 'subgrid', 'Enable the optimised subgrid path without channels. Forces acceleration.'),
    'SGCa':                      K('float', 'subgrid', 'Upstream catchment area exponent.'),
    'SGCA_mode':                 K('flag', 'subgrid', 'Interpret p as bank-full area.'),
    'SGCbank':                   K('str', 'files', 'Sub-grid channel bank elevation grid (m).'),
    'SGCbed':                    K('str', 'files', 'Sub-grid channel bed elevation grid (m).'),
    'SGCbfh_mode':               K('flag', 'subgrid', 'Interpret p as bank-full depth.'),
    'SGCcat_area':               K('str', 'files', 'Upstream catchment area grid.'),
    'SGCchan':                   K('int', 'subgrid', 'Channel cross-section type. 1 = rectangular.'),
    'SGCchangroup':              K('str', 'files', 'Integer grid of sub-grid parameter group id per cell.'),
    'SGCchanprams':              K('str', 'files', 'Table of sub-grid channel parameter groups.'),
    'SGCd8':                     K('flag', 'subgrid', 'Use D8 sub-grid flow directions.'),
    'SGCdirnfile':               K('str', 'files', 'Sub-grid channel flow direction grid (integer valued).'),
    'SGCm':                      K('float', 'subgrid', 'Meander coefficient (clamped to <= 1).'),
    'SGCmanningfile':            K('str', 'files', "Sub-grid channel Manning's n grid. NODATA falls back to SGCn."),
    'SGCn':                      K('float', 'subgrid', "Sub-grid channel Manning's n."),
    'SGCp':                      K('float', 'subgrid', 'Width-to-depth exponent. Setting this enables the subgrid model.'),
    'SGCr':                      K('float', 'subgrid', 'Width-to-depth multiplier. Setting this enables the subgrid model.'),
    'SGCs':                      K('float', 'subgrid', 'Shape exponent.'),
    'SGCvoutput':                K('flag', 'subgrid', 'Output sub-grid channel velocities.'),
    'SGCwidth':                  K('str', 'files', 'Sub-grid channel width grid (m). Enables the subgrid model and forces acceleration.'),
    'sim_time':                  K('float', 'run', 'Simulation duration, seconds.'),
    'simtime':                   K('float', 'run', 'Alias for sim_time.'),
    'stagefile':                 K('str', 'files', 'Stage (point) output locations.'),
    'standard_extensions_out':   K('flag', 'output', 'Append .asc/.bin to output filenames.'),
    'startelev':                 K('flag', 'physics', 'Treat startfile as water surface elevation rather than depth.'),
    'startfile':                 K('str', 'files', 'Initial water depth grid (or water surface elevation if startelev is set).'),
    'startq':                    K('flag', 'physics', 'Initialise channel depth from steady state discharge.'),
    'startq2d':                  K('flag', 'physics', 'Also load startfile .Qx/.Qy (FV1/DG2).'),
    'steady':                    K('flag', 'run', 'Stop early when steady state is reached.'),
    'steadytol':                 K('float', 'run', 'Steady state discharge tolerance.'),
    'theta':                     K('float', 'physics', 'Acceleration scheme theta.'),
    'toutput':                   K('flag', 'output', 'Write adaptive timestep grids.'),
    'ts_multiple':               K('int', 'physics', 'Channel runs at N times the floodplain timestep.'),
    'tstart':                    K('float', 'run', 'Start time, seconds.'),
    'voutput':                   K('flag', 'output', 'Write velocity grids (.Vx/.Vy).'),
    'voutput_max':               K('flag', 'output', 'Write maximum velocity grids.'),
    'voutput_stage':             K('flag', 'output', 'Write velocity at stage points only.'),
    'vtkoff':                    K('flag', 'output', 'Disable VTK output.'),
    'weir':                      K('str', 'files', 'Alias for weirfile.'),
    'weirfile':                  K('str', 'files', 'Weir / bridge / culvert file.'),
}

#: Aliases the model accepts for the same setting. Canonical spelling first.
ALIASES = {
    "dir": "dirroot",
    "nfp": "fpfric",
    "simtime": "sim_time",
    "weir": "weirfile",
    "dynsw": "ch_dynamic",
    "inf": "infiltration",
}

#: Keywords the plugin refuses to write, with the reason shown to the user.
DENIED = {
    "log": (
        "`log` redirects the model's stdout to a file, which hides run progress "
        "and error messages from the plugin. The plugin keeps its own log instead."
    ),
    "gzip": (
        "`gzip` is applied through an unquoted shell call in the model, which "
        "breaks on paths containing spaces. Compress the results afterwards instead."
    ),
}

#: Solvers and options that need a CUDA build. Unavailable on macOS.
GPU_ONLY = frozenset(
    k for k, v in KEYWORDS.items() if v.group == "gpu"
) | {"cuda"}

_LOWER = {k.lower(): k for k in KEYWORDS}


def canonical(name):
    """Return the canonical spelling of *name*, or None if it is not a keyword."""
    key = _LOWER.get(name.lower())
    if key is None:
        return None
    return ALIASES.get(key, key)


def is_keyword(name):
    return name.lower() in _LOWER


def lookup(name):
    """Return the K record for *name*, or None."""
    key = _LOWER.get(name.lower())
    return KEYWORDS[key] if key else None


def suggest(name, n=3):
    """Closest real keywords to a probable typo, best first."""
    import difflib
    return difflib.get_close_matches(name.lower(), list(_LOWER), n=n, cutoff=0.7)
