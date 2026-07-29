// records/feature_match.hpp -- typed per-image features, ragged image-pair
// matches, and the lossless core payload of a COLMAP feature database.
#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

#include "records/reconstruction.hpp"
#include "records/tensor_dict.hpp"

constexpr int64_t kColmapMaxNumImages = 2147483647LL;

struct FeatureSet {
    uint32_t image_id = 0;
    std::string image_name;
    uint32_t camera_id = 0;
    uint64_t image_width = 0;
    uint64_t image_height = 0;
    bool has_time_id = false;
    int64_t time_id = 0;
    int32_t extractor_type = -1;

    bool keypoints_present = true;
    size_t rows = 0;
    size_t keypoint_columns = 2;
    std::vector<float> keypoints;  // rows * keypoint_columns

    bool has_descriptors = false;
    bool descriptor_dtype_present = false;
    bool descriptor_dim_present = false;
    sio::DType descriptor_dtype = sio::DType::U8;
    size_t descriptor_columns = 0;
    bool extractor_type_name_present = false;
    std::string extractor_type_name;
    std::vector<uint8_t> descriptors;

    bool keypoint_colors_present = false;
    std::vector<uint8_t> keypoint_colors;  // rows * 3 RGB

    bool has_scores = false;
    std::vector<float> scores;  // rows

    bool quality_present = false;
    double quality = 0.0;
};

struct MatchGraph {
    size_t pair_count = 0;
    std::vector<int64_t> pair_ids;       // pair_count
    std::vector<uint32_t> image_pairs;   // pair_count * 2, low id first
    std::vector<uint8_t> match_present;  // pair_count, DB row exists
    std::vector<uint8_t> geometry_present;  // pair_count, DB row exists

    std::vector<uint64_t> match_offsets;  // pair_count + 1
    std::vector<uint32_t> matches;        // 2 * match_offsets.back()
    bool has_scores = false;
    std::vector<uint8_t> match_score_present;  // pair_count
    std::vector<float> scores;            // match_offsets.back()

    // COLMAP stores geometrically verified correspondences as another ragged
    // list, not as a bit mask over the raw table. Keeping that list exactly
    // preserves duplicates and DBs whose verified pair has no raw-match row.
    std::vector<uint64_t> verified_offsets;  // pair_count + 1
    std::vector<uint32_t> verified_matches;  // 2 * verified_offsets.back()

    std::vector<int32_t> configs;       // pair_count
    std::vector<uint8_t> F_present;     // pair_count, canonical 0/1
    std::vector<uint8_t> E_present;     // pair_count
    std::vector<uint8_t> H_present;     // pair_count
    std::vector<double> F;              // pair_count * 9
    std::vector<double> E;              // pair_count * 9
    std::vector<double> H;              // pair_count * 9
    std::vector<uint8_t> pose_present;  // pair_count
    std::vector<double> qvecs;          // pair_count * 4, WXYZ
    std::vector<double> tvecs;          // pair_count * 3

    // Current COLMAP stores optional recovered camera models beside each
    // verified pair. Vectors retain one slot per pair; presence and
    // prior-focal flags preserve SQL NULL independently from zero values.
    std::vector<uint8_t> camera1_present;
    std::vector<uint8_t> camera2_present;
    std::vector<Camera> recovered_camera1;
    std::vector<Camera> recovered_camera2;
    std::vector<uint8_t> camera1_prior_focal_length;
    std::vector<uint8_t> camera2_prior_focal_length;

    std::vector<uint8_t> provenance_present;
    std::vector<uint32_t> source_flags;
    std::vector<uint8_t> retrieval_score_present;
    std::vector<float> retrieval_scores;

    size_t num_pairs() const { return pair_count; }
    size_t num_matches() const {
        return match_offsets.empty()
                   ? 0
                   : static_cast<size_t>(match_offsets.back());
    }
    size_t num_verified_matches() const {
        return verified_offsets.empty()
                   ? 0
                   : static_cast<size_t>(verified_offsets.back());
    }
};

struct ColmapRigFrameSet {
    std::vector<uint32_t> rig_ids;
    std::vector<int32_t> rig_ref_sensor_types;
    std::vector<uint32_t> rig_ref_sensor_ids;
    std::vector<uint64_t> rig_sensor_offsets{0};
    std::vector<int32_t> rig_sensor_types;
    std::vector<uint32_t> rig_sensor_ids;
    std::vector<uint8_t> rig_sensor_pose_present;
    std::vector<double> rig_sensor_qvecs;  // WXYZ sensor_from_rig
    std::vector<double> rig_sensor_tvecs;

    std::vector<uint32_t> frame_ids;
    std::vector<uint32_t> frame_rig_ids;
    std::vector<uint64_t> frame_data_offsets{0};
    std::vector<uint64_t> frame_data_ids;
    std::vector<int32_t> frame_sensor_types;
    std::vector<uint32_t> frame_sensor_ids;

    size_t num_rigs() const { return rig_ids.size(); }
    size_t num_frames() const { return frame_ids.size(); }
    size_t num_rig_sensors() const {
        return rig_sensor_ids.size();
    }
    size_t num_frame_data() const {
        return frame_data_ids.size();
    }
};

