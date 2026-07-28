# SceneIO-owned translation-unit manifests.
#
# Keep these lists explicit.  They are the native ownership boundary used by
# both the build and repository checks; configure fails if a tracked codec or
# record is missing, appears more than once, or is assigned to no family.

set(SCENEIO_MODULE_SOURCES
  src/cpp/module.cpp)

set(SCENEIO_BINDING_SOURCES
  src/cpp/bindings/registry.cpp
  src/cpp/bindings/records.cpp
  src/cpp/bindings/arrays.cpp
  src/cpp/bindings/calibration.cpp
  src/cpp/bindings/images.cpp
  src/cpp/bindings/meshes.cpp
  src/cpp/bindings/points.cpp
  src/cpp/bindings/reconstruction.cpp
  src/cpp/bindings/sequences.cpp
  src/cpp/bindings/splats.cpp)

set(SCENEIO_RECORD_SOURCES
  src/cpp/records/reconstruction.cpp
  src/cpp/records/gaussian_cloud.cpp
  src/cpp/records/posed_view_set.cpp
  src/cpp/records/tensor_dict.cpp
  src/cpp/records/image.cpp
  src/cpp/records/image_sequence.cpp
  src/cpp/records/point_cloud.cpp
  src/cpp/records/depth_map.cpp
  src/cpp/records/flow_field.cpp
  src/cpp/records/state_trajectory.cpp
  src/cpp/records/camera_rig.cpp
  src/cpp/records/pose_graph.cpp
  src/cpp/records/feature_match.cpp
  src/cpp/records/material_set.cpp
  src/cpp/records/mesh.cpp
  src/cpp/records/mesh_scene.cpp)

set(SCENEIO_ARRAY_CODEC_SOURCES
  src/cpp/codecs/arrays/pfm.cpp
  src/cpp/codecs/arrays/npy_npz.cpp
  src/cpp/codecs/arrays/safetensors.cpp
  src/cpp/codecs/arrays/flo.cpp
  src/cpp/codecs/arrays/dmb.cpp)

set(SCENEIO_CALIBRATION_CODEC_SOURCES
  src/cpp/codecs/camera_calibration.cpp)

set(SCENEIO_IMAGE_CODEC_SOURCES
  src/cpp/codecs/netpbm.cpp
  src/cpp/codecs/png.cpp
  src/cpp/codecs/jpeg.cpp
  src/cpp/codecs/bmp_tga.cpp
  src/cpp/codecs/hdr.cpp
  src/cpp/codecs/exr.cpp
  src/cpp/codecs/webp.cpp)

set(SCENEIO_MESH_CODEC_SOURCES
  src/cpp/codecs/ply_mesh.cpp
  src/cpp/codecs/obj_mtl.cpp
  src/cpp/codecs/stl_off.cpp
  src/cpp/codecs/gltf.cpp)

set(SCENEIO_POINT_CODEC_SOURCES
  src/cpp/codecs/ply_point.cpp
  src/cpp/codecs/pcd.cpp
  src/cpp/codecs/xyz.cpp
  src/cpp/codecs/las.cpp
  src/cpp/codecs/laz.cpp)

set(SCENEIO_RECONSTRUCTION_CODEC_SOURCES
  src/cpp/codecs/colmap.cpp
  src/cpp/codecs/transforms_json.cpp
  src/cpp/codecs/pose_text.cpp
  src/cpp/codecs/euroc_state.cpp
  src/cpp/codecs/g2o.cpp
  src/cpp/codecs/colmap_db.cpp
  src/cpp/codecs/colmap_txt.cpp
  src/cpp/codecs/bundler.cpp
  src/cpp/codecs/bal.cpp
  src/cpp/codecs/nvm.cpp
  src/cpp/codecs/openmvg.cpp)

set(SCENEIO_SEQUENCE_CODEC_SOURCES
  src/cpp/codecs/y4m.cpp)

set(SCENEIO_SPLAT_CODEC_SOURCES
  src/cpp/codecs/ply_gaussian.cpp
  src/cpp/codecs/compressed_ply.cpp
  src/cpp/codecs/sog.cpp
  src/cpp/codecs/ksplat.cpp
  src/cpp/codecs/spz.cpp
  src/cpp/codecs/splat.cpp)

