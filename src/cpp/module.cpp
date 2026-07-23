// sceneio._core — the nanobind module assembler. Records register first
// (they are the codecs' return types), then codecs. See
// docs/core_architecture.md for how to add a codec.
#include <nanobind/nanobind.h>

#include "io/common.hpp"

namespace nb = nanobind;
using namespace nb::literals;

// records/
void register_reconstruction(nb::module_ &);
void register_gaussian_cloud(nb::module_ &);
void register_posed_view_set(nb::module_ &);
void register_tensor_dict(nb::module_ &);
void register_image(nb::module_ &);
void register_point_cloud(nb::module_ &);
void register_depth_map(nb::module_ &);
// codecs/
void register_pfm(nb::module_ &);
void register_colmap(nb::module_ &);
void register_ply_gaussian(nb::module_ &);
void register_spz(nb::module_ &);
void register_transforms_json(nb::module_ &);
void register_pose_text(nb::module_ &);
void register_npy_npz(nb::module_ &);
void register_netpbm(nb::module_ &);
void register_colmap_txt(nb::module_ &);
void register_xyz(nb::module_ &);
void register_flo(nb::module_ &);
void register_bundler(nb::module_ &);
void register_nvm(nb::module_ &);
void register_openmvg(nb::module_ &);
void register_splat(nb::module_ &);
void register_png(nb::module_ &);
void register_jpeg(nb::module_ &);
void register_hdr(nb::module_ &);
void register_exr(nb::module_ &);
void register_las(nb::module_ &);
void register_webp(nb::module_ &);

NB_MODULE(_core, m) {
    m.doc() = "sceneio compiled core (nanobind): codecs + SoA memory representations";
    m.attr("__phase__") = 2;
    // Private verification hook: tests compare this address with NumPy's view
    // of the same exporter to prove the buffer caster aliases rather than copies.
    m.def("_buffer_address",
          [](nb::handle source) {
              sio::ByteView data(source);
              return reinterpret_cast<uintptr_t>(data.data());
          },
          "data"_a);
    // Private registry adapter: run a direct compiled bytes encoder with a
    // lazy binary-file sink. Python-side conversion must finish before this
    // call because arbitrary protocol callbacks could otherwise re-enter an
    // encoder while the sink is active. emit_bytes() writes the encoder's C++
    // buffer directly and returns an empty sentinel instead of allocating the
    // usual output-sized Python bytes object.
    m.def("_write_to_file",
          [](nb::callable encoder, nb::handle value, nb::handle path,
             size_t max_chunk, size_t test_short_write,
             size_t test_fail_after) {
              sio::FileSinkScope sink(path, max_chunk, test_short_write,
                                      test_fail_after);
              try {
                  encoder(value);
                  if (sink.calls() == 0)
                      throw std::runtime_error(
                          "file sink encoder returned without emitting output");
                  sink.close();
                  return sink.native_write_calls();
              } catch (...) {
                  sink.close_noexcept();
                  throw;
              }
          },
          "encoder"_a, "value"_a, "path"_a, "_max_chunk"_a = 0,
          "_test_short_write"_a = 0, "_test_fail_after"_a = 0);

    register_reconstruction(m);
    register_gaussian_cloud(m);
    register_posed_view_set(m);
    register_tensor_dict(m);
    register_image(m);
    register_point_cloud(m);
    register_depth_map(m);

    register_pfm(m);
    register_colmap(m);
    register_ply_gaussian(m);
    register_spz(m);
    register_transforms_json(m);
    register_pose_text(m);
    register_npy_npz(m);
    register_netpbm(m);
    register_colmap_txt(m);
    register_xyz(m);
    register_flo(m);
    register_bundler(m);
    register_nvm(m);
    register_openmvg(m);
    register_splat(m);
    register_png(m);
    register_jpeg(m);
    register_hdr(m);
    register_exr(m);
    register_las(m);
    register_webp(m);
}
