# Generate the native camera-model lookup from the package-owned Python
# manifest.  Configure-time generation makes the manifest the only editable
# authority while keeping the native lookup constexpr-like and dependency-free
# at runtime.

set(SCENEIO_CAMERA_MODEL_MANIFEST
  "${PROJECT_SOURCE_DIR}/src/sceneio/_camera_models.py")
set(SCENEIO_CAMERA_MODEL_GENERATOR
  "${PROJECT_SOURCE_DIR}/tools/generate_camera_models.py")
set(SCENEIO_GENERATED_INCLUDE_DIR
  "${CMAKE_CURRENT_BINARY_DIR}/generated")
set(SCENEIO_CAMERA_MODEL_HEADER
  "${SCENEIO_GENERATED_INCLUDE_DIR}/sceneio_camera_models.generated.hpp")

if(NOT EXISTS "${SCENEIO_CAMERA_MODEL_MANIFEST}" OR
   NOT EXISTS "${SCENEIO_CAMERA_MODEL_GENERATOR}")
  message(FATAL_ERROR "SceneIO camera-model manifest/generator is incomplete")
endif()

file(MAKE_DIRECTORY "${SCENEIO_GENERATED_INCLUDE_DIR}")
execute_process(
  COMMAND
    "${Python_EXECUTABLE}"
    "${SCENEIO_CAMERA_MODEL_GENERATOR}"
    --manifest "${SCENEIO_CAMERA_MODEL_MANIFEST}"
    --output "${SCENEIO_CAMERA_MODEL_HEADER}"
  RESULT_VARIABLE _sceneio_camera_model_result
  OUTPUT_VARIABLE _sceneio_camera_model_stdout
  ERROR_VARIABLE _sceneio_camera_model_stderr)
if(NOT _sceneio_camera_model_result EQUAL 0)
  message(FATAL_ERROR
    "SceneIO camera-model generation failed:\n"
    "${_sceneio_camera_model_stdout}${_sceneio_camera_model_stderr}")
endif()

set_property(
  DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
  "${SCENEIO_CAMERA_MODEL_MANIFEST}"
  "${SCENEIO_CAMERA_MODEL_GENERATOR}")
