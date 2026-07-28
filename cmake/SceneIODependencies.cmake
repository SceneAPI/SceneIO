# Python (scikit-build-core provides the hints for the target interpreter).
# CMake 3.18 supplies Development.Module and FetchContent SOURCE_SUBDIR, both
# used by the stable native build.
find_package(Python 3.12 REQUIRED COMPONENTS Interpreter Development.Module)
find_package(Threads REQUIRED)

# Locate the pip-installed nanobind and load its CMake package.
execute_process(
  COMMAND "${Python_EXECUTABLE}" -m nanobind --cmake_dir
  OUTPUT_STRIP_TRAILING_WHITESPACE
  OUTPUT_VARIABLE nanobind_ROOT)
find_package(nanobind CONFIG REQUIRED)

# STABLE_ABI -> a single abi3 wheel across CPython >= 3.12 (D1/D4 in
# docs/io_implementation_plan.md); NB_STATIC links nanobind statically so the
# wheel has no extra runtime .so/.dll to ship.
# miniz 3.0.2 (MIT) — repository-contained gzip/ZIP inflate/deflate for SPZ,
# SOG, NPZ, and TinyEXR. Build the pinned amalgamation directly instead of
# configuring upstream's project.
set(miniz_SOURCE_DIR "${PROJECT_SOURCE_DIR}/src/cpp/third_party/miniz")
if(NOT EXISTS "${miniz_SOURCE_DIR}/miniz.c" OR
   NOT EXISTS "${miniz_SOURCE_DIR}/miniz.h")
  message(FATAL_ERROR
    "Repository-contained miniz 3.0.2 sources are incomplete")
endif()
add_library(miniz_static STATIC "${miniz_SOURCE_DIR}/miniz.c")
target_include_directories(miniz_static PUBLIC "${miniz_SOURCE_DIR}")
set_target_properties(
  miniz_static
  PROPERTIES
    POSITION_INDEPENDENT_CODE ON
    C_VISIBILITY_PRESET hidden)

# libwebp remains the final R6 source-closure unit using FetchContent until its
# exact selected sources move under src/cpp/third_party/.
include(FetchContent)

# nlohmann/json 3.11.3 (MIT), header-only — repository-contained multi-header
# source for the JSON codecs. Recreate the selected upstream interface target
# without configuring its install rules, tests, or alternate amalgamation.
set(nlohmann_json_SOURCE_DIR
  "${PROJECT_SOURCE_DIR}/src/cpp/third_party/nlohmann_json")
if(NOT EXISTS "${nlohmann_json_SOURCE_DIR}/include/nlohmann/json.hpp" OR
   NOT EXISTS "${nlohmann_json_SOURCE_DIR}/LICENSE.MIT")
  message(FATAL_ERROR
    "Repository-contained nlohmann/json 3.11.3 sources are incomplete")
endif()
add_library(nlohmann_json INTERFACE)
add_library(nlohmann_json::nlohmann_json ALIAS nlohmann_json)
target_compile_features(nlohmann_json INTERFACE cxx_std_11)
target_include_directories(
  nlohmann_json INTERFACE "${nlohmann_json_SOURCE_DIR}/include")

# zstd 1.5.6 (BSD-3-Clause) — repository-contained compression library for
# the SPZ v4 (NGSP) container. Configure the exact selected upstream CMake
# project and build only its static library.
set(zstd_SOURCE_DIR "${PROJECT_SOURCE_DIR}/src/cpp/third_party/zstd")
if(NOT EXISTS "${zstd_SOURCE_DIR}/lib/zstd.h" OR
   NOT EXISTS "${zstd_SOURCE_DIR}/cmake/upstream/CMakeLists.txt" OR
   NOT EXISTS "${zstd_SOURCE_DIR}/LICENSE")
  message(FATAL_ERROR
    "Repository-contained zstd 1.5.6 sources are incomplete")
