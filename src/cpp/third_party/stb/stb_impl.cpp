// third_party/stb/stb_impl.cpp — the single translation unit that instantiates
// the stb libraries (STB_IMAGE_IMPLEMENTATION / STB_IMAGE_WRITE_IMPLEMENTATION
// must appear in exactly one TU). Isolated here so stb's own warnings stay
// contained and the codecs include only the (gated) declarations. The gates in
// stb_config.h are included first so this TU's compiled API matches the codecs'.
#include "stb_config.h"

#define STB_IMAGE_IMPLEMENTATION
#include "stb_image.h"

#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"
