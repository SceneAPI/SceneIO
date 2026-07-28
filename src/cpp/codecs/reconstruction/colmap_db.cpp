// codecs/reconstruction/colmap_db.cpp -- COLMAP SQLite feature/match database codec.
//
// Reads open SQLITE_OPEN_READONLY and copy only typed BLOB payloads into the
// compiled records. Writes validate the complete aggregate before opening the
// path, then replace the supported schema inside one rollback-capable
// transaction. The vendored SQLite amalgamation is public domain and linked
// privately into sceneio._core.
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <limits>
#include <map>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#include "records/feature_match.hpp"
#include "sqlite3.h"

using namespace nb::literals;

namespace {

constexpr sqlite3_int64 kMaxBlobBytes = 1000000000;

[[noreturn]] void sqlite_error(
    sqlite3 *database, const std::string &context,
    int result) {
    const char *message =
        database ? sqlite3_errmsg(database) : sqlite3_errstr(result);
    throw std::runtime_error(
        "COLMAP database: " + context + ": " +
        (message ? std::string(message) : "SQLite error") +
        " (code " + std::to_string(result) + ")");
}

void check(
    sqlite3 *database, int result,
    const std::string &context) {
    if (result != SQLITE_OK)
        sqlite_error(database, context, result);
}

class Database {
public:
    Database(const std::string &path, int flags) {
        if (path.find('\0') != std::string::npos)
            throw std::invalid_argument(
                "COLMAP database: path cannot contain embedded NUL");
        const int result = sqlite3_open_v2(
            path.c_str(), &database_, flags, nullptr);
        if (result != SQLITE_OK) {
            const std::string message =
                database_ ? sqlite3_errmsg(database_)
                          : sqlite3_errstr(result);
            if (database_) sqlite3_close_v2(database_);
            database_ = nullptr;
            throw std::runtime_error(
                "COLMAP database: cannot open '" + path +
                "': " + message);
        }
        sqlite3_extended_result_codes(database_, 1);
        sqlite3_busy_timeout(database_, 250);
    }
    Database(const Database &) = delete;
    Database &operator=(const Database &) = delete;
    ~Database() {
        if (database_) sqlite3_close_v2(database_);
    }
    sqlite3 *get() const { return database_; }

private:
    sqlite3 *database_ = nullptr;
};

class Statement {
public:
    Statement(sqlite3 *database, const std::string &sql)
        : database_(database) {
        const int result = sqlite3_prepare_v3(
            database_, sql.data(),
            static_cast<int>(sql.size()),
            SQLITE_PREPARE_PERSISTENT, &statement_,
            nullptr);
        if (result != SQLITE_OK) {
            if (statement_) sqlite3_finalize(statement_);
            statement_ = nullptr;
            sqlite_error(database_, "preparing SQL", result);
        }
    }
    Statement(const Statement &) = delete;
    Statement &operator=(const Statement &) = delete;
    ~Statement() {
        if (statement_) sqlite3_finalize(statement_);
    }
    sqlite3_stmt *get() const { return statement_; }
    bool row() {
        const int result = sqlite3_step(statement_);
        if (result == SQLITE_ROW) return true;
        if (result == SQLITE_DONE) return false;
        sqlite_error(database_, "executing SQL", result);
    }
    void done() {
        const int result = sqlite3_step(statement_);
        if (result != SQLITE_DONE)
            sqlite_error(database_, "executing SQL", result);
        reset();
    }
    void reset() {
        check(database_, sqlite3_reset(statement_), "resetting SQL");
        check(
            database_, sqlite3_clear_bindings(statement_),
            "clearing SQL bindings");
    }

private:
    sqlite3 *database_;
    sqlite3_stmt *statement_ = nullptr;
};

void execute(sqlite3 *database, const std::string &sql) {
    char *message = nullptr;
    const int result = sqlite3_exec(
        database, sql.c_str(), nullptr, nullptr, &message);
    if (result == SQLITE_OK) return;
    const std::string detail =
        message ? std::string(message) : sqlite3_errmsg(database);
    sqlite3_free(message);
    throw std::runtime_error(
        "COLMAP database: executing SQL: " + detail +
        " (code " + std::to_string(result) + ")");
}

class Transaction {
public:
    explicit Transaction(sqlite3 *database)
        : database_(database) {
        execute(database_, "BEGIN IMMEDIATE");
    }
    Transaction(const Transaction &) = delete;
    Transaction &operator=(const Transaction &) = delete;
    ~Transaction() {
        if (!committed_)
            sqlite3_exec(
                database_, "ROLLBACK", nullptr, nullptr, nullptr);
    }
    void commit() {
        execute(database_, "COMMIT");
        committed_ = true;
    }

private:
    sqlite3 *database_;
    bool committed_ = false;
};

void require_little_endian() {
    if (!sio::host_is_le())
        throw std::runtime_error(
            "COLMAP database: this build requires a "
            "little-endian host for COLMAP BLOBs");
}

int64_t integer(
    sqlite3_stmt *statement, int column,
    const char *name) {
    if (sqlite3_column_type(statement, column) != SQLITE_INTEGER)
        throw std::invalid_argument(
            std::string("COLMAP database: ") + name +
            " must be INTEGER");
    return sqlite3_column_int64(statement, column);
}

size_t extent(
    sqlite3_stmt *statement, int column,
    const char *name) {
    const int64_t value = integer(statement, column, name);
    if (value < 0 ||
        static_cast<uint64_t>(value) >
            std::numeric_limits<size_t>::max())
        throw std::invalid_argument(
            std::string("COLMAP database: ") + name +
            " is outside the host size range");
    return static_cast<size_t>(value);
}

uint32_t image_id_value(
    sqlite3_stmt *statement, int column,
    const char *name) {
    const int64_t value = integer(statement, column, name);
    if (value < 0 || value >= kColmapMaxNumImages)
        throw std::invalid_argument(
            std::string("COLMAP database: ") + name +
            " must be in 0..2147483646");
    return static_cast<uint32_t>(value);
}

int32_t int32_value(
    sqlite3_stmt *statement, int column,
    const char *name) {
    const int64_t value = integer(statement, column, name);
    if (value < std::numeric_limits<int32_t>::min() ||
        value > std::numeric_limits<int32_t>::max())
        throw std::invalid_argument(
            std::string("COLMAP database: ") + name +
            " is outside int32");
    return static_cast<int32_t>(value);
}

std::string text(
    sqlite3_stmt *statement, int column,
    const char *name) {
    if (sqlite3_column_type(statement, column) != SQLITE_TEXT)
        throw std::invalid_argument(
            std::string("COLMAP database: ") + name +
            " must be TEXT");
    const auto *data = sqlite3_column_text(statement, column);
    const int bytes = sqlite3_column_bytes(statement, column);
    if (bytes < 0 || (!data && bytes != 0))
        throw std::invalid_argument(
            std::string("COLMAP database: invalid ") + name);
    return std::string(
        reinterpret_cast<const char *>(data),
        static_cast<size_t>(bytes));
}

size_t checked_blob_extent(
    size_t rows, size_t columns, size_t itemsize,
    const char *name) {
    if (columns != 0 &&
        rows > std::numeric_limits<size_t>::max() / columns)
        throw std::invalid_argument(
            std::string("COLMAP database: ") + name +
            " element count overflows size_t");
    const size_t elements = rows * columns;
    if (itemsize != 0 &&
        elements >
            std::numeric_limits<size_t>::max() / itemsize)
        throw std::invalid_argument(
            std::string("COLMAP database: ") + name +
            " byte count overflows size_t");
    const size_t bytes = elements * itemsize;
    if (bytes > static_cast<size_t>(kMaxBlobBytes))
        throw std::invalid_argument(
            std::string("COLMAP database: ") + name +
            " exceeds the 1,000,000,000-byte bound");
    return bytes;
}

const uint8_t *checked_blob(
    sqlite3_stmt *statement, int column, size_t expected,
    const char *name, bool empty_is_absent = false,
    bool *present = nullptr) {
    const int type = sqlite3_column_type(statement, column);
    const int bytes = sqlite3_column_bytes(statement, column);
    if (bytes < 0)
        throw std::invalid_argument(
            std::string("COLMAP database: invalid ") + name +
            " byte count");
    const bool is_present =
        type != SQLITE_NULL &&
        (!empty_is_absent || bytes != 0);
    if (present) *present = is_present;
    if (!is_present) {
        if (expected != 0 && !empty_is_absent)
            throw std::invalid_argument(
                std::string("COLMAP database: missing ") + name);
        return nullptr;
    }
    if (type != SQLITE_BLOB)
        throw std::invalid_argument(
            std::string("COLMAP database: ") + name +
            " must be BLOB or NULL");
    if (static_cast<size_t>(bytes) != expected)
        throw std::invalid_argument(
            std::string("COLMAP database: ") + name +
            " byte count disagrees with rows/cols");
    const auto *data = static_cast<const uint8_t *>(
        sqlite3_column_blob(statement, column));
    if (expected != 0 && !data)
        throw std::invalid_argument(
            std::string("COLMAP database: invalid ") + name);
    return data;
}

template <typename T>
std::vector<T> numeric_blob(
    sqlite3_stmt *statement, int column, size_t rows,
    size_t columns, const char *name) {
    const size_t bytes =
        checked_blob_extent(rows, columns, sizeof(T), name);
    const uint8_t *data =
        checked_blob(statement, column, bytes, name);
    std::vector<T> result(rows * columns);
    if (bytes != 0)
        std::memcpy(result.data(), data, bytes);
    return result;
}

std::vector<uint8_t> byte_blob(
    sqlite3_stmt *statement, int column, size_t rows,
    size_t columns, const char *name) {
    const size_t bytes =
        checked_blob_extent(rows, columns, 1, name);
    const uint8_t *data =
        checked_blob(statement, column, bytes, name);
    return bytes == 0
               ? std::vector<uint8_t>{}
               : std::vector<uint8_t>(data, data + bytes);
}

template <typename T>
bool optional_fixed_blob(
    sqlite3_stmt *statement, int column, T *target,
    size_t count, const char *name) {
    const size_t bytes =
        checked_blob_extent(1, count, sizeof(T), name);
    bool present = false;
    const uint8_t *data = checked_blob(
        statement, column, bytes, name,
        /*empty_is_absent=*/true, &present);
    if (present) std::memcpy(target, data, bytes);
    return present;
}

bool table_exists(sqlite3 *database, const std::string &name) {
    Statement statement(
        database,
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name=?1");
    check(
        database,
        sqlite3_bind_text64(
            statement.get(), 1, name.data(),
            static_cast<sqlite3_uint64>(name.size()),
            SQLITE_TRANSIENT, SQLITE_UTF8),
        "binding table name");
    return statement.row();
}

bool column_exists(
    sqlite3 *database, const std::string &table,
    const std::string &column) {
    Statement statement(
        database, "PRAGMA table_info(\"" + table + "\")");
    while (statement.row())
        if (text(statement.get(), 1, "column name") == column)
            return true;
    return false;
}

std::vector<std::string> table_columns(
    sqlite3 *database, const std::string &table) {
    Statement statement(
        database, "PRAGMA table_info(\"" + table + "\")");
    std::vector<std::string> result;
    while (statement.row())
        result.push_back(
            text(statement.get(), 1, "column name"));
    return result;
}

int64_t scalar_count(
    sqlite3 *database, const std::string &table) {
    Statement statement(
        database, "SELECT count(*) FROM \"" + table + "\"");
    if (!statement.row())
        throw std::runtime_error(
            "COLMAP database: count query returned no row");
    return integer(statement.get(), 0, "row count");
}

void validate_schema(sqlite3 *database) {
    static constexpr const char *required[] = {
        "cameras", "images", "keypoints", "descriptors",
        "matches", "two_view_geometries"};
    for (const char *name : required)
        if (!table_exists(database, name))
            throw std::invalid_argument(
                std::string("COLMAP database: missing required table '") +
                name + "'");

    const std::map<std::string, std::vector<std::string>> represented = {
        {"cameras",
         {"camera_id", "model", "width", "height", "params",
          "prior_focal_length"}},
        {"images", {"image_id", "name", "camera_id", "time_id"}},
        {"keypoints", {"image_id", "rows", "cols", "data"}},
        {"descriptors",
         {"image_id", "type", "rows", "cols", "data"}},
        {"matches", {"pair_id", "rows", "cols", "data"}},
        {"two_view_geometries",
         {"pair_id", "rows", "cols", "data", "config", "F", "E",
          "H", "qvec", "tvec"}},
    };
    for (const auto &[table, allowed_values] : represented) {
        const std::unordered_set<std::string> allowed(
            allowed_values.begin(), allowed_values.end());
        for (const std::string &column :
             table_columns(database, table))
            if (!allowed.count(column))
                throw std::invalid_argument(
                    "COLMAP database: unsupported column '" +
                    table + "." + column + "'");
    }
}

void reject_unknown_tables(sqlite3 *database) {
    static const std::unordered_set<std::string> known = {
        "sqlite_sequence",
        "rigs",
        "rig_sensors",
        "cameras",
        "frames",
        "frame_data",
        "images",
        "pose_priors",
        "keypoints",
        "descriptors",
        "matches",
        "two_view_geometries",
        "videos",
        "video_frames",
        "image_qualities",
        "markers",
        "marker_projections",
    };
    Statement statement(
        database,
        "SELECT name FROM sqlite_master "
        "WHERE type='table' ORDER BY name");
    while (statement.row()) {
        const std::string name =
            text(statement.get(), 0, "table name");
        if (!known.count(name))
            throw std::invalid_argument(
                "COLMAP database: unsupported table '" +
                name + "'");
    }
}

void reject_unrepresented_rows(sqlite3 *database) {
    static constexpr const char *unsupported[] = {
        "rigs",
        "rig_sensors",
        "frames",
        "frame_data",
        "pose_priors",
        "videos",
        "video_frames",
        "image_qualities",
        "markers",
        "marker_projections",
    };
    for (const char *name : unsupported)
        if (table_exists(database, name) &&
            scalar_count(database, name) != 0)
            throw std::invalid_argument(
                std::string("COLMAP database: non-empty '") +
                name +
                "' is not representable by ColmapDatabase");
}

int32_t user_version(sqlite3 *database) {
    Statement statement(database, "PRAGMA user_version");
    if (!statement.row())
        throw std::runtime_error(
            "COLMAP database: PRAGMA user_version returned no row");
    return int32_value(statement.get(), 0, "user_version");
}

std::vector<Camera> read_cameras(
    sqlite3 *database, std::vector<uint8_t> &prior) {
    Statement statement(
        database,
        "SELECT camera_id, model, width, height, params, "
        "prior_focal_length FROM cameras ORDER BY camera_id");
    std::vector<Camera> cameras;
    while (statement.row()) {
        Camera camera;
        camera.id =
            image_id_value(statement.get(), 0, "camera_id");
        camera.model_id =
            int32_value(statement.get(), 1, "camera model");
        camera.width =
            static_cast<uint64_t>(
                extent(statement.get(), 2, "camera width"));
        camera.height =
            static_cast<uint64_t>(
                extent(statement.get(), 3, "camera height"));
        const auto info = colmap_model_info(camera.model_id);
        camera.params = numeric_blob<double>(
            statement.get(), 4, 1,
            static_cast<size_t>(info.nparams),
            "camera params");
        const int64_t flag =
            integer(statement.get(), 5, "prior_focal_length");
        if (flag != 0 && flag != 1)
            throw std::invalid_argument(
                "COLMAP database: prior_focal_length must be 0 or 1");
        cameras.push_back(std::move(camera));
        prior.push_back(static_cast<uint8_t>(flag));
    }
    return cameras;
}

std::vector<FeatureSet> read_images(
    sqlite3 *database,
    const std::unordered_map<uint32_t, const Camera *> &cameras) {
    const bool has_time =
        column_exists(database, "images", "time_id");
    Statement statement(
        database,
        has_time
            ? "SELECT image_id, name, camera_id, time_id "
              "FROM images ORDER BY image_id"
            : "SELECT image_id, name, camera_id, NULL "
              "FROM images ORDER BY image_id");
    std::vector<FeatureSet> features;
    while (statement.row()) {
        FeatureSet value;
        value.image_id =
            image_id_value(statement.get(), 0, "image_id");
        value.image_name = text(statement.get(), 1, "image name");
        value.camera_id =
            image_id_value(statement.get(), 2, "image camera_id");
        const auto camera = cameras.find(value.camera_id);
        if (camera == cameras.end())
            throw std::invalid_argument(
                "COLMAP database: image references a missing camera");
        value.image_width = camera->second->width;
        value.image_height = camera->second->height;
        value.keypoints_present = false;
        if (sqlite3_column_type(statement.get(), 3) != SQLITE_NULL) {
            value.time_id =
                integer(statement.get(), 3, "image time_id");
            value.has_time_id = true;
        }
        features.push_back(std::move(value));
    }
    return features;
}

std::unordered_map<uint32_t, size_t> feature_index(
    const std::vector<FeatureSet> &features) {
    std::unordered_map<uint32_t, size_t> result;
    result.reserve(features.size());
    for (size_t index = 0; index < features.size(); ++index)
        if (!result.emplace(features[index].image_id, index).second)
            throw std::invalid_argument(
                "COLMAP database: duplicate image_id");
    return result;
}

void read_keypoints(
    sqlite3 *database, std::vector<FeatureSet> &features,
    const std::unordered_map<uint32_t, size_t> &index) {
    Statement statement(
        database,
        "SELECT image_id, rows, cols, data "
        "FROM keypoints ORDER BY image_id");
    while (statement.row()) {
        const uint32_t image_id =
            image_id_value(statement.get(), 0, "keypoint image_id");
        const auto found = index.find(image_id);
        if (found == index.end())
            throw std::invalid_argument(
                "COLMAP database: keypoints reference a missing image");
        FeatureSet &value = features[found->second];
        if (value.keypoints_present)
            throw std::invalid_argument(
                "COLMAP database: duplicate keypoint row");
        value.rows = extent(statement.get(), 1, "keypoint rows");
        value.keypoint_columns =
            extent(statement.get(), 2, "keypoint cols");
        if (value.keypoint_columns != 2 &&
            value.keypoint_columns != 4 &&
            value.keypoint_columns != 6)
            throw std::invalid_argument(
                "COLMAP database: keypoint cols must be 2, 4, or 6");
        value.keypoints = numeric_blob<float>(
            statement.get(), 3, value.rows,
            value.keypoint_columns, "keypoint data");
        value.keypoints_present = true;
    }
}

void read_descriptors(
    sqlite3 *database, std::vector<FeatureSet> &features,
    const std::unordered_map<uint32_t, size_t> &index) {
    const bool has_type =
        column_exists(database, "descriptors", "type");
    Statement statement(
        database,
        has_type
            ? "SELECT image_id, type, rows, cols, data "
              "FROM descriptors ORDER BY image_id"
            : "SELECT image_id, 0, rows, cols, data "
              "FROM descriptors ORDER BY image_id");
    while (statement.row()) {
        const uint32_t image_id =
            image_id_value(
                statement.get(), 0, "descriptor image_id");
        const auto found = index.find(image_id);
        if (found == index.end())
            throw std::invalid_argument(
                "COLMAP database: descriptors reference a missing image");
        FeatureSet &value = features[found->second];
        if (value.has_descriptors)
            throw std::invalid_argument(
                "COLMAP database: duplicate descriptor row");
        value.extractor_type =
            int32_value(statement.get(), 1, "descriptor type");
        const size_t rows =
            extent(statement.get(), 2, "descriptor rows");
        value.descriptor_columns =
            extent(statement.get(), 3, "descriptor cols");
        if (rows != value.rows)
            throw std::invalid_argument(
                "COLMAP database: descriptor rows disagree "
                "with keypoint rows");
        value.descriptor_dtype = sio::DType::U8;
        value.descriptors = byte_blob(
            statement.get(), 4, rows,
            value.descriptor_columns, "descriptor data");
        value.has_descriptors = true;
    }
}

struct PairRow {
    uint32_t low = 0;
    uint32_t high = 0;
    bool match_present = false;
    std::vector<uint32_t> matches;
    bool geometry_present = false;
    std::vector<uint32_t> verified;
    int32_t config = 0;
    bool F_present = false;
    bool E_present = false;
    bool H_present = false;
    std::array<double, 9> F{};
    std::array<double, 9> E{};
    std::array<double, 9> H{};
    bool pose_present = false;
    std::array<double, 4> qvec{};
    std::array<double, 3> tvec{};
};

std::pair<uint32_t, uint32_t> decode_pair_id(int64_t pair_id) {
    if (pair_id < 0)
        throw std::invalid_argument(
            "COLMAP database: pair_id must be non-negative");
    const int64_t high = pair_id % kColmapMaxNumImages;
    const int64_t low =
        (pair_id - high) / kColmapMaxNumImages;
    if (low < 0 || high < 0 ||
        low >= high || high >= kColmapMaxNumImages ||
        colmap_pair_id(
            static_cast<uint32_t>(low),
            static_cast<uint32_t>(high)) != pair_id)
        throw std::invalid_argument(
            "COLMAP database: pair_id is not canonical");
    return {
        static_cast<uint32_t>(low),
        static_cast<uint32_t>(high)};
}

PairRow &pair_row(
    std::map<int64_t, PairRow> &rows, int64_t pair_id) {
    auto [iterator, inserted] =
        rows.try_emplace(pair_id);
    if (inserted) {
        const auto endpoints = decode_pair_id(pair_id);
        iterator->second.low = endpoints.first;
        iterator->second.high = endpoints.second;
    }
    return iterator->second;
}

void read_matches(
    sqlite3 *database, std::map<int64_t, PairRow> &rows,
    int64_t only_pair = -1) {
    Statement statement(
        database,
        only_pair < 0
            ? "SELECT pair_id, rows, cols, data "
              "FROM matches ORDER BY pair_id"
            : "SELECT pair_id, rows, cols, data "
              "FROM matches WHERE pair_id=?1");
    if (only_pair >= 0)
        check(
            database,
            sqlite3_bind_int64(
                statement.get(), 1, only_pair),
            "binding pair_id");
    while (statement.row()) {
        const int64_t pair_id =
            integer(statement.get(), 0, "pair_id");
        PairRow &row = pair_row(rows, pair_id);
        if (row.match_present)
            throw std::invalid_argument(
                "COLMAP database: duplicate match row");
        const size_t count =
            extent(statement.get(), 1, "match rows");
        const size_t columns =
            extent(statement.get(), 2, "match cols");
        if (columns != 2)
            throw std::invalid_argument(
                "COLMAP database: match cols must be 2");
        row.matches = numeric_blob<uint32_t>(
            statement.get(), 3, count, 2, "match data");
        row.match_present = true;
    }
}

void read_geometries(
    sqlite3 *database, std::map<int64_t, PairRow> &rows,
    int64_t only_pair = -1) {
    Statement statement(
        database,
        only_pair < 0
            ? "SELECT pair_id, rows, cols, data, config, "
              "F, E, H, qvec, tvec "
              "FROM two_view_geometries ORDER BY pair_id"
            : "SELECT pair_id, rows, cols, data, config, "
              "F, E, H, qvec, tvec "
              "FROM two_view_geometries WHERE pair_id=?1");
    if (only_pair >= 0)
        check(
            database,
            sqlite3_bind_int64(
                statement.get(), 1, only_pair),
            "binding pair_id");
    while (statement.row()) {
        const int64_t pair_id =
            integer(statement.get(), 0, "geometry pair_id");
        PairRow &row = pair_row(rows, pair_id);
        if (row.geometry_present)
            throw std::invalid_argument(
                "COLMAP database: duplicate geometry row");
        const size_t count =
            extent(statement.get(), 1, "geometry rows");
        const size_t columns =
            extent(statement.get(), 2, "geometry cols");
        if (columns != 2)
            throw std::invalid_argument(
                "COLMAP database: geometry cols must be 2");
        row.verified = numeric_blob<uint32_t>(
            statement.get(), 3, count, 2, "geometry data");
        row.config =
            int32_value(statement.get(), 4, "geometry config");
        row.F_present = optional_fixed_blob(
            statement.get(), 5, row.F.data(), 9, "F");
        row.E_present = optional_fixed_blob(
            statement.get(), 6, row.E.data(), 9, "E");
        row.H_present = optional_fixed_blob(
            statement.get(), 7, row.H.data(), 9, "H");
        const bool q_present = optional_fixed_blob(
            statement.get(), 8, row.qvec.data(), 4, "qvec");
        const bool t_present = optional_fixed_blob(
            statement.get(), 9, row.tvec.data(), 3, "tvec");
        if (q_present != t_present)
            throw std::invalid_argument(
                "COLMAP database: qvec/tvec presence disagrees");
        row.pose_present = q_present;
        row.geometry_present = true;
    }
}

MatchGraph make_graph(
    const std::map<int64_t, PairRow> &rows) {
    MatchGraph graph;
    graph.pair_count = rows.size();
    graph.pair_ids.reserve(rows.size());
    graph.image_pairs.reserve(rows.size() * 2);
    graph.match_present.reserve(rows.size());
    graph.geometry_present.reserve(rows.size());
    graph.match_offsets.push_back(0);
    graph.verified_offsets.push_back(0);
    graph.configs.reserve(rows.size());
    graph.F_present.reserve(rows.size());
    graph.E_present.reserve(rows.size());
    graph.H_present.reserve(rows.size());
    graph.F.reserve(rows.size() * 9);
    graph.E.reserve(rows.size() * 9);
    graph.H.reserve(rows.size() * 9);
    graph.pose_present.reserve(rows.size());
    graph.qvecs.reserve(rows.size() * 4);
    graph.tvecs.reserve(rows.size() * 3);
    for (const auto &[pair_id, row] : rows) {
        graph.pair_ids.push_back(pair_id);
        graph.image_pairs.push_back(row.low);
        graph.image_pairs.push_back(row.high);
        graph.match_present.push_back(row.match_present);
        graph.geometry_present.push_back(
            row.geometry_present);
        graph.matches.insert(
            graph.matches.end(), row.matches.begin(),
            row.matches.end());
        graph.match_offsets.push_back(
            graph.matches.size() / 2);
        graph.verified_matches.insert(
            graph.verified_matches.end(),
            row.verified.begin(), row.verified.end());
        graph.verified_offsets.push_back(
            graph.verified_matches.size() / 2);
        graph.configs.push_back(row.config);
        graph.F_present.push_back(row.F_present);
        graph.E_present.push_back(row.E_present);
        graph.H_present.push_back(row.H_present);
        graph.F.insert(
            graph.F.end(), row.F.begin(), row.F.end());
        graph.E.insert(
            graph.E.end(), row.E.begin(), row.E.end());
        graph.H.insert(
            graph.H.end(), row.H.begin(), row.H.end());
        graph.pose_present.push_back(row.pose_present);
        graph.qvecs.insert(
            graph.qvecs.end(), row.qvec.begin(),
            row.qvec.end());
        graph.tvecs.insert(
            graph.tvecs.end(), row.tvec.begin(),
            row.tvec.end());
    }
    validate_match_graph(graph, "COLMAP database");
    return graph;
}

ColmapDatabase read_database(const std::string &path) {
    require_little_endian();
    Database connection(
        path, SQLITE_OPEN_READONLY);
    sqlite3 *database = connection.get();
    execute(database, "PRAGMA query_only=ON");
    validate_schema(database);
    reject_unknown_tables(database);
    reject_unrepresented_rows(database);

    ColmapDatabase result;
    result.user_version = user_version(database);
    result.cameras =
        read_cameras(database, result.prior_focal_length);
    std::unordered_map<uint32_t, const Camera *> cameras;
    cameras.reserve(result.cameras.size());
    for (const Camera &camera : result.cameras)
        cameras.emplace(camera.id, &camera);
    result.features = read_images(database, cameras);
    const auto index = feature_index(result.features);
    read_keypoints(database, result.features, index);
    read_descriptors(database, result.features, index);
    std::map<int64_t, PairRow> rows;
    read_matches(database, rows);
    read_geometries(database, rows);
    result.match_graph = make_graph(rows);
    validate_colmap_database(result, "COLMAP database");
    return result;
}

FeatureSet read_feature(
    const std::string &path, uint32_t selected_image_id) {
    require_little_endian();
    Database connection(
        path, SQLITE_OPEN_READONLY);
    sqlite3 *database = connection.get();
    execute(database, "PRAGMA query_only=ON");
    validate_schema(database);
    reject_unknown_tables(database);
    const bool has_time =
        column_exists(database, "images", "time_id");
    Statement image(
        database,
        has_time
            ? "SELECT i.image_id, i.name, i.camera_id, "
              "i.time_id, c.width, c.height "
              "FROM images i JOIN cameras c "
              "ON c.camera_id=i.camera_id "
              "WHERE i.image_id=?1"
            : "SELECT i.image_id, i.name, i.camera_id, "
              "NULL, c.width, c.height "
              "FROM images i JOIN cameras c "
              "ON c.camera_id=i.camera_id "
              "WHERE i.image_id=?1");
    check(
        database,
        sqlite3_bind_int64(
            image.get(), 1, selected_image_id),
        "binding image_id");
    if (!image.row())
        throw std::out_of_range(
            "COLMAP database: image_id " +
            std::to_string(selected_image_id) +
            " was not found");
    FeatureSet result;
    result.image_id =
        image_id_value(image.get(), 0, "image_id");
    result.image_name = text(image.get(), 1, "image name");
    result.camera_id =
        image_id_value(image.get(), 2, "camera_id");
    if (sqlite3_column_type(image.get(), 3) != SQLITE_NULL) {
        result.time_id =
            integer(image.get(), 3, "time_id");
        result.has_time_id = true;
    }
    result.image_width =
        extent(image.get(), 4, "camera width");
    result.image_height =
        extent(image.get(), 5, "camera height");
    if (image.row())
        throw std::invalid_argument(
            "COLMAP database: duplicate image_id");
    result.keypoints_present = false;
    std::vector<FeatureSet> one;
    one.push_back(std::move(result));
    const auto index = feature_index(one);
    {
        Statement keypoints(
            database,
            "SELECT image_id, rows, cols, data "
            "FROM keypoints WHERE image_id=?1");
        check(
            database,
            sqlite3_bind_int64(
                keypoints.get(), 1, selected_image_id),
            "binding image_id");
        if (keypoints.row()) {
            FeatureSet &value = one.front();
            value.rows =
                extent(keypoints.get(), 1, "keypoint rows");
            value.keypoint_columns =
                extent(keypoints.get(), 2, "keypoint cols");
            if (value.keypoint_columns != 2 &&
                value.keypoint_columns != 4 &&
                value.keypoint_columns != 6)
                throw std::invalid_argument(
                    "COLMAP database: keypoint cols must be 2, 4, or 6");
            value.keypoints = numeric_blob<float>(
                keypoints.get(), 3, value.rows,
                value.keypoint_columns, "keypoint data");
            value.keypoints_present = true;
            if (keypoints.row())
                throw std::invalid_argument(
                    "COLMAP database: duplicate keypoint row");
        }
    }
    const bool has_type =
        column_exists(database, "descriptors", "type");
    Statement descriptors(
        database,
        has_type
            ? "SELECT type, rows, cols, data "
              "FROM descriptors WHERE image_id=?1"
            : "SELECT 0, rows, cols, data "
              "FROM descriptors WHERE image_id=?1");
    check(
        database,
        sqlite3_bind_int64(
            descriptors.get(), 1, selected_image_id),
        "binding image_id");
    if (descriptors.row()) {
        FeatureSet &value = one.front();
        value.extractor_type =
            int32_value(descriptors.get(), 0, "descriptor type");
        const size_t rows =
            extent(descriptors.get(), 1, "descriptor rows");
        value.descriptor_columns =
            extent(descriptors.get(), 2, "descriptor cols");
        if (rows != value.rows)
            throw std::invalid_argument(
                "COLMAP database: descriptor rows disagree "
                "with keypoint rows");
        value.descriptor_dtype = sio::DType::U8;
        value.descriptors = byte_blob(
            descriptors.get(), 3, rows,
            value.descriptor_columns, "descriptor data");
        value.has_descriptors = true;
        if (descriptors.row())
            throw std::invalid_argument(
                "COLMAP database: duplicate descriptor row");
    }
    validate_feature_set(one.front(), "COLMAP database");
    return std::move(one.front());
}

size_t image_feature_rows(
    sqlite3 *database, uint32_t image_id) {
    Statement images(
        database,
        "SELECT count(*) FROM images WHERE image_id=?1");
    check(
        database,
        sqlite3_bind_int64(images.get(), 1, image_id),
        "binding image_id");
    if (!images.row())
        throw std::runtime_error(
            "COLMAP database: image count query returned no row");
    const int64_t image_count =
        integer(images.get(), 0, "image count");
    if (image_count != 1)
        throw std::invalid_argument(
            "COLMAP database: match endpoint must reference "
            "exactly one image");

    Statement keypoints(
        database,
        "SELECT rows FROM keypoints WHERE image_id=?1");
    check(
        database,
        sqlite3_bind_int64(keypoints.get(), 1, image_id),
        "binding image_id");
    if (!keypoints.row()) return 0;
    const size_t rows =
        extent(keypoints.get(), 0, "keypoint rows");
    if (keypoints.row())
        throw std::invalid_argument(
            "COLMAP database: duplicate keypoint row");
    return rows;
}

MatchGraph read_pair(
    const std::string &path, uint32_t image_id1,
    uint32_t image_id2) {
    require_little_endian();
    const int64_t selected_pair =
        colmap_pair_id(image_id1, image_id2);
    Database connection(
        path, SQLITE_OPEN_READONLY);
    sqlite3 *database = connection.get();
    execute(database, "PRAGMA query_only=ON");
    validate_schema(database);
    reject_unknown_tables(database);
    std::map<int64_t, PairRow> rows;
    read_matches(database, rows, selected_pair);
    read_geometries(database, rows, selected_pair);
    if (rows.empty())
        throw std::out_of_range(
            "COLMAP database: image pair was not found");
    MatchGraph graph = make_graph(rows);
    const size_t rows_a =
        image_feature_rows(database, graph.image_pairs[0]);
    const size_t rows_b =
        image_feature_rows(database, graph.image_pairs[1]);
    const auto validate_indices =
        [&](const std::vector<uint32_t> &matches,
            const char *kind) {
            for (size_t index = 0;
                 index < matches.size(); index += 2)
                if (matches[index] >= rows_a ||
                    matches[index + 1] >= rows_b)
                    throw std::invalid_argument(
                        std::string("COLMAP database: ") +
                        kind +
                        " index exceeds an endpoint FeatureSet");
        };
    validate_indices(graph.matches, "raw match");
    validate_indices(
        graph.verified_matches, "verified match");
    return graph;
}

void bind_int64(
    sqlite3 *database, sqlite3_stmt *statement,
    int parameter, int64_t value) {
    check(
        database,
        sqlite3_bind_int64(statement, parameter, value),
        "binding INTEGER");
}

void bind_text(
    sqlite3 *database, sqlite3_stmt *statement,
    int parameter, const std::string &value) {
    check(
        database,
        sqlite3_bind_text64(
            statement, parameter, value.data(),
            static_cast<sqlite3_uint64>(value.size()),
            SQLITE_TRANSIENT, SQLITE_UTF8),
        "binding TEXT");
}

void bind_blob(
    sqlite3 *database, sqlite3_stmt *statement,
    int parameter, const void *data, size_t bytes) {
    if (bytes > static_cast<size_t>(kMaxBlobBytes))
        throw std::invalid_argument(
            "COLMAP database: output BLOB exceeds "
            "the 1,000,000,000-byte bound");
    const int result =
        bytes == 0
            ? sqlite3_bind_zeroblob64(statement, parameter, 0)
            : sqlite3_bind_blob64(
                  statement, parameter, data,
                  static_cast<sqlite3_uint64>(bytes),
                  SQLITE_TRANSIENT);
    check(database, result, "binding BLOB");
}

void bind_optional_blob(
    sqlite3 *database, sqlite3_stmt *statement,
    int parameter, bool present, const void *data,
    size_t bytes) {
    if (!present) {
        check(
            database,
            sqlite3_bind_null(statement, parameter),
            "binding NULL");
        return;
    }
    bind_blob(
        database, statement, parameter, data, bytes);
}

void create_schema(sqlite3 *database) {
    execute(
        database,
        R"SQL(
DROP TABLE IF EXISTS marker_projections;
DROP TABLE IF EXISTS markers;
DROP TABLE IF EXISTS image_qualities;
DROP TABLE IF EXISTS video_frames;
DROP TABLE IF EXISTS videos;
DROP TABLE IF EXISTS two_view_geometries;
DROP TABLE IF EXISTS matches;
DROP TABLE IF EXISTS descriptors;
DROP TABLE IF EXISTS keypoints;
DROP TABLE IF EXISTS pose_priors;
DROP TABLE IF EXISTS images;
DROP TABLE IF EXISTS frame_data;
DROP TABLE IF EXISTS frames;
DROP TABLE IF EXISTS rig_sensors;
DROP TABLE IF EXISTS rigs;
DROP TABLE IF EXISTS cameras;

CREATE TABLE rigs(
  rig_id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
  ref_sensor_id INTEGER NOT NULL,
  ref_sensor_type INTEGER NOT NULL);
CREATE TABLE rig_sensors(
  rig_id INTEGER NOT NULL,
  sensor_id INTEGER NOT NULL,
  sensor_type INTEGER NOT NULL,
  sensor_from_rig BLOB,
  FOREIGN KEY(rig_id) REFERENCES rigs(rig_id) ON DELETE CASCADE);
CREATE TABLE cameras(
  camera_id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
  model INTEGER NOT NULL,
  width INTEGER NOT NULL,
  height INTEGER NOT NULL,
  params BLOB,
  prior_focal_length INTEGER NOT NULL);
CREATE TABLE frames(
  frame_id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
  rig_id INTEGER NOT NULL,
  FOREIGN KEY(rig_id) REFERENCES rigs(rig_id) ON DELETE CASCADE);
CREATE TABLE frame_data(
  frame_id INTEGER NOT NULL,
  data_id INTEGER NOT NULL,
  sensor_id INTEGER NOT NULL,
  sensor_type INTEGER NOT NULL,
  FOREIGN KEY(frame_id) REFERENCES frames(frame_id) ON DELETE CASCADE);
CREATE TABLE images(
  image_id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
  name TEXT NOT NULL UNIQUE,
  camera_id INTEGER NOT NULL,
  time_id INTEGER,
  CONSTRAINT image_id_check
    CHECK(image_id >= 0 AND image_id < 2147483647),
  FOREIGN KEY(camera_id) REFERENCES cameras(camera_id));
CREATE TABLE pose_priors(
  pose_prior_id INTEGER PRIMARY KEY NOT NULL,
  corr_data_id INTEGER NOT NULL,
  corr_sensor_id INTEGER NOT NULL,
  corr_sensor_type INTEGER NOT NULL,
  position BLOB,
  position_covariance BLOB,
  gravity BLOB,
  coordinate_system INTEGER NOT NULL,
  rotation BLOB,
  rotation_covariance BLOB,
  pose_covariance BLOB);
CREATE TABLE keypoints(
  image_id INTEGER PRIMARY KEY NOT NULL,
  rows INTEGER NOT NULL,
  cols INTEGER NOT NULL,
  data BLOB,
  FOREIGN KEY(image_id) REFERENCES images(image_id) ON DELETE CASCADE);
CREATE TABLE descriptors(
  image_id INTEGER PRIMARY KEY NOT NULL,
  type INTEGER NOT NULL,
  rows INTEGER NOT NULL,
  cols INTEGER NOT NULL,
  data BLOB,
  FOREIGN KEY(image_id) REFERENCES images(image_id) ON DELETE CASCADE);
CREATE TABLE matches(
  pair_id INTEGER PRIMARY KEY NOT NULL,
  rows INTEGER NOT NULL,
  cols INTEGER NOT NULL,
  data BLOB);
CREATE TABLE two_view_geometries(
  pair_id INTEGER PRIMARY KEY NOT NULL,
  rows INTEGER NOT NULL,
  cols INTEGER NOT NULL,
  data BLOB,
  config INTEGER NOT NULL,
  F BLOB,
  E BLOB,
  H BLOB,
  qvec BLOB,
  tvec BLOB);
CREATE TABLE videos(
  video_id INTEGER PRIMARY KEY NOT NULL,
  name TEXT,
  source_path TEXT,
  content_hash TEXT,
  width INTEGER,
  height INTEGER,
  num_frames INTEGER,
  fps REAL,
  duration_seconds REAL,
  codec_name TEXT,
  sync_group TEXT);
CREATE TABLE video_frames(
  video_id INTEGER NOT NULL,
  image_id INTEGER NOT NULL,
  frame_id INTEGER NOT NULL,
  pts_seconds REAL,
  time_id INTEGER);
CREATE TABLE image_qualities(
  image_id INTEGER PRIMARY KEY NOT NULL,
  quality REAL);
CREATE TABLE markers(
  marker_id INTEGER PRIMARY KEY NOT NULL,
  label TEXT,
  type INTEGER,
  world_position BLOB,
  world_position_cov BLOB,
  point3D_id INTEGER,
  enabled INTEGER);
CREATE TABLE marker_projections(
  marker_id INTEGER NOT NULL,
  image_id INTEGER NOT NULL,
  x REAL,
  y REAL,
  size REAL,
  pinned INTEGER,
  point2D_idx INTEGER);
)SQL");
}

void write_rows(
    sqlite3 *database, const ColmapDatabase &value) {
    Statement cameras(
        database,
        "INSERT INTO cameras("
        "camera_id,model,width,height,params,prior_focal_length"
        ") VALUES(?1,?2,?3,?4,?5,?6)");
    for (size_t index = 0;
         index < value.cameras.size(); ++index) {
        const Camera &camera = value.cameras[index];
        bind_int64(database, cameras.get(), 1, camera.id);
        bind_int64(
            database, cameras.get(), 2, camera.model_id);
        bind_int64(
            database, cameras.get(), 3, camera.width);
        bind_int64(
            database, cameras.get(), 4, camera.height);
        bind_blob(
            database, cameras.get(), 5,
            camera.params.data(),
            camera.params.size() * sizeof(double));
        bind_int64(
            database, cameras.get(), 6,
            value.prior_focal_length[index]);
        cameras.done();
    }

    Statement images(
        database,
        "INSERT INTO images("
        "image_id,name,camera_id,time_id"
        ") VALUES(?1,?2,?3,?4)");
    Statement keypoints(
        database,
        "INSERT INTO keypoints("
        "image_id,rows,cols,data"
        ") VALUES(?1,?2,?3,?4)");
    Statement descriptors(
        database,
        "INSERT INTO descriptors("
        "image_id,type,rows,cols,data"
        ") VALUES(?1,?2,?3,?4,?5)");
    for (const FeatureSet &features : value.features) {
        if (features.has_scores)
            throw std::invalid_argument(
                "COLMAP database writer: feature scores "
                "are not representable");
        if (features.has_descriptors &&
            features.descriptor_dtype != sio::DType::U8)
            throw std::invalid_argument(
                "COLMAP database writer: descriptors "
                "must be uint8");
        bind_int64(
            database, images.get(), 1, features.image_id);
        bind_text(
            database, images.get(), 2, features.image_name);
        bind_int64(
            database, images.get(), 3, features.camera_id);
        if (features.has_time_id)
            bind_int64(
                database, images.get(), 4, features.time_id);
        else
            check(
                database,
                sqlite3_bind_null(images.get(), 4),
                "binding NULL");
        images.done();

        if (features.keypoints_present) {
            bind_int64(
                database, keypoints.get(), 1,
                features.image_id);
            bind_int64(
                database, keypoints.get(), 2, features.rows);
            bind_int64(
                database, keypoints.get(), 3,
                features.keypoint_columns);
            bind_blob(
                database, keypoints.get(), 4,
                features.keypoints.data(),
                features.keypoints.size() * sizeof(float));
            keypoints.done();
        }
        if (features.has_descriptors) {
            bind_int64(
                database, descriptors.get(), 1,
                features.image_id);
            bind_int64(
                database, descriptors.get(), 2,
                features.extractor_type);
            bind_int64(
                database, descriptors.get(), 3,
                features.rows);
            bind_int64(
                database, descriptors.get(), 4,
                features.descriptor_columns);
            bind_blob(
                database, descriptors.get(), 5,
                features.descriptors.data(),
                features.descriptors.size());
            descriptors.done();
        }
    }

    if (value.match_graph.has_scores)
        throw std::invalid_argument(
            "COLMAP database writer: match scores "
            "are not representable");
    Statement matches(
        database,
        "INSERT INTO matches("
        "pair_id,rows,cols,data"
        ") VALUES(?1,?2,2,?3)");
    Statement geometries(
        database,
        "INSERT INTO two_view_geometries("
        "pair_id,rows,cols,data,config,F,E,H,qvec,tvec"
        ") VALUES(?1,?2,2,?3,?4,?5,?6,?7,?8,?9)");
    const MatchGraph &graph = value.match_graph;
    for (size_t pair = 0; pair < graph.pair_count; ++pair) {
        if (graph.match_present[pair]) {
            const size_t begin =
                static_cast<size_t>(graph.match_offsets[pair]);
            const size_t end =
                static_cast<size_t>(
                    graph.match_offsets[pair + 1]);
            bind_int64(
                database, matches.get(), 1,
                graph.pair_ids[pair]);
            bind_int64(
                database, matches.get(), 2, end - begin);
            bind_blob(
                database, matches.get(), 3,
                begin == end
                    ? nullptr
                    : graph.matches.data() + begin * 2,
                (end - begin) * 2 * sizeof(uint32_t));
            matches.done();
        }
        if (graph.geometry_present[pair]) {
            const size_t begin =
                static_cast<size_t>(
                    graph.verified_offsets[pair]);
            const size_t end =
                static_cast<size_t>(
                    graph.verified_offsets[pair + 1]);
            bind_int64(
                database, geometries.get(), 1,
                graph.pair_ids[pair]);
            bind_int64(
                database, geometries.get(), 2, end - begin);
            bind_blob(
                database, geometries.get(), 3,
                begin == end
                    ? nullptr
                    : graph.verified_matches.data() + begin * 2,
                (end - begin) * 2 * sizeof(uint32_t));
            bind_int64(
                database, geometries.get(), 4,
                graph.configs[pair]);
            bind_optional_blob(
                database, geometries.get(), 5,
                graph.F_present[pair],
                graph.F.data() + pair * 9,
                9 * sizeof(double));
            bind_optional_blob(
                database, geometries.get(), 6,
                graph.E_present[pair],
                graph.E.data() + pair * 9,
                9 * sizeof(double));
            bind_optional_blob(
                database, geometries.get(), 7,
                graph.H_present[pair],
                graph.H.data() + pair * 9,
                9 * sizeof(double));
            bind_optional_blob(
                database, geometries.get(), 8,
                graph.pose_present[pair],
                graph.qvecs.data() + pair * 4,
                4 * sizeof(double));
            bind_optional_blob(
                database, geometries.get(), 9,
                graph.pose_present[pair],
                graph.tvecs.data() + pair * 3,
                3 * sizeof(double));
            geometries.done();
        }
    }
}

void validate_colmap_encodable(const ColmapDatabase &value) {
    for (const FeatureSet &features : value.features) {
        if (features.has_scores)
            throw std::invalid_argument(
                "COLMAP database writer: feature scores "
                "are not representable");
        if (features.has_descriptors &&
            features.descriptor_dtype != sio::DType::U8)
            throw std::invalid_argument(
                "COLMAP database writer: descriptors "
                "must be uint8");
    }
    if (value.match_graph.has_scores)
        throw std::invalid_argument(
            "COLMAP database writer: match scores "
            "are not representable");
}

void write_database(
    const ColmapDatabase &value, const std::string &path,
    size_t test_fail_after) {
    require_little_endian();
    validate_colmap_database(value, "COLMAP database writer");
    validate_colmap_encodable(value);
    std::error_code filesystem_error;
    const std::filesystem::path filesystem_path =
        std::filesystem::u8path(path);
    const bool existed =
        std::filesystem::exists(
            filesystem_path, filesystem_error);
    if (filesystem_error)
        throw std::runtime_error(
            "COLMAP database: cannot inspect destination path: " +
            filesystem_error.message());
    bool created = false;
    try {
        Database connection(
            path, SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE |
                      (existed ? 0 : SQLITE_OPEN_EXCLUSIVE));
        created = !existed;
        sqlite3 *database = connection.get();
        reject_unknown_tables(database);
        execute(database, "PRAGMA foreign_keys=OFF");
        Transaction transaction(database);
        create_schema(database);
        if (test_fail_after == 1)
            throw std::runtime_error(
                "COLMAP database: injected failure after schema");
        write_rows(database, value);
        if (test_fail_after == 2)
            throw std::runtime_error(
                "COLMAP database: injected failure after rows");
        execute(
            database,
            "PRAGMA user_version=" +
                std::to_string(value.user_version));
        transaction.commit();
    } catch (...) {
        if (created) {
            std::error_code ignored;
            std::filesystem::remove(
                filesystem_path, ignored);
        }
        throw;
    }
}

struct DatabaseInspection {
    int32_t user_version = 0;
    int64_t cameras = 0;
    int64_t images = 0;
    int64_t keypoint_rows = 0;
    int64_t descriptor_rows = 0;
    int64_t match_pairs = 0;
    int64_t verified_pairs = 0;
    int64_t raw_matches = 0;
    int64_t verified_matches = 0;
    std::vector<int64_t> descriptor_dimensions;
    std::vector<uint32_t> image_ids;
    std::vector<std::string> image_names;
    std::vector<int64_t> keypoint_counts;
    std::vector<int64_t> keypoint_dimensions;
    std::vector<int64_t> descriptor_counts;
    std::vector<int64_t> image_descriptor_dimensions;
};

int64_t sum_column(
    sqlite3 *database, const std::string &table,
    const std::string &column) {
    Statement statement(
        database,
        "SELECT coalesce(sum(\"" + column +
            "\"),0) FROM \"" + table + "\"");
    if (!statement.row())
        throw std::runtime_error(
            "COLMAP database: aggregate query returned no row");
    return integer(statement.get(), 0, "aggregate count");
}

DatabaseInspection inspect_database(const std::string &path) {
    Database connection(
        path, SQLITE_OPEN_READONLY);
    sqlite3 *database = connection.get();
    execute(database, "PRAGMA query_only=ON");
    validate_schema(database);
    DatabaseInspection result;
    result.user_version = user_version(database);
    result.cameras = scalar_count(database, "cameras");
    result.images = scalar_count(database, "images");
    result.keypoint_rows = scalar_count(database, "keypoints");
    result.descriptor_rows =
        scalar_count(database, "descriptors");
    result.match_pairs = scalar_count(database, "matches");
    result.verified_pairs =
        scalar_count(database, "two_view_geometries");
    result.raw_matches =
        sum_column(database, "matches", "rows");
    result.verified_matches = sum_column(
        database, "two_view_geometries", "rows");
    {
        Statement dimensions(
            database,
            "SELECT DISTINCT cols FROM descriptors "
            "ORDER BY cols");
        while (dimensions.row())
            result.descriptor_dimensions.push_back(
                integer(
                    dimensions.get(), 0,
                    "descriptor dimension"));
    }
    {
        Statement images(
            database,
            "SELECT i.image_id,i.name,"
            "coalesce(k.rows,-1),coalesce(k.cols,-1),"
            "coalesce(d.rows,-1),coalesce(d.cols,-1) "
            "FROM images i "
            "LEFT JOIN keypoints k ON k.image_id=i.image_id "
            "LEFT JOIN descriptors d ON d.image_id=i.image_id "
            "ORDER BY i.image_id");
        while (images.row()) {
            result.image_ids.push_back(
                image_id_value(
                    images.get(), 0, "image_id"));
            result.image_names.push_back(
                text(images.get(), 1, "image name"));
            result.keypoint_counts.push_back(
                integer(images.get(), 2, "keypoint count"));
            result.keypoint_dimensions.push_back(
                integer(images.get(), 3, "keypoint dimension"));
            result.descriptor_counts.push_back(
                integer(images.get(), 4, "descriptor count"));
            result.image_descriptor_dimensions.push_back(
                integer(images.get(), 5, "descriptor dimension"));
        }
    }
    return result;
}

nb::dict inspection_dict(const std::string &path) {
    DatabaseInspection value;
    {
        nb::gil_scoped_release release;
        value = inspect_database(path);
    }
    nb::dict result;
    result["user_version"] = value.user_version;
    result["num_cameras"] = value.cameras;
    result["num_images"] = value.images;
    result["num_keypoint_rows"] = value.keypoint_rows;
    result["num_descriptor_rows"] = value.descriptor_rows;
    result["num_match_pairs"] = value.match_pairs;
    result["num_verified_pairs"] = value.verified_pairs;
    result["num_matches"] = value.raw_matches;
    result["num_verified_matches"] = value.verified_matches;
    result["descriptor_dimensions"] =
        nb::cast(value.descriptor_dimensions);
    result["image_ids"] = nb::cast(value.image_ids);
    result["image_names"] = nb::cast(value.image_names);
    result["keypoint_counts"] =
        nb::cast(value.keypoint_counts);
    result["keypoint_dimensions"] =
        nb::cast(value.keypoint_dimensions);
    result["descriptor_counts"] =
        nb::cast(value.descriptor_counts);
    result["image_descriptor_dimensions"] =
        nb::cast(value.image_descriptor_dimensions);
    result["sqlite_version"] =
        std::string(sqlite3_libversion());
    return result;
}

}  // namespace

void register_colmap_db(nb::module_ &module) {
    module.def(
        "read_colmap_db",
        [](const std::string &path) {
            nb::gil_scoped_release release;
            return read_database(path);
        },
        "path"_a,
        "Read a COLMAP SQLite database through a read-only "
        "native connection.");
    module.def(
        "read_colmap_db_image",
        [](const std::string &path, uint32_t image_id) {
            nb::gil_scoped_release release;
            return read_feature(path, image_id);
        },
        "path"_a, "image_id"_a);
    module.def(
        "read_colmap_db_pair",
        [](const std::string &path, uint32_t image_id1,
           uint32_t image_id2) {
            nb::gil_scoped_release release;
            return read_pair(path, image_id1, image_id2);
        },
        "path"_a, "image_id1"_a, "image_id2"_a);
    module.def(
        "write_colmap_db",
        [](const ColmapDatabase &value,
           const std::string &path, size_t test_fail_after) {
            nb::gil_scoped_release release;
            write_database(value, path, test_fail_after);
        },
        "database"_a, "path"_a,
        "_test_fail_after"_a = 0,
        "Write a COLMAP SQLite database transactionally.");
    module.def(
        "inspect_colmap_db", &inspection_dict,
        "path"_a,
        "Inspect COLMAP database row counts and metadata "
        "without reading BLOB payloads.");
}
