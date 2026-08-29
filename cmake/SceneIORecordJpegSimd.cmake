if(NOT DEFINED INPUT OR NOT EXISTS "${INPUT}")
  message(FATAL_ERROR
    "libjpeg-turbo SIMD evidence header does not exist: '${INPUT}'")
endif()
if(NOT DEFINED OUTPUT OR OUTPUT STREQUAL "")
  message(FATAL_ERROR "libjpeg-turbo SIMD evidence output is required")
endif()

file(READ "${INPUT}" _sceneio_jconfigint)
string(
  REGEX MATCH
  "#define[ \t]+SIMD_ARCHITECTURE[ \t]+([A-Za-z0-9_]+)"
  _sceneio_simd_match
  "${_sceneio_jconfigint}")
if(NOT _sceneio_simd_match)
  message(FATAL_ERROR
    "libjpeg-turbo generated header has no SIMD_ARCHITECTURE token")
endif()
set(_sceneio_simd_architecture "${CMAKE_MATCH_1}")
file(SHA256 "${INPUT}" _sceneio_jconfigint_sha256)
file(TO_CMAKE_PATH "${INPUT}" _sceneio_jconfigint_path)

string(CONCAT _sceneio_simd_evidence
  "{\n"
  "  \"schema_version\": 1,\n"
  "  \"simd_required\": true,\n"
  "  \"simd_architecture\": \"${_sceneio_simd_architecture}\",\n"
  "  \"generated_header\": \"${_sceneio_jconfigint_path}\",\n"
  "  \"generated_header_sha256\": \"${_sceneio_jconfigint_sha256}\"\n"
  "}\n")
file(WRITE "${OUTPUT}" "${_sceneio_simd_evidence}")