struct ColmapPosePriorSet {
    // False identifies the stock 3.13 image-linked table. Readers normalize
    // those rows into the same data/sensor identity arrays while retaining
    // the source layout for an exact-profile writer.
    bool generalized = false;
    std::vector<uint32_t> prior_ids;
    std::vector<uint64_t> corr_data_ids;
    std::vector<uint32_t> corr_sensor_ids;
    std::vector<int32_t> corr_sensor_types;
    std::vector<int32_t> coordinate_systems;
    // Presence is SQL BLOB presence, not semantic all-finite validity.
    // Exact-size upstream BLOBs can contain all-NaN optional defaults.
    std::vector<uint8_t> position_present;
    std::vector<double> positions;
    std::vector<uint8_t> position_covariance_present;
    std::vector<double> position_covariances;  // row-major N*3*3
    std::vector<uint8_t> gravity_present;
    std::vector<double> gravities;
    std::vector<uint8_t> rotation_present;
    std::vector<double> rotations;  // XYZW cam_from_world
    std::vector<uint8_t> rotation_covariance_present;
    std::vector<double> rotation_covariances;  // row-major N*3*3
    std::vector<uint8_t> pose_covariance_present;
    std::vector<double> pose_covariances;  // row-major N*6*6

    size_t size() const { return prior_ids.size(); }
};

struct ColmapMarkerSet {
    std::vector<uint32_t> marker_ids;
    std::vector<std::string> labels;
    std::vector<int32_t> types;
    std::vector<uint8_t> world_position_present;
    std::vector<double> world_positions;
    std::vector<uint8_t> world_covariance_present;
    std::vector<double> world_covariances;  // row-major N*3*3
    std::vector<uint64_t> point3d_ids;
    std::vector<uint8_t> enabled;

    std::vector<uint32_t> projection_marker_ids;
    std::vector<uint32_t> projection_image_ids;
    std::vector<double> projection_xy;
    std::vector<double> projection_sizes;
    std::vector<uint8_t> projection_pinned;
    std::vector<uint32_t> projection_point2d_indices;

    size_t num_markers() const { return marker_ids.size(); }
    size_t num_projections() const {
        return projection_marker_ids.size();
    }
};

struct ColmapVideoMetadataSet {
    std::vector<uint32_t> video_ids;
    std::vector<std::string> names;
    std::vector<uint8_t> source_path_present;
    std::vector<std::string> source_paths;
    std::vector<uint8_t> content_hash_present;
    std::vector<std::string> content_hashes;
    std::vector<int32_t> widths;
    std::vector<int32_t> heights;
    std::vector<int64_t> num_frames;
    std::vector<double> fps;
    std::vector<double> duration_seconds;
    std::vector<uint8_t> codec_name_present;
    std::vector<std::string> codec_names;
    std::vector<uint8_t> sync_group_present;
    std::vector<std::string> sync_groups;

    std::vector<uint32_t> frame_video_ids;
    std::vector<uint32_t> frame_image_ids;
    std::vector<int64_t> frame_ids;
    std::vector<uint8_t> pts_present;
    std::vector<double> pts_seconds;
    std::vector<uint8_t> time_id_present;
    std::vector<uint32_t> time_ids;

    size_t num_videos() const { return video_ids.size(); }
    size_t num_video_frames() const {
        return frame_video_ids.size();
    }
};

struct ColmapMaxxSchemaInfo {
    bool present = false;
    uint32_t schema_version = 0;
    uint32_t minimum_reader_version = 0;
    std::string producer_version;
    std::string producer_commit;
};

struct ColmapDatabase {
    std::vector<Camera> cameras;
    std::vector<uint8_t> prior_focal_length;  // cameras.size(), 0/1
    std::vector<FeatureSet> features;
    MatchGraph match_graph;
    ColmapRigFrameSet rig_frames;
    ColmapPosePriorSet pose_priors;
    ColmapMarkerSet markers;
    ColmapVideoMetadataSet video_metadata;
    ColmapMaxxSchemaInfo maxx_schema_info;
    // Exact on-disk schema identity. Records built through colmap_database()
    // use SceneIO's legacy hybrid profile until the caller selects one of the
    // exact profile writers. Readers populate both values from SQLite.
    std::string profile = "sceneio-hybrid-v1";
    int32_t application_id = 0;
    int32_t user_version = 3140002;

    size_t num_cameras() const { return cameras.size(); }
    size_t num_images() const { return features.size(); }
};

int64_t colmap_pair_id(uint32_t image_id1, uint32_t image_id2);
void validate_feature_set(
    const FeatureSet &features, const char *context = "feature_set");
void validate_match_graph(
    const MatchGraph &graph, const char *context = "match_graph");
void validate_colmap_rig_frames(
    const ColmapRigFrameSet &value,
    const char *context = "colmap_rig_frames");
void validate_colmap_pose_priors(
    const ColmapPosePriorSet &value,
    const char *context = "colmap_pose_priors");
void validate_colmap_markers(
    const ColmapMarkerSet &value,
    const char *context = "colmap_markers");
void validate_colmap_videos(
    const ColmapVideoMetadataSet &value,
    const char *context = "colmap_video_metadata");
void validate_colmap_database(
    const ColmapDatabase &database,
    const char *context = "colmap_database");
