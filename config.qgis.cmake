# Build configuration used by the QGIS plugin's "Build LISFLOOD-FP executable" step.
# Mirrors config.default.cmake. Selected via -D_CONFIG=<this file> (CMakeLists.txt:10),
# so the source tree's own config.default.cmake is left untouched.
#
# _NETCDF is flipped to 1 by the ENABLE_NETCDF option; it is only needed for the
# `netcdf_out` keyword and `dynamicrainfile`. Off by default to keep the build lean.
set(_NETCDF 0)
add_compile_definitions(_NUMERIC_MODE=1)    # 1 = double precision
add_compile_definitions(_ONLY_RECT=1)       # rectangular subgrid channels only
add_compile_definitions(_PROFILE_MODE=0)
add_compile_definitions(_DISABLE_WET_DRY=0)
add_compile_definitions(_CALCULATE_Q_MODE=1)  # required for the max_Froude keyword
add_compile_definitions(_SGM_BY_BLOCKS=0)
add_compile_definitions(_BALANCE_TYPE=0)
