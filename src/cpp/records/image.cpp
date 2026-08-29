// records/image.cpp — Image nanobind binding. Registered once (after the
// other records) and shared by the raster-image codecs (netpbm now;
// PNG/JPEG/TIFF/EXR later). Array access is a dtype-polymorphic zero-copy
// view; conventions are metadata the codec recorded, and an `image(...)`
// factory builds one from an array for tests.
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>

#include <optional>

#include "records/image.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

// dtype-erased, read-only, contiguous CPU array — accepts numpy OR torch of
// ANY dtype at the binding layer; we dispatch on a.dtype() and raise our own
// clear error for unsupported kinds (non-contiguous input is copied by nb).
using anyarr = nb::ndarray<nb::ro, nb::c_contig, nb::device::cpu>;

Image make_image(anyarr pixels, std::optional<std::string> color_space,
                 std::optional<std::string> alpha_mode, std::optional<uint32_t> maxval) {
    // 1. shape: ndim 2 -> C=1; ndim 3 -> C=shape(2) in {1,3,4}; (H,W,1) -> C=1.
    if (pixels.ndim() != 2 && pixels.ndim() != 3)
        throw std::invalid_argument("image: pixels must be (H,W) or (H,W,C)");
    const size_t H = pixels.shape(0), W = pixels.shape(1);
    const size_t C = pixels.ndim() == 2 ? 1 : pixels.shape(2);
    if (H == 0 || W == 0 || !image_valid_channels(C))
        throw std::invalid_argument("image: need H,W >= 1 and C in {1,3,4}");

    Image im;
    im.height = H;
    im.width = W;
    im.channels = C;  // (H,W,1) already collapsed to C==1 above -> grayscale
    const size_t cnt = H * W * C;

    // 2. dtype dispatch + one bulk copy into the matching typed vector.
    if (pixels.dtype() == nb::dtype<uint8_t>()) {
        im.dtype = PixelType::U8;
        const auto *d = static_cast<const uint8_t *>(pixels.data());
        im.u8.assign(d, d + cnt);
    } else if (pixels.dtype() == nb::dtype<uint16_t>()) {
        im.dtype = PixelType::U16;
        const auto *d = static_cast<const uint16_t *>(pixels.data());
        im.u16.assign(d, d + cnt);
    } else if (pixels.dtype() == nb::dtype<float>()) {
        im.dtype = PixelType::F32;
        const auto *d = static_cast<const float *>(pixels.data());
        im.f32.assign(d, d + cnt);
    } else {
        throw std::invalid_argument("image: dtype must be uint8, uint16, or float32");
    }

    // 3. conventions: defaults derive from shape, then validate the vocabulary.
    im.color_space = color_space.value_or(im.channels == 1 ? "gray" : "srgb");
    if (!image_valid_color_space(im.color_space))
        throw std::invalid_argument("image: color_space must be srgb|linear|gray|unknown");

    im.alpha_mode = alpha_mode.value_or(im.channels == 4 ? "straight" : "none");
    const bool alpha_ok =
        im.channels == 4 ? (im.alpha_mode == "straight" || im.alpha_mode == "premultiplied")
                         : (im.alpha_mode == "none");
    if (!alpha_ok)
        throw std::invalid_argument(
            "image: alpha_mode 'straight'|'premultiplied' requires C==4 (else 'none')");

    // 4. maxval: netpbm sample-range metadata. Default per dtype (255/65535/0);
    // if supplied, require it fit the integer storage. Each format writer
    // re-guards the dtype<->maxval pairing (a foreign one is refused there).
    if (maxval) {
        im.maxval = *maxval;
        if (im.dtype == PixelType::U8 && (im.maxval < 1 || im.maxval > 255))
            throw std::invalid_argument("image: maxval for uint8 must be in 1..255");
        if (im.dtype == PixelType::U16 && (im.maxval < 1 || im.maxval > 65535))
            throw std::invalid_argument("image: maxval for uint16 must be in 1..65535");
        if (im.dtype == PixelType::F32 && im.maxval != 0)
            throw std::invalid_argument(
                "image: maxval applies to integer dtypes (uint8/uint16); omit it for float32");
    } else {
        im.maxval = im.dtype == PixelType::U8    ? 255u
                    : im.dtype == PixelType::U16 ? 65535u
                                                 : 0u;
    }
    return im;
}

}  // namespace

void register_image(nb::module_ &m) {
    nb::class_<Image>(m, "Image")
        .def_prop_ro("height", [](const Image &im) { return im.height; })
        .def_prop_ro("width", [](const Image &im) { return im.width; })
        .def_prop_ro("channels", [](const Image &im) { return im.channels; })
        .def_prop_ro("dtype", [](const Image &im) { return image_dtype_name(im.dtype); })
        // dtype-polymorphic zero-copy view. Because the getter returns a
        // dynamically-typed nb::object, rv_policy::reference_internal cannot
        // attach the owner the way the fixed-dtype records (GaussianCloud,
        // PosedViewSet) do through a bare-ndarray return. Instead
        // sio::view(self, ...) bakes `self` in as the array's owner, so the
        // backing buffer stays alive for as long as the returned array does
        // (the gc.collect() lifetime test in tests/records/test_image.py pins
        // this). nb::handle_t<Image> hands us the Python self to use as owner.
        .def_prop_ro("pixels", [](nb::handle_t<Image> self) -> nb::object {
            const Image &im = nb::cast<const Image &>(self);
            std::vector<size_t> shape =
                im.channels == 1 ? std::vector<size_t>{im.height, im.width}  // gray -> (H,W)
                                 : std::vector<size_t>{im.height, im.width, im.channels};  // -> (H,W,C)
            switch (im.dtype) {
                case PixelType::U8: return nb::cast(sio::view(self, im.u8.data(), shape));
                case PixelType::U16: return nb::cast(sio::view(self, im.u16.data(), shape));
                default: return nb::cast(sio::view(self, im.f32.data(), shape));
            }
        })
        // conventions the codec recorded (metadata):
        .def_prop_ro("color_space", [](const Image &im) { return im.color_space; })
        .def_prop_ro("alpha_mode", [](const Image &im) { return im.alpha_mode; })
        .def_prop_ro("maxval", [](const Image &im) { return im.maxval; })
        // fixed canonical tags (derived, like GaussianCloud.quaternion_order):
        .def_prop_ro("channel_order",
                     [](const Image &im) {
                         return im.channels == 1 ? "gray" : (im.channels == 3 ? "rgb" : "rgba");
                     })
        .def_prop_ro("row_order", [](const Image &) { return "top_to_bottom"; })
        .def("__repr__", [](const Image &im) {
            return "<Image " + std::to_string(im.height) + "x" + std::to_string(im.width) + "x" +
                   std::to_string(im.channels) + " " + image_dtype_name(im.dtype) + " " +
                   im.color_space + ">";
        });

    m.def("image", &make_image, "pixels"_a, "color_space"_a = nb::none(),
          "alpha_mode"_a = nb::none(), "maxval"_a = nb::none(),
          "Build an Image from a (H,W)/(H,W,C) uint8/uint16/float32 array (numpy or torch); "
          "C in {1,3,4}; (H,W,1) normalizes to grayscale; conventions (color_space, alpha_mode, "
          "maxval) recorded as metadata.");
}
