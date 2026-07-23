// third_party/tinyexr/tinyexr_impl.cpp — the single TU that instantiates tinyexr.
// TINYEXR_USE_MINIZ defaults to 1, so tinyexr's `#include <miniz.h>` resolves to
// OUR vendored miniz (miniz_static's include dir is PUBLIC and propagates here);
// we never compile tinyexr's own bundled deps/miniz, so there is no second zlib.
// Threads stay off (TINYEXR_USE_THREAD default 0) to avoid a C++11-thread surface.
// Isolated here so tinyexr's warnings stay contained and exr.cpp includes only
// the declarations.
#define TINYEXR_IMPLEMENTATION
#include "tinyexr.h"
