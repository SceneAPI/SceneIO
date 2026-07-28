# Codec-backend selection and default-off qualification controls.
#
# The source-controlled internal default is the only backend selected by an
# ordinary build.  R5 qualification builds may provide a temporary override,
# but the override is rejected unless qualification is explicitly enabled.
# A later selection commit therefore changes the internal default without
# redesigning the source or dependency graph.

set(SCENEIO_INTERNAL_JPEG_DEFAULT_BACKEND "stb")

option(
  SCENEIO_BUILD_BACKEND_QUALIFICATION
  "Enable private codec-backend qualification controls"
  OFF)
set(
  SCENEIO_QUALIFICATION_JPEG_BACKEND
  ""
  CACHE STRING
  "Qualification-only JPEG override (empty, stb, or libjpeg-turbo)")
set_property(
  CACHE SCENEIO_QUALIFICATION_JPEG_BACKEND
  PROPERTY STRINGS "" stb libjpeg-turbo)
mark_as_advanced(SCENEIO_QUALIFICATION_JPEG_BACKEND)

set(_sceneio_supported_jpeg_backends stb libjpeg-turbo)
if(NOT SCENEIO_INTERNAL_JPEG_DEFAULT_BACKEND IN_LIST
   _sceneio_supported_jpeg_backends)
  message(FATAL_ERROR
    "SCENEIO_INTERNAL_JPEG_DEFAULT_BACKEND has unsupported value "
    "'${SCENEIO_INTERNAL_JPEG_DEFAULT_BACKEND}'")
endif()
if(NOT SCENEIO_QUALIFICATION_JPEG_BACKEND STREQUAL "" AND
   NOT SCENEIO_QUALIFICATION_JPEG_BACKEND IN_LIST
   _sceneio_supported_jpeg_backends)
  message(FATAL_ERROR
    "SCENEIO_QUALIFICATION_JPEG_BACKEND must be empty, 'stb', or "
    "'libjpeg-turbo' (got '${SCENEIO_QUALIFICATION_JPEG_BACKEND}')")
endif()
if(NOT SCENEIO_BUILD_BACKEND_QUALIFICATION AND
   NOT SCENEIO_QUALIFICATION_JPEG_BACKEND STREQUAL "")
  message(FATAL_ERROR
    "A JPEG qualification override requires "
    "SCENEIO_BUILD_BACKEND_QUALIFICATION=ON")
endif()

set(SCENEIO_EFFECTIVE_JPEG_BACKEND
  "${SCENEIO_INTERNAL_JPEG_DEFAULT_BACKEND}")
if(SCENEIO_BUILD_BACKEND_QUALIFICATION AND
   NOT SCENEIO_QUALIFICATION_JPEG_BACKEND STREQUAL "")
  set(SCENEIO_EFFECTIVE_JPEG_BACKEND
    "${SCENEIO_QUALIFICATION_JPEG_BACKEND}")
endif()

set(SCENEIO_SELECTED_BACKEND_SOURCES)
set(SCENEIO_SELECTED_BACKEND_INCLUDE_DIRS)
set(SCENEIO_SELECTED_BACKEND_LINK_TARGETS)
set(SCENEIO_SELECTED_BACKEND_DEFINITIONS)
set(SCENEIO_SELECTED_BACKEND_BUILD_TARGETS)
set(SCENEIO_SELECTED_BACKEND_LINK_OPTIONS)
set(SCENEIO_SELECTED_BACKEND_SIMD_HEADER)
set(SCENEIO_SELECTED_BACKEND_SIMD_EVIDENCE)

get_property(
  _sceneio_generator_is_multi_config
  GLOBAL PROPERTY GENERATOR_IS_MULTI_CONFIG)

if(SCENEIO_BUILD_BACKEND_QUALIFICATION)
  list(APPEND SCENEIO_SELECTED_BACKEND_DEFINITIONS
    SCENEIO_BUILD_BACKEND_QUALIFICATION=1)
endif()

