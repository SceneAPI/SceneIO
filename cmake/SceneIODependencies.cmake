# Python (scikit-build-core provides the hints for the target interpreter and
# backports FindPython when CMake predates Development.SABIModule). Requiring
# both module targets makes the cp312 stable-ABI contract explicit: nanobind
# otherwise falls back to a CPython-version-specific extension without failing.
find_package(
  Python 3.12
  REQUIRED COMPONENTS
    Interpreter
    Development.Module
    Development.SABIModule)
if(NOT TARGET Python::SABIModule)
  message(FATAL_ERROR
    "SceneIO's cp312 stable-ABI build requires Python::SABIModule")
endif()
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

# libwebp 1.5.0 (BSD-3-Clause) — repository-contained upstream core source and
# CMake configuration. Keep upstream SIMD dispatch enabled, disable every tool
# and optional utility, and exclude the subdirectory from the parent ALL/install
# sets. The private static `webp` target pulls in `sharpyuv`.
set(libwebp_SOURCE_DIR "${PROJECT_SOURCE_DIR}/src/cpp/third_party/libwebp")
if(NOT EXISTS "${libwebp_SOURCE_DIR}/CMakeLists.txt" OR
   NOT EXISTS "${libwebp_SOURCE_DIR}/src/webp/decode.h" OR
   NOT EXISTS "${libwebp_SOURCE_DIR}/src/webp/encode.h" OR
   NOT EXISTS "${libwebp_SOURCE_DIR}/sharpyuv/sharpyuv.h" OR
   NOT EXISTS "${libwebp_SOURCE_DIR}/COPYING" OR
   NOT EXISTS "${libwebp_SOURCE_DIR}/PATENTS")
  message(FATAL_ERROR
    "Repository-contained libwebp 1.5.0 sources are incomplete")
endif()
foreach(_wopt WEBP_BUILD_ANIM_UTILS WEBP_BUILD_CWEBP WEBP_BUILD_DWEBP WEBP_BUILD_GIF2WEBP
        WEBP_BUILD_IMG2WEBP WEBP_BUILD_VWEBP WEBP_BUILD_WEBPINFO WEBP_BUILD_WEBPMUX
        WEBP_BUILD_EXTRAS WEBP_BUILD_WEBP_JS
        WEBP_BUILD_FUZZTEST)
  set(${_wopt} OFF CACHE BOOL "" FORCE)
endforeach()
set(WEBP_BUILD_LIBWEBPMUX ON CACHE BOOL "" FORCE)
set(WEBP_ENABLE_SIMD ON CACHE BOOL "" FORCE)
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
add_subdirectory(
  "${libwebp_SOURCE_DIR}"
  "${CMAKE_CURRENT_BINARY_DIR}/libwebp"
  EXCLUDE_FROM_ALL)
foreach(_webp_target
        sharpyuv
        webpdecode webpdspdecode webputilsdecode webpdecoder
        webpencode webpdsp webputils webp webpdemux libwebpmux)
  set_target_properties(
    ${_webp_target}
    PROPERTIES
      POSITION_INDEPENDENT_CODE ON
      C_VISIBILITY_PRESET hidden)
endforeach()

# libogg 1.3.6 and libtheora 1.2.0 (BSD-3-Clause) -- repository-contained
# upstream sources. libogg retains its upstream CMake configuration; Theora is
# built from the upstream portable C implementation so the same source set is
# valid on MSVC, GCC 10, and AppleClang/arm64. The codec remains private to
# `_core`; no development files or tools are installed.
set(libogg_SOURCE_DIR "${PROJECT_SOURCE_DIR}/src/cpp/third_party/ogg")
set(libtheora_SOURCE_DIR "${PROJECT_SOURCE_DIR}/src/cpp/third_party/theora")
if(NOT EXISTS "${libogg_SOURCE_DIR}/CMakeLists.txt" OR
   NOT EXISTS "${libogg_SOURCE_DIR}/include/ogg/ogg.h" OR
   NOT EXISTS "${libogg_SOURCE_DIR}/COPYING" OR
   NOT EXISTS "${libtheora_SOURCE_DIR}/include/theora/theoradec.h" OR
   NOT EXISTS "${libtheora_SOURCE_DIR}/include/theora/theoraenc.h" OR
   NOT EXISTS "${libtheora_SOURCE_DIR}/COPYING")
  message(FATAL_ERROR
    "Repository-contained libogg/libtheora sources are incomplete")
