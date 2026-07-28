# SceneIO extension and native-control targets.
#
# Dependency targets and source manifests must already exist before this file
# is included.

nanobind_add_module(_core STABLE_ABI NB_STATIC
  ${SCENEIO_CORE_SOURCES})

# nanobind intentionally treats STABLE_ABI as a request and can fall back to a
# CPython-version-specific build. Turn SceneIO's wheel contract into a checked
# invariant before compiling: the module must use nanobind's abi3 support
# library and its platform-specific stable-extension suffix.
get_target_property(_sceneio_core_links _core LINK_LIBRARIES)
if(NOT "${_sceneio_core_links}" MATCHES
       "(^|;)nanobind-static-abi3(;|$)")
  message(FATAL_ERROR
    "SceneIO _core did not select nanobind-static-abi3")
endif()
get_target_property(_sceneio_core_suffix _core SUFFIX)
if(NOT "${_sceneio_core_suffix}" STREQUAL "${NB_SUFFIX_S}")
  message(FATAL_ERROR
    "SceneIO _core suffix '${_sceneio_core_suffix}' does not match "
    "the stable-ABI suffix '${NB_SUFFIX_S}'")
endif()

if(SCENEIO_SELECTED_BACKEND_SOURCES)
  target_sources(_core PRIVATE ${SCENEIO_SELECTED_BACKEND_SOURCES})
endif()
target_include_directories(
  _core
  PRIVATE
    src/cpp
    ${zstd_SOURCE_DIR}/lib
    src/cpp/third_party/stb
    src/cpp/third_party/tinyexr
    src/cpp/third_party/tinyobjloader
    src/cpp/third_party/cgltf
    ${libwebp_SOURCE_DIR}
    ${libwebp_SOURCE_DIR}/src
    ${SCENEIO_SELECTED_BACKEND_INCLUDE_DIRS})
target_link_libraries(
  _core
  PRIVATE
    miniz_static
    nlohmann_json::nlohmann_json
    libzstd_static
    FastFloat::fast_float
    lazperf_static
    lodepng_static
    sqlite_static
    webp
    Threads::Threads)

if(SCENEIO_SELECTED_BACKEND_LINK_TARGETS)
  target_link_libraries(
    _core PRIVATE ${SCENEIO_SELECTED_BACKEND_LINK_TARGETS})
endif()
if(SCENEIO_SELECTED_BACKEND_LINK_OPTIONS)
  target_link_options(
    _core PRIVATE ${SCENEIO_SELECTED_BACKEND_LINK_OPTIONS})
endif()
if(SCENEIO_SELECTED_BACKEND_DEFINITIONS)
  target_compile_definitions(
    _core PRIVATE ${SCENEIO_SELECTED_BACKEND_DEFINITIONS})
endif()
if(SCENEIO_SELECTED_BACKEND_BUILD_TARGETS)
  add_dependencies(
    _core ${SCENEIO_SELECTED_BACKEND_BUILD_TARGETS})
endif()
if(SCENEIO_SELECTED_BACKEND_SIMD_HEADER)
  add_custom_command(
    TARGET _core
    POST_BUILD
    COMMAND
      "${CMAKE_COMMAND}"
      "-DINPUT=${SCENEIO_SELECTED_BACKEND_SIMD_HEADER}"
      "-DOUTPUT=${SCENEIO_SELECTED_BACKEND_SIMD_EVIDENCE}"
      -P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/SceneIORecordJpegSimd.cmake"
    VERBATIM)
endif()

# Land the extension inside the importable `sceneio` package as sceneio._core.
install(TARGETS _core LIBRARY DESTINATION sceneio)

# A separate, off-by-default extension supplies native lifetime controls and
# controlled LAZperf arithmetic decoders for the focused instrumented
# workflow. These hooks must never be linked into _core or a normal wheel.
if(SCENEIO_BUILD_NATIVE_TEST_HOOKS)
  add_executable(sceneio_native_arithmetic_default_check
    src/cpp/testing/lazperf_default_main.cpp
    src/cpp/testing/lazperf_default_test.cpp)
  target_compile_options(
    sceneio_native_arithmetic_default_check PRIVATE -g)
  target_link_libraries(
    sceneio_native_arithmetic_default_check PRIVATE lazperf_static)

  # Keep the COMPRESS_ONLY_K header instantiation in a separate binary. The
  # macro changes LAZperf's integer class definition, so linking both variants
  # into one program would violate the C++ one-definition rule.
  add_executable(sceneio_native_arithmetic_compact_check
    src/cpp/testing/lazperf_compact_main.cpp
    src/cpp/testing/lazperf_compact_test.cpp)
  target_compile_options(
    sceneio_native_arithmetic_compact_check PRIVATE -g)
  target_link_libraries(
    sceneio_native_arithmetic_compact_check PRIVATE lazperf_static)

  nanobind_add_module(_native_test STABLE_ABI NB_STATIC
    src/cpp/testing/native_test.cpp
    src/cpp/testing/lazperf_default_test.cpp)
  target_compile_options(_native_test PRIVATE -g)
  target_link_libraries(_native_test PRIVATE lazperf_static)
  install(TARGETS _native_test LIBRARY DESTINATION sceneio)
endif()