if(SCENEIO_EFFECTIVE_JPEG_BACKEND STREQUAL "libjpeg-turbo")
  include(ExternalProject)

  set(_sceneio_jpeg_turbo_version "3.2.0")
  set(_sceneio_jpeg_turbo_commit
    "c85e6b905bf237038faa936dab160ebfc5da0344")
  set(_sceneio_jpeg_turbo_archive_sha256
    "6f30092cef9fb839779646608f4ee14ae3cbac989c47fa05e841b0841f09878e")
  string(CONCAT _sceneio_jpeg_turbo_url
    "https://github.com/libjpeg-turbo/libjpeg-turbo/releases/download/"
    "${_sceneio_jpeg_turbo_version}/"
    "libjpeg-turbo-${_sceneio_jpeg_turbo_version}.tar.gz")
  set(_sceneio_jpeg_turbo_prefix
    "${CMAKE_BINARY_DIR}/_q/jpeg")
  set(_sceneio_jpeg_turbo_source
    "${_sceneio_jpeg_turbo_prefix}/src/sceneio_libjpeg_turbo")
  set(_sceneio_jpeg_turbo_binary
    "${_sceneio_jpeg_turbo_prefix}/src/sceneio_libjpeg_turbo-build")
  set(_sceneio_jpeg_turbo_cache
    "${_sceneio_jpeg_turbo_binary}/CMakeCache.txt")

  if(_sceneio_generator_is_multi_config)
    set(_sceneio_external_build_type "")
  elseif(CMAKE_BUILD_TYPE)
    set(_sceneio_external_build_type "${CMAKE_BUILD_TYPE}")
  else()
    set(_sceneio_external_build_type "Release")
  endif()

  set(_sceneio_jpeg_turbo_cmake_args
    "-DCMAKE_POSITION_INDEPENDENT_CODE:BOOL=ON"
    "-DCMAKE_C_VISIBILITY_PRESET:STRING=hidden"
    "-DCMAKE_CXX_VISIBILITY_PRESET:STRING=hidden"
    "-DCMAKE_VISIBILITY_INLINES_HIDDEN:BOOL=ON"
    "-DENABLE_SHARED:BOOL=OFF"
    "-DENABLE_STATIC:BOOL=ON"
    "-DREQUIRE_SIMD:BOOL=ON"
    "-DWITH_ARITH_DEC:BOOL=OFF"
    "-DWITH_ARITH_ENC:BOOL=OFF"
    "-DWITH_JNA:STRING="
    "-DWITH_JPEG7:BOOL=OFF"
    "-DWITH_JPEG8:BOOL=OFF"
    "-DWITH_SIMD:BOOL=ON"
    "-DWITH_TURBOJPEG:BOOL=ON"
    "-DWITH_TOOLS:BOOL=OFF"
    "-DWITH_TESTS:BOOL=OFF"
    "-DWITH_FUZZ:BOOL=OFF"
    "-DWITH_PROFILE:BOOL=OFF")

  if(NOT _sceneio_generator_is_multi_config)
    list(APPEND _sceneio_jpeg_turbo_cmake_args
      "-DCMAKE_BUILD_TYPE:STRING=${_sceneio_external_build_type}")
  endif()

  if(CMAKE_C_COMPILER)
    file(TO_CMAKE_PATH
      "${CMAKE_C_COMPILER}" _sceneio_external_c_compiler)
    list(APPEND _sceneio_jpeg_turbo_cmake_args
      "-DCMAKE_C_COMPILER:FILEPATH=${_sceneio_external_c_compiler}")
  endif()
  if(CMAKE_C_COMPILER_LAUNCHER)
    string(REPLACE ";" "|" _sceneio_external_c_launcher
      "${CMAKE_C_COMPILER_LAUNCHER}")
    list(APPEND _sceneio_jpeg_turbo_cmake_args
      "-DCMAKE_C_COMPILER_LAUNCHER:STRING=${_sceneio_external_c_launcher}")
  endif()
  if(CMAKE_TOOLCHAIN_FILE)
    file(TO_CMAKE_PATH
      "${CMAKE_TOOLCHAIN_FILE}" _sceneio_external_toolchain)
    list(APPEND _sceneio_jpeg_turbo_cmake_args
      "-DCMAKE_TOOLCHAIN_FILE:FILEPATH=${_sceneio_external_toolchain}")
  endif()

  set(_sceneio_external_flag_names CMAKE_C_FLAGS)
  if(_sceneio_generator_is_multi_config)
    list(APPEND _sceneio_external_flag_names
      CMAKE_C_FLAGS_DEBUG
      CMAKE_C_FLAGS_RELEASE
      CMAKE_C_FLAGS_RELWITHDEBINFO
      CMAKE_C_FLAGS_MINSIZEREL)
  else()
    string(TOUPPER
      "${_sceneio_external_build_type}"
      _sceneio_external_build_type_upper)
    list(APPEND _sceneio_external_flag_names
      "CMAKE_C_FLAGS_${_sceneio_external_build_type_upper}")
  endif()
  foreach(_sceneio_flag_name IN LISTS _sceneio_external_flag_names)
    if(DEFINED ${_sceneio_flag_name} AND
       NOT "${${_sceneio_flag_name}}" STREQUAL "")
      string(REPLACE ";" "|" _sceneio_external_flag_value
        "${${_sceneio_flag_name}}")
      list(APPEND _sceneio_jpeg_turbo_cmake_args
        "-D${_sceneio_flag_name}:STRING=${_sceneio_external_flag_value}")
    endif()
  endforeach()

  if(MSVC OR CMAKE_C_SIMULATE_ID STREQUAL "MSVC")
    list(APPEND _sceneio_jpeg_turbo_cmake_args
      "-DWITH_CRT_DLL:BOOL=ON")
    set(_sceneio_candidate_crt "dynamic")
    set(_sceneio_jpeg_turbo_library_file
      "turbojpeg-static${CMAKE_STATIC_LIBRARY_SUFFIX}")
  else()
    set(_sceneio_candidate_crt "platform-default")
    set(_sceneio_jpeg_turbo_library_file
      "${CMAKE_STATIC_LIBRARY_PREFIX}turbojpeg${CMAKE_STATIC_LIBRARY_SUFFIX}")
  endif()

  set(_sceneio_jpeg_turbo_nasm "")
  if(CMAKE_ASM_NASM_COMPILER)
    set(_sceneio_jpeg_turbo_nasm "${CMAKE_ASM_NASM_COMPILER}")
  else()
    find_program(_sceneio_jpeg_turbo_nasm NAMES nasm)
  endif()
  set(_sceneio_jpeg_turbo_nasm_version "")
  set(_sceneio_jpeg_turbo_nasm_sha256 "")
  if(_sceneio_jpeg_turbo_nasm)
    file(TO_CMAKE_PATH
      "${_sceneio_jpeg_turbo_nasm}" _sceneio_jpeg_turbo_nasm)
    list(APPEND _sceneio_jpeg_turbo_cmake_args
      "-DCMAKE_ASM_NASM_COMPILER:FILEPATH=${_sceneio_jpeg_turbo_nasm}")
    execute_process(
      COMMAND "${_sceneio_jpeg_turbo_nasm}" -v
      OUTPUT_VARIABLE _sceneio_jpeg_turbo_nasm_version
      ERROR_VARIABLE _sceneio_jpeg_turbo_nasm_version_error
      OUTPUT_STRIP_TRAILING_WHITESPACE
      ERROR_STRIP_TRAILING_WHITESPACE)
    if(_sceneio_jpeg_turbo_nasm_version STREQUAL "")
      set(_sceneio_jpeg_turbo_nasm_version
        "${_sceneio_jpeg_turbo_nasm_version_error}")
    endif()
    if(EXISTS "${_sceneio_jpeg_turbo_nasm}")
      file(SHA256
        "${_sceneio_jpeg_turbo_nasm}"
        _sceneio_jpeg_turbo_nasm_sha256)
    endif()
  endif()

  if(CMAKE_OSX_ARCHITECTURES)
    string(REPLACE ";" "|" _sceneio_external_osx_architectures
      "${CMAKE_OSX_ARCHITECTURES}")
    string(CONCAT _sceneio_external_osx_architectures_arg
      "-DCMAKE_OSX_ARCHITECTURES:STRING="
      "${_sceneio_external_osx_architectures}")
    list(APPEND _sceneio_jpeg_turbo_cmake_args
      "${_sceneio_external_osx_architectures_arg}")
  endif()
  if(CMAKE_OSX_DEPLOYMENT_TARGET)
    string(CONCAT _sceneio_external_osx_deployment_arg
      "-DCMAKE_OSX_DEPLOYMENT_TARGET:STRING="
      "${CMAKE_OSX_DEPLOYMENT_TARGET}")
    list(APPEND _sceneio_jpeg_turbo_cmake_args
      "${_sceneio_external_osx_deployment_arg}")
  endif()
  if(CMAKE_OSX_SYSROOT)
    list(APPEND _sceneio_jpeg_turbo_cmake_args
      "-DCMAKE_OSX_SYSROOT:PATH=${CMAKE_OSX_SYSROOT}")
  endif()
  if(CMAKE_SYSROOT)
    list(APPEND _sceneio_jpeg_turbo_cmake_args
      "-DCMAKE_SYSROOT:PATH=${CMAKE_SYSROOT}")
  endif()

  if(_sceneio_generator_is_multi_config)
    set(_sceneio_jpeg_turbo_byproducts)
    foreach(_sceneio_config IN LISTS CMAKE_CONFIGURATION_TYPES)
      string(CONCAT _sceneio_jpeg_turbo_byproduct
        "${_sceneio_jpeg_turbo_binary}/${_sceneio_config}/"
        "${_sceneio_jpeg_turbo_library_file}")
      list(APPEND _sceneio_jpeg_turbo_byproducts
        "${_sceneio_jpeg_turbo_byproduct}")
    endforeach()
    set(_sceneio_jpeg_turbo_build_command
      "${CMAKE_COMMAND}" --build <BINARY_DIR>
      --config $<CONFIG> --target turbojpeg-static)
  else()
    string(CONCAT _sceneio_jpeg_turbo_byproduct
      "${_sceneio_jpeg_turbo_binary}/"
      "${_sceneio_jpeg_turbo_library_file}")
    set(_sceneio_jpeg_turbo_byproducts
      "${_sceneio_jpeg_turbo_byproduct}")
    set(_sceneio_jpeg_turbo_build_command
      "${CMAKE_COMMAND}" --build <BINARY_DIR>
      --target turbojpeg-static)
  endif()

  set(_sceneio_download_timestamp_args)
  if(CMAKE_VERSION VERSION_GREATER_EQUAL "3.24")
    list(APPEND _sceneio_download_timestamp_args
      DOWNLOAD_EXTRACT_TIMESTAMP TRUE)
  endif()

  ExternalProject_Add(sceneio_libjpeg_turbo
    PREFIX "${_sceneio_jpeg_turbo_prefix}"
    URL "${_sceneio_jpeg_turbo_url}"
    URL_HASH "SHA256=${_sceneio_jpeg_turbo_archive_sha256}"
    ${_sceneio_download_timestamp_args}
    LIST_SEPARATOR "|"
    CMAKE_ARGS ${_sceneio_jpeg_turbo_cmake_args}
    BUILD_COMMAND ${_sceneio_jpeg_turbo_build_command}
    INSTALL_COMMAND ""
    BUILD_BYPRODUCTS ${_sceneio_jpeg_turbo_byproducts})

  add_library(sceneio_libjpeg_turbo_static STATIC IMPORTED GLOBAL)
  if(_sceneio_generator_is_multi_config)
    set_property(
      TARGET sceneio_libjpeg_turbo_static
      PROPERTY IMPORTED_CONFIGURATIONS "${CMAKE_CONFIGURATION_TYPES}")
    foreach(_sceneio_config IN LISTS CMAKE_CONFIGURATION_TYPES)
      string(TOUPPER "${_sceneio_config}" _sceneio_config_upper)
      string(CONCAT _sceneio_jpeg_turbo_imported_location
        "${_sceneio_jpeg_turbo_binary}/${_sceneio_config}/"
        "${_sceneio_jpeg_turbo_library_file}")
      set_property(
        TARGET sceneio_libjpeg_turbo_static
        PROPERTY "IMPORTED_LOCATION_${_sceneio_config_upper}"
        "${_sceneio_jpeg_turbo_imported_location}")
    endforeach()
  else()
    set_property(
      TARGET sceneio_libjpeg_turbo_static
      PROPERTY IMPORTED_LOCATION
      "${_sceneio_jpeg_turbo_byproduct}")
  endif()
  add_dependencies(
    sceneio_libjpeg_turbo_static sceneio_libjpeg_turbo)

  list(APPEND SCENEIO_SELECTED_BACKEND_SOURCES
    src/cpp/qualification/jpeg_turbo.cpp)
  list(APPEND SCENEIO_SELECTED_BACKEND_INCLUDE_DIRS
    "${_sceneio_jpeg_turbo_source}/src")
  list(APPEND SCENEIO_SELECTED_BACKEND_LINK_TARGETS
    sceneio_libjpeg_turbo_static)
  list(APPEND SCENEIO_SELECTED_BACKEND_DEFINITIONS
    SCENEIO_USE_LIBJPEG_TURBO=1)
  list(APPEND SCENEIO_SELECTED_BACKEND_BUILD_TARGETS
    sceneio_libjpeg_turbo)
  set(SCENEIO_SELECTED_BACKEND_SIMD_HEADER
    "${_sceneio_jpeg_turbo_binary}/jconfigint.h")
  set(SCENEIO_SELECTED_BACKEND_SIMD_EVIDENCE
    "${CMAKE_BINARY_DIR}/sceneio-jpeg-simd-$<CONFIG>.json")
  if(APPLE)
    list(APPEND SCENEIO_SELECTED_BACKEND_LINK_OPTIONS
      "LINKER:-exported_symbol,_PyInit__core")
    set(_sceneio_symbol_export_policy
      "exported-symbol=PyInit__core")
  elseif(UNIX)
    list(APPEND SCENEIO_SELECTED_BACKEND_LINK_OPTIONS
      "LINKER:--exclude-libs,ALL")
    set(_sceneio_symbol_export_policy "exclude-libs=ALL")
  else()
    set(_sceneio_symbol_export_policy "explicit-dllexport-only")
  endif()

  list(JOIN _sceneio_jpeg_turbo_cmake_args
    "\n" _sceneio_jpeg_turbo_option_payload)
  string(SHA256 _sceneio_jpeg_turbo_option_sha256
    "${_sceneio_jpeg_turbo_option_payload}")
