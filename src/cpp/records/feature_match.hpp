// records/feature_match.hpp -- typed per-image features, ragged image-pair
// matches, and the lossless core payload of a COLMAP feature database.
#pragma once

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
    sio::DType descriptor_dtype = sio::DType::U8;
    size_t descriptor_columns = 0;
    std::vector<uint8_t> descriptors;

    bool has_scores = false;
    std::vector<float> scores;  // rows
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

    size_t size() const { return prior_ids.size(); }
};

struct ColmapDatabase {
    std::vector<Camera> cameras;
    std::vector<uint8_t> prior_focal_length;  // cameras.size(), 0/1
    std::vector<FeatureSet> features;
    MatchGraph match_graph;
    ColmapRigFrameSet rig_frames;
    ColmapPosePriorSet pose_priors;
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
void validate_colmap_database(
    const ColmapDatabase &database,
    const char *context = "colmap_database");
