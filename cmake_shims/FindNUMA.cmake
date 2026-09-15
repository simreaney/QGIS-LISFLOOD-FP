# Shim: libnuma does not exist on macOS.
#
# LISFLOOD-FP's CMakeLists.txt does `if (UNIX) find_package(NUMA REQUIRED)`, and
# CMake's UNIX is true on macOS, so the stock build hard-fails at configure time.
#
# This is safe: the only NUMA code (lisflood2/lisflood_processing.cpp:1729-1744)
# sits behind `#ifdef __unix__`, and Apple clang defines only __APPLE__/__MACH__,
# never __unix__. So no NUMA symbol is ever compiled on macOS.
#
# Leaving the INCLUDE_DIRS/LIBRARIES variables unset makes the two consuming
# target_* calls expand to zero arguments, which is a well-formed no-op.
#
# Selected via -DCMAKE_MODULE_PATH=<this dir>, which CMakeLists.txt:23 appends to
# rather than overwrites, so this is searched first and the source tree stays clean.
set(NUMA_FOUND TRUE)
unset(NUMA_INCLUDE_DIRS)
unset(NUMA_LIBRARIES)