endif()

function(_sceneio_json_escape input output)
  set(_sceneio_json_value "${input}")
  string(REPLACE "\\" "\\\\" _sceneio_json_value
    "${_sceneio_json_value}")
  string(REPLACE "\"" "\\\"" _sceneio_json_value
    "${_sceneio_json_value}")
  string(REPLACE "\r" "\\r" _sceneio_json_value
    "${_sceneio_json_value}")
  string(REPLACE "\n" "\\n" _sceneio_json_value
    "${_sceneio_json_value}")
  set(${output} "${_sceneio_json_value}" PARENT_SCOPE)
endfunction()

if(SCENEIO_BUILD_BACKEND_QUALIFICATION)
  if(_sceneio_generator_is_multi_config)
    set(_sceneio_manifest_multi_config true)
  else()
    set(_sceneio_manifest_multi_config false)
  endif()
  if(SCENEIO_EFFECTIVE_JPEG_BACKEND STREQUAL "libjpeg-turbo")
    set(_sceneio_manifest_simd_required true)
  else()
    set(_sceneio_manifest_simd_required false)
    set(_sceneio_candidate_crt "not-linked")
    set(_sceneio_external_build_type "")
    set(_sceneio_jpeg_turbo_cache "")
    set(_sceneio_jpeg_turbo_nasm "")
    set(_sceneio_jpeg_turbo_nasm_version "")
    set(_sceneio_jpeg_turbo_nasm_sha256 "")
    set(_sceneio_jpeg_turbo_option_sha256 "")
    set(_sceneio_symbol_export_policy "retained-default")
  endif()

  foreach(_sceneio_manifest_field
      CMAKE_GENERATOR
      CMAKE_GENERATOR_PLATFORM
      CMAKE_GENERATOR_TOOLSET
      CMAKE_VERSION
      CMAKE_SYSTEM_NAME
      CMAKE_SYSTEM_PROCESSOR
      CMAKE_C_COMPILER
      CMAKE_C_COMPILER_ID
      CMAKE_C_COMPILER_VERSION
      CMAKE_CXX_COMPILER
      CMAKE_CXX_COMPILER_ID
      CMAKE_CXX_COMPILER_VERSION
      CMAKE_MSVC_RUNTIME_LIBRARY)
    _sceneio_json_escape(
      "${${_sceneio_manifest_field}}"
      "_sceneio_json_${_sceneio_manifest_field}")
  endforeach()
  foreach(_sceneio_manifest_variable
      _sceneio_external_build_type
      _sceneio_candidate_crt
      _sceneio_jpeg_turbo_cache
      _sceneio_jpeg_turbo_nasm
      _sceneio_jpeg_turbo_nasm_version
      _sceneio_jpeg_turbo_nasm_sha256
      _sceneio_jpeg_turbo_option_sha256
      _sceneio_symbol_export_policy)
    _sceneio_json_escape(
      "${${_sceneio_manifest_variable}}"
      "_sceneio_json${_sceneio_manifest_variable}")
  endforeach()

  string(CONCAT _sceneio_backend_qualification_manifest
    "{\n"
    "  \"schema_version\": 1,\n"
    "  \"qualification_build\": true,\n"
    "  \"jpeg_backend\": \"${SCENEIO_EFFECTIVE_JPEG_BACKEND}\",\n"
    "  \"internal_jpeg_default\": "
    "\"${SCENEIO_INTERNAL_JPEG_DEFAULT_BACKEND}\",\n"
    "  \"qualification_jpeg_override\": "
    "\"${SCENEIO_QUALIFICATION_JPEG_BACKEND}\",\n"
    "  \"generator\": \"${_sceneio_json_CMAKE_GENERATOR}\",\n"
    "  \"generator_platform\": "
    "\"${_sceneio_json_CMAKE_GENERATOR_PLATFORM}\",\n"
    "  \"generator_toolset\": "
    "\"${_sceneio_json_CMAKE_GENERATOR_TOOLSET}\",\n"
    "  \"cmake_version\": \"${_sceneio_json_CMAKE_VERSION}\",\n"
    "  \"multi_config\": ${_sceneio_manifest_multi_config},\n"
    "  \"outer_configuration\": \"$<CONFIG>\",\n"
    "  \"external_build_type\": "
    "\"${_sceneio_json_sceneio_external_build_type}\",\n"
    "  \"system_name\": \"${_sceneio_json_CMAKE_SYSTEM_NAME}\",\n"
    "  \"system_processor\": "
    "\"${_sceneio_json_CMAKE_SYSTEM_PROCESSOR}\",\n"
    "  \"c_compiler\": \"${_sceneio_json_CMAKE_C_COMPILER}\",\n"
    "  \"c_compiler_id\": \"${_sceneio_json_CMAKE_C_COMPILER_ID}\",\n"
    "  \"c_compiler_version\": "
    "\"${_sceneio_json_CMAKE_C_COMPILER_VERSION}\",\n"
    "  \"cxx_compiler\": \"${_sceneio_json_CMAKE_CXX_COMPILER}\",\n"
    "  \"cxx_compiler_id\": "
    "\"${_sceneio_json_CMAKE_CXX_COMPILER_ID}\",\n"
    "  \"cxx_compiler_version\": "
    "\"${_sceneio_json_CMAKE_CXX_COMPILER_VERSION}\",\n"
    "  \"outer_msvc_runtime\": "
    "\"${_sceneio_json_CMAKE_MSVC_RUNTIME_LIBRARY}\",\n"
    "  \"candidate_crt\": \"${_sceneio_json_sceneio_candidate_crt}\",\n"
    "  \"libjpeg_turbo_version\": \"3.2.0\",\n"
    "  \"libjpeg_turbo_commit\": "
    "\"c85e6b905bf237038faa936dab160ebfc5da0344\",\n"
    "  \"libjpeg_turbo_archive_sha256\": "
    "\"6f30092cef9fb839779646608f4ee14ae3cbac989c47fa05e841b0841f09878e\",\n"
    "  \"external_cmake_cache\": "
    "\"${_sceneio_json_sceneio_jpeg_turbo_cache}\",\n"
    "  \"option_fingerprint_sha256\": "
    "\"${_sceneio_json_sceneio_jpeg_turbo_option_sha256}\",\n"
    "  \"symbol_export_policy\": "
    "\"${_sceneio_json_sceneio_symbol_export_policy}\",\n"
    "  \"simd_required\": ${_sceneio_manifest_simd_required},\n"
    "  \"simd_architecture\": "
    "\"${_sceneio_json_CMAKE_SYSTEM_PROCESSOR}\",\n"
    "  \"nasm_compiler\": "
    "\"${_sceneio_json_sceneio_jpeg_turbo_nasm}\",\n"
    "  \"nasm_version\": "
    "\"${_sceneio_json_sceneio_jpeg_turbo_nasm_version}\",\n"
    "  \"nasm_sha256\": "
    "\"${_sceneio_json_sceneio_jpeg_turbo_nasm_sha256}\"\n"
    "}\n")
  file(GENERATE
    OUTPUT
      "${CMAKE_BINARY_DIR}/sceneio-backend-qualification-$<CONFIG>.json"
    CONTENT "${_sceneio_backend_qualification_manifest}")