set(SCENEIO_CODEC_SOURCES
  ${SCENEIO_ARRAY_CODEC_SOURCES}
  ${SCENEIO_CALIBRATION_CODEC_SOURCES}
  ${SCENEIO_IMAGE_CODEC_SOURCES}
  ${SCENEIO_MESH_CODEC_SOURCES}
  ${SCENEIO_POINT_CODEC_SOURCES}
  ${SCENEIO_RECONSTRUCTION_CODEC_SOURCES}
  ${SCENEIO_SEQUENCE_CODEC_SOURCES}
  ${SCENEIO_SPLAT_CODEC_SOURCES})

set(SCENEIO_SUPPORT_SOURCES
  src/cpp/third_party/stb/stb_impl.cpp
  src/cpp/third_party/tinyexr/tinyexr_impl.cpp)

set(SCENEIO_CORE_SOURCES
  src/cpp/module.cpp
  src/cpp/bindings/registry.cpp
  src/cpp/bindings/records.cpp
  src/cpp/bindings/arrays.cpp
  src/cpp/bindings/calibration.cpp
  src/cpp/bindings/images.cpp
  src/cpp/bindings/meshes.cpp
  src/cpp/bindings/points.cpp
  src/cpp/bindings/reconstruction.cpp
  src/cpp/bindings/sequences.cpp
  src/cpp/bindings/splats.cpp
  src/cpp/records/reconstruction.cpp
  src/cpp/records/gaussian_cloud.cpp
  src/cpp/records/posed_view_set.cpp
  src/cpp/records/tensor_dict.cpp
  src/cpp/records/image.cpp
  src/cpp/records/image_sequence.cpp
  src/cpp/records/point_cloud.cpp
  src/cpp/records/depth_map.cpp
  src/cpp/records/flow_field.cpp
  src/cpp/records/state_trajectory.cpp
  src/cpp/records/camera_rig.cpp
  src/cpp/records/pose_graph.cpp
  src/cpp/records/feature_match.cpp
  src/cpp/records/material_set.cpp
  src/cpp/records/mesh.cpp
  src/cpp/records/mesh_scene.cpp
  src/cpp/codecs/arrays/pfm.cpp
  src/cpp/codecs/colmap.cpp
  src/cpp/codecs/ply_gaussian.cpp
  src/cpp/codecs/compressed_ply.cpp
  src/cpp/codecs/sog.cpp
  src/cpp/codecs/ksplat.cpp
  src/cpp/codecs/ply_point.cpp
  src/cpp/codecs/ply_mesh.cpp
  src/cpp/codecs/obj_mtl.cpp
  src/cpp/codecs/stl_off.cpp
  src/cpp/codecs/gltf.cpp
  src/cpp/codecs/pcd.cpp
  src/cpp/codecs/spz.cpp
  src/cpp/codecs/transforms_json.cpp
  src/cpp/codecs/pose_text.cpp
  src/cpp/codecs/arrays/npy_npz.cpp
  src/cpp/codecs/netpbm.cpp
  src/cpp/codecs/colmap_txt.cpp
  src/cpp/codecs/xyz.cpp
  src/cpp/codecs/arrays/flo.cpp
  src/cpp/codecs/bundler.cpp
  src/cpp/codecs/bal.cpp
  src/cpp/codecs/nvm.cpp
  src/cpp/codecs/openmvg.cpp
  src/cpp/codecs/splat.cpp
  src/cpp/codecs/png.cpp
  src/cpp/codecs/jpeg.cpp
  src/cpp/codecs/hdr.cpp
  src/cpp/codecs/bmp_tga.cpp
  src/cpp/codecs/exr.cpp
  src/cpp/codecs/las.cpp
  src/cpp/codecs/laz.cpp
  src/cpp/codecs/y4m.cpp
  src/cpp/codecs/webp.cpp
  src/cpp/codecs/arrays/safetensors.cpp
  src/cpp/codecs/arrays/dmb.cpp
  src/cpp/codecs/euroc_state.cpp
  src/cpp/codecs/camera_calibration.cpp
  src/cpp/codecs/g2o.cpp
  src/cpp/codecs/colmap_db.cpp
  src/cpp/third_party/stb/stb_impl.cpp
  src/cpp/third_party/tinyexr/tinyexr_impl.cpp)

function(_sceneio_assert_unique_sources label)
  set(_sceneio_sources ${ARGN})
  list(LENGTH _sceneio_sources _sceneio_source_count)
  list(REMOVE_DUPLICATES _sceneio_sources)
  list(LENGTH _sceneio_sources _sceneio_unique_source_count)
  if(NOT _sceneio_source_count EQUAL _sceneio_unique_source_count)
    message(FATAL_ERROR "${label} contains duplicate source paths")
  endif()