endif()
set(INSTALL_DOCS OFF CACHE BOOL "" FORCE)
set(INSTALL_PKG_CONFIG_MODULE OFF CACHE BOOL "" FORCE)
set(INSTALL_CMAKE_PACKAGE_MODULE OFF CACHE BOOL "" FORCE)
add_subdirectory(
  "${libogg_SOURCE_DIR}"
  "${CMAKE_CURRENT_BINARY_DIR}/libogg"
  EXCLUDE_FROM_ALL)
set_property(TARGET ogg PROPERTY POSITION_INDEPENDENT_CODE ON)
set_property(TARGET ogg PROPERTY C_VISIBILITY_PRESET hidden)

set(_sceneio_theora_sources
  ${libtheora_SOURCE_DIR}/lib/analyze.c
  ${libtheora_SOURCE_DIR}/lib/apiwrapper.c
  ${libtheora_SOURCE_DIR}/lib/bitpack.c
  ${libtheora_SOURCE_DIR}/lib/decapiwrapper.c
  ${libtheora_SOURCE_DIR}/lib/decinfo.c
  ${libtheora_SOURCE_DIR}/lib/decode.c
  ${libtheora_SOURCE_DIR}/lib/dequant.c
  ${libtheora_SOURCE_DIR}/lib/encapiwrapper.c
  ${libtheora_SOURCE_DIR}/lib/encfrag.c
  ${libtheora_SOURCE_DIR}/lib/encinfo.c
  ${libtheora_SOURCE_DIR}/lib/encode.c
  ${libtheora_SOURCE_DIR}/lib/enquant.c
  ${libtheora_SOURCE_DIR}/lib/fdct.c
  ${libtheora_SOURCE_DIR}/lib/fragment.c
  ${libtheora_SOURCE_DIR}/lib/huffdec.c
  ${libtheora_SOURCE_DIR}/lib/huffenc.c
  ${libtheora_SOURCE_DIR}/lib/idct.c
  ${libtheora_SOURCE_DIR}/lib/info.c
  ${libtheora_SOURCE_DIR}/lib/internal.c
  ${libtheora_SOURCE_DIR}/lib/mathops.c
  ${libtheora_SOURCE_DIR}/lib/mcenc.c
  ${libtheora_SOURCE_DIR}/lib/quant.c
  ${libtheora_SOURCE_DIR}/lib/rate.c
  ${libtheora_SOURCE_DIR}/lib/state.c
  ${libtheora_SOURCE_DIR}/lib/tokenize.c)
if(NOT MSVC AND CMAKE_SYSTEM_PROCESSOR MATCHES "^(x86_64|AMD64|amd64)$")
  list(APPEND _sceneio_theora_sources
    ${libtheora_SOURCE_DIR}/lib/x86/mmxencfrag.c
    ${libtheora_SOURCE_DIR}/lib/x86/mmxfdct.c
    ${libtheora_SOURCE_DIR}/lib/x86/mmxfrag.c
    ${libtheora_SOURCE_DIR}/lib/x86/mmxidct.c
    ${libtheora_SOURCE_DIR}/lib/x86/mmxstate.c
    ${libtheora_SOURCE_DIR}/lib/x86/sse2encfrag.c
    ${libtheora_SOURCE_DIR}/lib/x86/sse2fdct.c
    ${libtheora_SOURCE_DIR}/lib/x86/sse2idct.c
    ${libtheora_SOURCE_DIR}/lib/x86/x86cpu.c
    ${libtheora_SOURCE_DIR}/lib/x86/x86enc.c
    ${libtheora_SOURCE_DIR}/lib/x86/x86enquant.c
    ${libtheora_SOURCE_DIR}/lib/x86/x86state.c)
endif()
add_library(theora_static STATIC ${_sceneio_theora_sources})
if(NOT MSVC AND CMAKE_SYSTEM_PROCESSOR MATCHES "^(x86_64|AMD64|amd64)$")
  target_compile_definitions(
    theora_static PRIVATE OC_X86_ASM OC_X86_64_ASM)
endif()
target_include_directories(
  theora_static
  PUBLIC
    ${libtheora_SOURCE_DIR}/include
    ${libogg_SOURCE_DIR}/include
    ${CMAKE_CURRENT_BINARY_DIR}/libogg/include)
target_link_libraries(theora_static PUBLIC ogg)
if(NOT WIN32)
  target_link_libraries(theora_static PRIVATE m)
endif()
set_property(TARGET theora_static PROPERTY POSITION_INDEPENDENT_CODE ON)
set_property(TARGET theora_static PROPERTY C_VISIBILITY_PRESET hidden)
