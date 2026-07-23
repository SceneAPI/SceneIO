// third_party/stb/stb_config.h — shared compile-gate configuration for the stb
// single-file libraries. Included FIRST (before stb_image.h / stb_image_write.h)
// by BOTH the implementation TU (stb_impl.cpp) and every codec TU, so the gates
// never drift — a mismatch would silently change the compiled API surface.
//
// STBI_ONLY_JPEG + STBI_ONLY_HDR compile ONLY the JPEG and Radiance-HDR decoders
// (dropping PNG/BMP/GIF/PSD/PIC/PNM/TGA and, with PNG, stb's own zlib — we never
// link it; PNG is lodepng's job). STBI_NO_STDIO drops the decode-side fopen paths
// (we only decode from memory).
//
// NOTE: we deliberately DON'T define STBI_WRITE_NO_STDIO. In this stb version the
// whole HDR write section — including the memory-based stbi_write_hdr_to_func we
// call — sits inside `#ifndef STBI_WRITE_NO_STDIO` (stb_image_write.h:637-804), so
// that gate would remove it and hdr.cpp fails to link. The only cost of leaving it
// is a few unused fopen-based writer functions compiled into the TU.
#pragma once
#define STBI_NO_STDIO
#define STBI_ONLY_JPEG
#define STBI_ONLY_HDR
