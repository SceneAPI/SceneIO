#include <nanobind/nanobind.h>

#include <cstdlib>
#include <cstring>
#include <new>

namespace nb = nanobind;

bool sceneio_test_lazperf_default_corrector_rejects();

#if defined(__GNUC__) || defined(__clang__)
#define SCENEIO_LSAN_NOINLINE __attribute__((noinline))
#define SCENEIO_LSAN_VISIBLE __attribute__((visibility("default")))
#else
#define SCENEIO_LSAN_NOINLINE
#define SCENEIO_LSAN_VISIBLE
#endif

namespace {

constexpr std::size_t kControlBytes = 12'345;

void touch_allocation(void *allocation) {
    std::memset(allocation, 0x5A, kControlBytes);
#if defined(__GNUC__) || defined(__clang__)
    __asm__ __volatile__("" : : "r"(allocation) : "memory");
#endif
}

}  // namespace

extern "C" SCENEIO_LSAN_NOINLINE SCENEIO_LSAN_VISIBLE void
sceneio_lsan_test_allocate_clean() {
    void *allocation = std::malloc(kControlBytes);
    if (allocation == nullptr) {
        throw std::bad_alloc();
    }
    touch_allocation(allocation);
    std::free(allocation);
}

extern "C" SCENEIO_LSAN_NOINLINE SCENEIO_LSAN_VISIBLE void
sceneio_lsan_test_allocate_leak() {
    void *allocation = std::malloc(kControlBytes);
    if (allocation == nullptr) {
        throw std::bad_alloc();
    }
    touch_allocation(allocation);
}

NB_MODULE(_native_test, module) {
    module.doc() =
        "Off-by-default native sanitizer controls for SceneIO CI only.";
    module.def("allocate_clean", &sceneio_lsan_test_allocate_clean);
    module.def("allocate_leak", &sceneio_lsan_test_allocate_leak);
    module.def(
        "lazperf_default_corrector_rejects",
        &sceneio_test_lazperf_default_corrector_rejects);
}
