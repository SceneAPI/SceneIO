// third_party/tinyexr/tinyexr_impl.cpp — the single TU that instantiates tinyexr.
// TINYEXR_USE_MINIZ defaults to 1, so tinyexr's `#include <miniz.h>` resolves to
// OUR vendored miniz (miniz_static's include dir is PUBLIC and propagates here);
// we never compile tinyexr's own bundled deps/miniz, so there is no second zlib.
// O4 enables tinyexr's independent scanline-block workers, capped at eight so a
// single image cannot oversubscribe large CI/host machines. CMake links the
// portable Threads target on platforms that require an explicit pthread link.
// Isolated here so tinyexr's warnings stay contained and exr.cpp includes only
// the declarations.
#define TINYEXR_USE_THREAD 1
#define TINYEXR_MAX_THREADS 8
#define TINYEXR_IMPLEMENTATION
#include "tinyexr.h"
