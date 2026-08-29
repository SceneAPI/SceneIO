#include "bindings/registry.hpp"

void register_camera_calibration(nanobind::module_ &);

namespace sio::bindings {
namespace {

constexpr RegistrationDescriptor REGISTRATIONS[] = {
    {37, "camera_calibration", &::register_camera_calibration},
};

constexpr CodecDescriptor CODECS[] = {
    {19,
     "opencv_yaml",
     "calibration",
     symbols("read_opencv_yaml"),
     symbols("write_opencv_yaml"),
     symbols("_inspect_opencv_yaml"),
     symbols("read_opencv_yaml"),
     symbols("write_opencv_yaml"),
     symbols()},
    {20,
     "opencv_xml",
     "calibration",
     symbols("read_opencv_xml"),
     symbols("write_opencv_xml"),
     symbols("_inspect_opencv_xml"),
     symbols("read_opencv_xml"),
     symbols("write_opencv_xml"),
     symbols()},
    {21,
     "ros_camera_info",
     "calibration",
     symbols("read_ros_camera_info"),
     symbols("write_ros_camera_info"),
     symbols("_inspect_ros_camera_info"),
     symbols("read_ros_camera_info"),
     symbols("write_ros_camera_info"),
     symbols()},
    {22,
     "kalibr",
     "calibration",
     symbols("read_kalibr"),
     symbols("write_kalibr"),
     symbols("_inspect_kalibr"),
     symbols("read_kalibr"),
     symbols("write_kalibr"),
     symbols()},
};

constexpr FamilyBindings FAMILY{
    "calibration",
    REGISTRATIONS,
    sizeof(REGISTRATIONS) / sizeof(REGISTRATIONS[0]),
    CODECS,
    sizeof(CODECS) / sizeof(CODECS[0]),
};

} // namespace

const FamilyBindings &calibration_bindings() { return FAMILY; }

} // namespace sio::bindings
