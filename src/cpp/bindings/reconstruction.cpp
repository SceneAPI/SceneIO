#include "bindings/registry.hpp"

void register_colmap(nanobind::module_ &);
void register_transforms_json(nanobind::module_ &);
void register_pose_text(nanobind::module_ &);
void register_colmap_txt(nanobind::module_ &);
void register_bundler(nanobind::module_ &);
void register_bal(nanobind::module_ &);
void register_nvm(nanobind::module_ &);
void register_openmvg(nanobind::module_ &);
void register_euroc_state(nanobind::module_ &);
void register_g2o(nanobind::module_ &);
void register_colmap_db(nanobind::module_ &);

namespace sio::bindings {
namespace {

constexpr RegistrationDescriptor REGISTRATIONS[] = {
    {1, "colmap", &::register_colmap},
    {13, "transforms_json", &::register_transforms_json},
    {14, "pose_text", &::register_pose_text},
    {17, "colmap_txt", &::register_colmap_txt},
    {20, "bundler", &::register_bundler},
    {21, "bal", &::register_bal},
    {22, "nvm", &::register_nvm},
    {23, "openmvg", &::register_openmvg},
    {36, "euroc_state", &::register_euroc_state},
    {38, "g2o", &::register_g2o},
    {39, "colmap_db", &::register_colmap_db},
};

constexpr CodecDescriptor CODECS[] = {
    {1,
     "colmap_sparse",
     "reconstruction",
     symbols("read_colmap_sparse"),
     symbols("write_colmap_sparse"),
     symbols(),
     symbols("read_colmap_sparse"),
     symbols("write_colmap_sparse"),
     symbols("read_colmap_sparse_image")},
    {15,
     "transforms_json",
     "reconstruction",
     symbols("read_transforms_json"),
     symbols("write_transforms_json"),
     symbols("_inspect_transforms_json"),
     symbols("read_transforms_json"),
     symbols("write_transforms_json"),
     symbols()},
    {16,
     "tum",
     "reconstruction",
     symbols("read_tum"),
     symbols("write_tum"),
     symbols(),
     symbols("read_tum"),
     symbols("write_tum"),
     symbols()},
    {17,
     "kitti",
     "reconstruction",
     symbols("read_kitti"),
     symbols("write_kitti"),
     symbols(),
     symbols("read_kitti"),
     symbols("write_kitti"),
     symbols()},
    {18,
     "euroc_state",
     "reconstruction",
     symbols("read_euroc_state"),
     symbols("write_euroc_state"),
     symbols("_inspect_euroc_state"),
     symbols("read_euroc_state"),
     symbols("write_euroc_state"),
     symbols("read_euroc_state_states")},
    {23,
     "g2o",
     "reconstruction",
     symbols("read_g2o"),
     symbols("write_g2o"),
     symbols("_inspect_g2o"),
     symbols("read_g2o"),
     symbols("write_g2o"),
     symbols()},
    {24,
     "colmap_db",
     "reconstruction",
     symbols("read_colmap_db"),
     symbols("write_colmap_db"),
     symbols("inspect_colmap_db"),
     symbols("read_colmap_db"),
     symbols("write_colmap_db"),
     symbols("read_colmap_db_image", "read_colmap_db_pair")},
    {38,
     "colmap_sparse_txt",
     "reconstruction",
     symbols("read_colmap_txt"),
     symbols("write_colmap_txt"),
     symbols("_inspect_colmap_txt"),
     symbols("read_colmap_txt"),
     symbols("write_colmap_txt"),
     symbols("read_colmap_txt_image")},
    {45,
     "bundler",
     "reconstruction",
     symbols("read_bundler"),
     symbols("write_bundler"),
     symbols("_inspect_bundler"),
     symbols("read_bundler"),
     symbols("write_bundler"),
     symbols()},
    {46,
     "bal",
     "reconstruction",
     symbols("read_bal"),
     symbols("write_bal"),
     symbols("_inspect_bal"),
     symbols("read_bal"),
     symbols("write_bal"),
     symbols()},
    {47,
     "nvm",
     "reconstruction",
     symbols("read_nvm"),
     symbols("write_nvm"),
     symbols("_inspect_nvm"),
     symbols("read_nvm"),
     symbols("write_nvm"),
     symbols()},
    {48,
     "openmvg",
     "reconstruction",
     symbols("read_openmvg"),
     symbols("write_openmvg"),
     symbols("_inspect_openmvg"),
     symbols("read_openmvg"),
     symbols("write_openmvg"),
     symbols()},
};

constexpr FamilyBindings FAMILY{
    "reconstruction",
    REGISTRATIONS,
    sizeof(REGISTRATIONS) / sizeof(REGISTRATIONS[0]),
    CODECS,
    sizeof(CODECS) / sizeof(CODECS[0]),
};

} // namespace

const FamilyBindings &reconstruction_bindings() { return FAMILY; }

} // namespace sio::bindings