endif()
set(ZSTD_BUILD_SHARED OFF CACHE BOOL "" FORCE)
set(ZSTD_BUILD_STATIC ON CACHE BOOL "" FORCE)
set(ZSTD_BUILD_COMPRESSION ON CACHE BOOL "" FORCE)
set(ZSTD_BUILD_DECOMPRESSION ON CACHE BOOL "" FORCE)
set(ZSTD_BUILD_DICTBUILDER ON CACHE BOOL "" FORCE)
set(ZSTD_BUILD_DEPRECATED OFF CACHE BOOL "" FORCE)
set(ZSTD_BUILD_PROGRAMS OFF CACHE BOOL "" FORCE)
set(ZSTD_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(ZSTD_BUILD_CONTRIB OFF CACHE BOOL "" FORCE)
set(ZSTD_LEGACY_SUPPORT OFF CACHE BOOL "" FORCE)
set(ZSTD_MULTITHREAD_SUPPORT ON CACHE BOOL "" FORCE)
add_subdirectory(
  "${zstd_SOURCE_DIR}/cmake/upstream"
  "${CMAKE_BINARY_DIR}/_deps/zstd-build"
  EXCLUDE_FROM_ALL)
set_target_properties(
  libzstd_static
  PROPERTIES
    POSITION_INDEPENDENT_CODE ON
    C_VISIBILITY_PRESET hidden)

# fast_float 6.1.6 (MIT option), header-only — repository-contained portable
# float parsing for the text codecs. std::from_chars<double> is unavailable on
# manylinux2014 (GCC 10) and older libc++ (macOS), so the wheels use this exact
# selected multi-header tree on every platform.
set(fast_float_SOURCE_DIR
  "${PROJECT_SOURCE_DIR}/src/cpp/third_party/fast_float")
if(NOT EXISTS "${fast_float_SOURCE_DIR}/include/fast_float/fast_float.h")
  message(FATAL_ERROR
    "Repository-contained fast_float source is missing: "
    "${fast_float_SOURCE_DIR}")
endif()
add_library(fast_float INTERFACE)
add_library(FastFloat::fast_float ALIAS fast_float)
target_include_directories(
  fast_float INTERFACE "${fast_float_SOURCE_DIR}/include")
target_compile_features(fast_float INTERFACE cxx_std_11)
if(MSVC_VERSION GREATER 1910)
  target_compile_options(fast_float INTERFACE /permissive-)
endif()

# LAZperf 3.4.0 (Apache-2.0/BSD-3-Clause/BSD-2-Clause) —
# repository-contained LASzip-compatible LAZ compression/decompression. Build
# exactly the 15 selected library translation units; upstream tools, tests,
# benchmarks, install rules, and test-data downloads are not configured.
set(lazperf_SOURCE_DIR
  "${PROJECT_SOURCE_DIR}/src/cpp/third_party/lazperf")
if(NOT EXISTS "${lazperf_SOURCE_DIR}/cpp/lazperf/lazperf.hpp" OR
   NOT EXISTS "${lazperf_SOURCE_DIR}/cpp/lazperf/detail/field_point14.cpp" OR
   NOT EXISTS "${lazperf_SOURCE_DIR}/COPYING")
  message(FATAL_ERROR
    "Repository-contained LAZperf 3.4.0 sources are incomplete")
endif()
set(LAZPERF_SOURCES
  "${lazperf_SOURCE_DIR}/cpp/lazperf/charbuf.cpp"
  "${lazperf_SOURCE_DIR}/cpp/lazperf/detail/field_byte10.cpp"
  "${lazperf_SOURCE_DIR}/cpp/lazperf/detail/field_byte14.cpp"
  "${lazperf_SOURCE_DIR}/cpp/lazperf/detail/field_gpstime10.cpp"
  "${lazperf_SOURCE_DIR}/cpp/lazperf/detail/field_nir14.cpp"
  "${lazperf_SOURCE_DIR}/cpp/lazperf/detail/field_point10.cpp"
  "${lazperf_SOURCE_DIR}/cpp/lazperf/detail/field_point14.cpp"
  "${lazperf_SOURCE_DIR}/cpp/lazperf/detail/field_rgb10.cpp"
  "${lazperf_SOURCE_DIR}/cpp/lazperf/detail/field_rgb14.cpp"
  "${lazperf_SOURCE_DIR}/cpp/lazperf/filestream.cpp"
  "${lazperf_SOURCE_DIR}/cpp/lazperf/header.cpp"
  "${lazperf_SOURCE_DIR}/cpp/lazperf/lazperf.cpp"
  "${lazperf_SOURCE_DIR}/cpp/lazperf/readers.cpp"
  "${lazperf_SOURCE_DIR}/cpp/lazperf/vlr.cpp"
  "${lazperf_SOURCE_DIR}/cpp/lazperf/writers.cpp")
add_library(lazperf_static STATIC ${LAZPERF_SOURCES})
target_include_directories(lazperf_static PUBLIC "${lazperf_SOURCE_DIR}/cpp")
target_compile_definitions(lazperf_static
  PUBLIC LAZPERF_VENDORED
  PRIVATE
    $<$<PLATFORM_ID:Windows>:WIN32_LEAN_AND_MEAN>
    $<$<CXX_COMPILER_ID:MSVC>:_CRT_SECURE_NO_WARNINGS>)
set_target_properties(
  lazperf_static
  PROPERTIES
    POSITION_INDEPENDENT_CODE ON
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN ON)
if(WIN32)
  target_link_libraries(lazperf_static PUBLIC ws2_32)
endif()
# lodepng (zlib license) — PNG codec. Vendored in-repo at
# src/cpp/third_party/lodepng (COMMIT.txt pins the source); it has its own
# self-contained inflate/deflate (lodepng_*-prefixed, no miniz interaction), so
# it builds as a tiny static lib with no external deps. LODEPNG_NO_COMPILE_DISK
# drops the fopen paths (bytes-only API); hidden visibility keeps its symbols out
# of _core's export table.
add_library(lodepng_static STATIC src/cpp/third_party/lodepng/lodepng.cpp)
target_include_directories(lodepng_static PUBLIC src/cpp/third_party/lodepng)
target_compile_definitions(lodepng_static PUBLIC LODEPNG_NO_COMPILE_DISK)
set_property(TARGET lodepng_static PROPERTY POSITION_INDEPENDENT_CODE ON)
set_property(TARGET lodepng_static PROPERTY CXX_VISIBILITY_PRESET hidden)

# SQLite (public domain) -- the in-repo 3.53.4 amalgamation is pinned in
# third_party/sqlite/COMMIT.txt. Keep the database engine private and omit
# surfaces SceneIO does not use; COLMAP reads still retain normal locking and
# read-only enforcement, while writes use rollback-capable transactions.
add_library(sqlite_static STATIC src/cpp/third_party/sqlite/sqlite3.c)
target_include_directories(sqlite_static PUBLIC src/cpp/third_party/sqlite)
target_compile_definitions(sqlite_static PRIVATE
  SQLITE_DQS=0
  SQLITE_DEFAULT_MEMSTATUS=0
  SQLITE_OMIT_DEPRECATED
  SQLITE_OMIT_LOAD_EXTENSION)
set_property(TARGET sqlite_static PROPERTY POSITION_INDEPENDENT_CODE ON)
set_property(TARGET sqlite_static PROPERTY C_VISIBILITY_PRESET hidden)

# libwebp (BSD) — WebP codec, built from source (all its command-line tools OFF so
# only the core encode/decode static libs compile). Link the in-tree `webp` target
# (NOT `WebP::webp`, which only exists via find_package — the fast_float alias
# lesson); it pulls in `sharpyuv` itself.
foreach(_wopt WEBP_BUILD_ANIM_UTILS WEBP_BUILD_CWEBP WEBP_BUILD_DWEBP WEBP_BUILD_GIF2WEBP
        WEBP_BUILD_IMG2WEBP WEBP_BUILD_VWEBP WEBP_BUILD_WEBPINFO WEBP_BUILD_WEBPMUX
        WEBP_BUILD_LIBWEBPMUX WEBP_BUILD_EXTRAS WEBP_BUILD_FUZZTEST)
  set(${_wopt} OFF CACHE BOOL "" FORCE)
endforeach()
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)  # static webp linked into _core
FetchContent_Declare(libwebp
  URL https://github.com/webmproject/libwebp/archive/refs/tags/v1.5.0.tar.gz)
FetchContent_MakeAvailable(libwebp)
set_property(TARGET webp PROPERTY POSITION_INDEPENDENT_CODE ON)
set_property(TARGET sharpyuv PROPERTY POSITION_INDEPENDENT_CODE ON)