endif()

unset(_sceneio_backend_qualification_manifest)
unset(_sceneio_candidate_crt)
unset(_sceneio_config)
unset(_sceneio_config_upper)
unset(_sceneio_download_timestamp_args)
unset(_sceneio_external_build_type)
unset(_sceneio_external_build_type_upper)
unset(_sceneio_external_c_compiler)
unset(_sceneio_external_c_launcher)
unset(_sceneio_external_flag_value)
unset(_sceneio_external_flag_names)
unset(_sceneio_external_osx_architectures)
unset(_sceneio_external_osx_architectures_arg)
unset(_sceneio_external_osx_deployment_arg)
unset(_sceneio_external_toolchain)
unset(_sceneio_flag_name)
unset(_sceneio_generator_is_multi_config)
unset(_sceneio_jpeg_turbo_archive_sha256)
unset(_sceneio_jpeg_turbo_binary)
unset(_sceneio_jpeg_turbo_build_command)
unset(_sceneio_jpeg_turbo_byproduct)
unset(_sceneio_jpeg_turbo_byproducts)
unset(_sceneio_jpeg_turbo_cache)
unset(_sceneio_jpeg_turbo_cmake_args)
unset(_sceneio_jpeg_turbo_commit)
unset(_sceneio_jpeg_turbo_library_file)
unset(_sceneio_jpeg_turbo_imported_location)
unset(_sceneio_jpeg_turbo_nasm)
unset(_sceneio_jpeg_turbo_nasm_sha256)
unset(_sceneio_jpeg_turbo_nasm_version)
unset(_sceneio_jpeg_turbo_nasm_version_error)
unset(_sceneio_jpeg_turbo_option_payload)
unset(_sceneio_jpeg_turbo_option_sha256)
unset(_sceneio_jpeg_turbo_prefix)
unset(_sceneio_jpeg_turbo_source)
unset(_sceneio_jpeg_turbo_url)
unset(_sceneio_jpeg_turbo_version)
unset(_sceneio_json_value)
unset(_sceneio_manifest_field)
unset(_sceneio_manifest_multi_config)
unset(_sceneio_manifest_simd_required)
unset(_sceneio_manifest_variable)
unset(_sceneio_symbol_export_policy)
unset(_sceneio_supported_jpeg_backends)