endfunction()

function(_sceneio_assert_sources_exist label)
  foreach(_sceneio_source IN LISTS ARGN)
    if(NOT EXISTS "${PROJECT_SOURCE_DIR}/${_sceneio_source}")
      message(FATAL_ERROR
        "${label} references missing source: ${_sceneio_source}")
    endif()
  endforeach()
endfunction()

_sceneio_assert_unique_sources(
  "SCENEIO_CODEC_SOURCES" ${SCENEIO_CODEC_SOURCES})
_sceneio_assert_unique_sources(
  "SCENEIO_CORE_SOURCES" ${SCENEIO_CORE_SOURCES})
_sceneio_assert_sources_exist(
  "SCENEIO_CORE_SOURCES" ${SCENEIO_CORE_SOURCES})

set(_sceneio_owned_core_sources
  ${SCENEIO_MODULE_SOURCES}
  ${SCENEIO_BINDING_SOURCES}
  ${SCENEIO_RECORD_SOURCES}
  ${SCENEIO_CODEC_SOURCES}
  ${SCENEIO_SUPPORT_SOURCES})
list(SORT _sceneio_owned_core_sources)
set(_sceneio_linked_core_sources ${SCENEIO_CORE_SOURCES})
list(SORT _sceneio_linked_core_sources)
if(NOT _sceneio_owned_core_sources STREQUAL _sceneio_linked_core_sources)
  message(FATAL_ERROR
    "SCENEIO_CORE_SOURCES differs from the owned module/record/codec/support "
    "source manifests")
endif()

file(GLOB_RECURSE _sceneio_discovered_codec_sources
  RELATIVE "${PROJECT_SOURCE_DIR}"
  CONFIGURE_DEPENDS
  "${PROJECT_SOURCE_DIR}/src/cpp/codecs/*.cpp")
list(SORT _sceneio_discovered_codec_sources)
set(_sceneio_manifest_codec_sources ${SCENEIO_CODEC_SOURCES})
list(SORT _sceneio_manifest_codec_sources)
if(NOT _sceneio_discovered_codec_sources STREQUAL
   _sceneio_manifest_codec_sources)
  message(FATAL_ERROR
    "SCENEIO_CODEC_SOURCES must own every codec source exactly once.\n"
    "Discovered: ${_sceneio_discovered_codec_sources}\n"
    "Manifest: ${_sceneio_manifest_codec_sources}")
endif()

file(GLOB_RECURSE _sceneio_discovered_record_sources
  RELATIVE "${PROJECT_SOURCE_DIR}"
  CONFIGURE_DEPENDS
  "${PROJECT_SOURCE_DIR}/src/cpp/records/*.cpp")
list(SORT _sceneio_discovered_record_sources)
set(_sceneio_manifest_record_sources ${SCENEIO_RECORD_SOURCES})
list(SORT _sceneio_manifest_record_sources)
if(NOT _sceneio_discovered_record_sources STREQUAL
   _sceneio_manifest_record_sources)
  message(FATAL_ERROR
    "SCENEIO_RECORD_SOURCES must own every record source exactly once.\n"
    "Discovered: ${_sceneio_discovered_record_sources}\n"
    "Manifest: ${_sceneio_manifest_record_sources}")
endif()

file(GLOB_RECURSE _sceneio_discovered_binding_sources
  RELATIVE "${PROJECT_SOURCE_DIR}"
  CONFIGURE_DEPENDS
  "${PROJECT_SOURCE_DIR}/src/cpp/bindings/*.cpp")
list(SORT _sceneio_discovered_binding_sources)
set(_sceneio_manifest_binding_sources ${SCENEIO_BINDING_SOURCES})
list(SORT _sceneio_manifest_binding_sources)
if(NOT _sceneio_discovered_binding_sources STREQUAL
   _sceneio_manifest_binding_sources)
  message(FATAL_ERROR
    "SCENEIO_BINDING_SOURCES must own every binding source exactly once.\n"
    "Discovered: ${_sceneio_discovered_binding_sources}\n"
    "Manifest: ${_sceneio_manifest_binding_sources}")
endif()

unset(_sceneio_discovered_codec_sources)
unset(_sceneio_manifest_codec_sources)
unset(_sceneio_discovered_record_sources)
unset(_sceneio_manifest_record_sources)
unset(_sceneio_discovered_binding_sources)
unset(_sceneio_manifest_binding_sources)
unset(_sceneio_owned_core_sources)
unset(_sceneio_linked_core_sources)
