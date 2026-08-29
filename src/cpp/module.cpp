// sceneio._core — the nanobind module assembler. Records register first
// (they are the codecs' return types), then codecs. See
// docs/core_architecture.md for how to add a codec.
#include <nanobind/nanobind.h>

#include "bindings/registry.hpp"
#include "io/common.hpp"

namespace nb = nanobind;
using namespace nb::literals;

NB_MODULE(_core, m) {
    m.doc() = "sceneio compiled core (nanobind): codecs + SoA memory representations";
    m.attr("__phase__") = 2;
    m.attr("__native_features__") = nb::make_tuple();
    // Private verification hook: tests compare this address with NumPy's view
    // of the same exporter to prove the buffer caster aliases rather than copies.
    m.def("_buffer_address",
          [](nb::handle source) {
              sio::ByteView data(source);
              return reinterpret_cast<uintptr_t>(data.data());
          },
          "data"_a);
    m.def("_parallel_hardware_lane_cap",
          []() {
              return std::min<size_t>(
                  std::max<size_t>(1, std::thread::hardware_concurrency()), 8);
          });
    m.def("_parallel_lane_count", &sio::parallel_lane_count, "count"_a,
          "requested"_a, "min_items_per_lane"_a);
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

    sio::bindings::register_records(m);
    sio::bindings::register_codecs(m);
    m.attr("__codec_inventory__") = sio::bindings::codec_inventory(m);
}
