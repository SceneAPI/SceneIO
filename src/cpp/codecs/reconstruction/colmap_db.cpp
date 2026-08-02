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
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <iomanip>
#include <limits>
#include <locale>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#include "codecs/reconstruction/colmap_db_profiles.hpp"
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

double number_value(
    sqlite3_stmt *statement, int column,
    const char *name) {
    const int type = sqlite3_column_type(statement, column);
    if (type != SQLITE_FLOAT && type != SQLITE_INTEGER)
        throw std::invalid_argument(
            std::string("COLMAP database: ") + name +
            " must be REAL");
    return sqlite3_column_double(statement, column);
}

double real_value(
    sqlite3_stmt *statement, int column,
    const char *name) {
    const double value =
        number_value(statement, column, name);
    if (!std::isfinite(value))
        throw std::invalid_argument(
            std::string("COLMAP database: ") + name +
            " must be finite");
    return value;
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

uint32_t uint32_value(
    sqlite3_stmt *statement, int column,
    const char *name) {
    const int64_t value = integer(statement, column, name);
    if (value < 0 ||
        static_cast<uint64_t>(value) >
            std::numeric_limits<uint32_t>::max())
        throw std::invalid_argument(
            std::string("COLMAP database: ") + name +
            " is outside uint32");
    return static_cast<uint32_t>(value);
}

uint64_t nonnegative_int64_value(
    sqlite3_stmt *statement, int column,
    const char *name) {
    const int64_t value = integer(statement, column, name);
    if (value < 0)
        throw std::invalid_argument(
            std::string("COLMAP database: ") + name +
            " must be non-negative");
    return static_cast<uint64_t>(value);
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

template <typename T>
bool optional_strict_fixed_blob(
    sqlite3_stmt *statement, int column, T *target,
    size_t count, const char *name) {
    if (sqlite3_column_type(statement, column) == SQLITE_NULL)
        return false;
    const size_t bytes =
        checked_blob_extent(1, count, sizeof(T), name);
    const uint8_t *data =
        checked_blob(statement, column, bytes, name);
    if (bytes != 0) std::memcpy(target, data, bytes);
    return true;
}

uint32_t read_u32_le(const uint8_t *data) {
    return static_cast<uint32_t>(data[0]) |
           (static_cast<uint32_t>(data[1]) << 8) |
           (static_cast<uint32_t>(data[2]) << 16) |
           (static_cast<uint32_t>(data[3]) << 24);
}

uint64_t read_u64_le(const uint8_t *data) {
    uint64_t value = 0;
    for (size_t index = 0; index < 8; ++index)
        value |=
            static_cast<uint64_t>(data[index]) << (index * 8);
    return value;
}

bool optional_recovered_camera(
    sqlite3_stmt *statement, int column, Camera &camera,
    uint8_t &prior_focal_length, const char *name) {
    const int type = sqlite3_column_type(statement, column);
    if (type == SQLITE_NULL) return false;
    if (type != SQLITE_BLOB)
        throw std::invalid_argument(
            std::string("COLMAP database: ") + name +
            " must be BLOB or NULL");
    const int sqlite_bytes =
        sqlite3_column_bytes(statement, column);
    if (sqlite_bytes < 0)
        throw std::invalid_argument(
            std::string("COLMAP database: invalid ") + name +
            " byte count");
    const size_t bytes =
        static_cast<size_t>(sqlite_bytes);
    constexpr size_t header_bytes = 33;
    if (bytes < header_bytes)
        throw std::invalid_argument(
            std::string("COLMAP database: truncated ") + name +
            " blob");
    const auto *data = static_cast<const uint8_t *>(
        sqlite3_column_blob(statement, column));
    if (!data)
        throw std::invalid_argument(
            std::string("COLMAP database: invalid ") + name);

    camera.id = read_u32_le(data);
    const uint32_t raw_model = read_u32_le(data + 4);
    if (raw_model >
        static_cast<uint32_t>(
            std::numeric_limits<int32_t>::max()))
        throw std::invalid_argument(
            std::string("COLMAP database: ") + name +
            " camera model is outside int32");
    camera.model_id = static_cast<int32_t>(raw_model);
    camera.width = read_u64_le(data + 8);
    camera.height = read_u64_le(data + 16);
    prior_focal_length = data[24];
    if (prior_focal_length > 1)
        throw std::invalid_argument(
            std::string("COLMAP database: ") + name +
            " prior_focal_length must be 0 or 1");
    const uint64_t count64 = read_u64_le(data + 25);
    if (count64 >
        (static_cast<uint64_t>(
             std::numeric_limits<size_t>::max()) -
         header_bytes) /
            sizeof(double))
        throw std::invalid_argument(
            std::string("COLMAP database: ") + name +
            " parameter count overflows size_t");
    const size_t count = static_cast<size_t>(count64);
    const size_t expected =
        header_bytes + count * sizeof(double);
    if (expected > static_cast<size_t>(kMaxBlobBytes))
        throw std::invalid_argument(
            std::string("COLMAP database: ") + name +
            " exceeds the 1,000,000,000-byte bound");
    if (bytes < expected)
        throw std::invalid_argument(
            std::string("COLMAP database: truncated ") + name +
            " parameter payload");
    if (bytes > expected)
        throw std::invalid_argument(
            std::string("COLMAP database: ") + name +
            " blob has trailing bytes");
    const auto model = colmap_model_info(camera.model_id);
    if (count != static_cast<size_t>(model.nparams))
        throw std::invalid_argument(
            std::string("COLMAP database: ") + name +
            " parameter count disagrees with model");
    camera.params.resize(count);
    for (size_t index = 0; index < count; ++index) {
        const uint64_t bits =
            read_u64_le(data + header_bytes + index * 8);
        std::memcpy(
            &camera.params[index], &bits, sizeof(double));
    }
    return true;
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

int32_t pragma_int(sqlite3 *database, const char *name) {
    Statement statement(database, std::string("PRAGMA ") + name);
    if (!statement.row())
        throw std::runtime_error(
            std::string("COLMAP database: PRAGMA ") + name +
            " returned no row");
    return int32_value(statement.get(), 0, name);
}

std::string normalize_schema_sql(const unsigned char *source) {
    if (!source) return {};
    std::string result;
    bool quoted = false;
    char quote = '\0';
    for (const unsigned char *cursor = source; *cursor; ++cursor) {
        char value = static_cast<char>(*cursor);
        if (quoted) {
            result.push_back(value);
            if (value == quote) {
                if (cursor[1] == static_cast<unsigned char>(quote)) {
                    result.push_back(static_cast<char>(cursor[1]));
                    ++cursor;
                } else {
                    quoted = false;
                }
            }
            continue;
        }
        if (value == '\'' || value == '"' || value == '`') {
            quoted = true;
            quote = value;
            result.push_back(value);
        } else {
            const bool ascii_space =
                value == ' ' || value == '\t' || value == '\n' ||
                value == '\r' || value == '\f' || value == '\v';
            if (!ascii_space)
                result.push_back(
                    value >= 'A' && value <= 'Z'
                        ? static_cast<char>(value - 'A' + 'a')
                        : value);
        }
    }
    return result;
}

void append_schema_value(
    std::ostringstream &output, sqlite3_stmt *statement, int column) {
    const int kind = sqlite3_column_type(statement, column);
    output << kind << ':';
    switch (kind) {
        case SQLITE_NULL:
            output << '-';
            break;
        case SQLITE_INTEGER:
            output << sqlite3_column_int64(statement, column);
            break;
        case SQLITE_FLOAT:
            output << std::setprecision(17)
                   << sqlite3_column_double(statement, column);
            break;
        case SQLITE_TEXT:
        case SQLITE_BLOB: {
            const int bytes = sqlite3_column_bytes(statement, column);
            const auto *data = static_cast<const unsigned char *>(
                kind == SQLITE_TEXT
                    ? static_cast<const void *>(
                          sqlite3_column_text(statement, column))
                    : sqlite3_column_blob(statement, column));
            output << bytes << ':';
            if (bytes > 0 && data)
                output.write(
                    reinterpret_cast<const char *>(data), bytes);
            break;
        }
        default:
            throw std::runtime_error(
                "COLMAP database: unexpected SQLite value kind");
    }
    output << '|';
}

std::vector<std::string> schema_rows(
    sqlite3 *database, const std::string &sql,
    int name_column = -1,
    std::vector<std::string> *names = nullptr) {
    Statement statement(database, sql);
    const int columns = sqlite3_column_count(statement.get());
    std::vector<std::string> rows;
    while (statement.row()) {
        std::ostringstream row;
        row.imbue(std::locale::classic());
        for (int column = 0; column < columns; ++column)
            append_schema_value(row, statement.get(), column);
        rows.push_back(row.str());
        if (names && name_column >= 0)
            names->push_back(
                text(statement.get(), name_column, "schema name"));
    }
    std::sort(rows.begin(), rows.end());
    if (names) std::sort(names->begin(), names->end());
    return rows;
}

void append_schema_rows(
    std::ostringstream &output, std::vector<std::string> rows) {
    for (const std::string &row : rows)
        output << row << '\n';
}

std::string canonical_schema(sqlite3 *database) {
    // sqlite_schema SQL captures CHECK constraints and expression/partial
    // indexes. The PRAGMA rows additionally freeze column affinity,
    // nullability, defaults, PK order, foreign keys, and index layout.
    std::ostringstream output;
    output.imbue(std::locale::classic());
    Statement masters(
        database,
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' "
        "ORDER BY type,name");
    std::vector<std::string> tables;
    while (masters.row()) {
        const std::string type =
            text(masters.get(), 0, "schema object type");
        const std::string name =
            text(masters.get(), 1, "schema object name");
        output << "object|";
        append_schema_value(output, masters.get(), 0);
        append_schema_value(output, masters.get(), 1);
        append_schema_value(output, masters.get(), 2);
        output << normalize_schema_sql(
            sqlite3_column_text(masters.get(), 3)) << '\n';
        if (type == "table") tables.push_back(name);
    }
    for (const std::string &table : tables) {
        if (table.find('"') != std::string::npos)
            throw std::invalid_argument(
                "COLMAP database: table names containing quotes "
                "are not supported");
        for (const char *pragma :
             {"table_xinfo", "foreign_key_list"}) {
            output << pragma << '|' << table << '\n';
            append_schema_rows(
                output,
                schema_rows(
                    database, std::string("PRAGMA ") + pragma +
                                  "(\"" + table + "\")"));
        }
        output << "index_list|" << table << '\n';
        std::vector<std::string> indexes;
        append_schema_rows(
            output,
            schema_rows(
                database,
                "PRAGMA index_list(\"" + table + "\")",
                1, &indexes));
        for (const std::string &index : indexes) {
            if (index.find('"') != std::string::npos)
                throw std::invalid_argument(
                    "COLMAP database: index names containing quotes "
                    "are not supported");
            output << "index_xinfo|" << index << '\n';
            append_schema_rows(
                output,
                schema_rows(
                    database,
                    "PRAGMA index_xinfo(\"" + index + "\")"));
        }
    }
    return output.str();
}

struct ProfileIdentity {
    std::string name = "unknown";
    std::string source_revision;
    int32_t application_id = 0;
    int32_t user_version = 0;
    std::string schema;
};

bool valid_maxx_schema_row(sqlite3 *database) {
    if (!table_exists(database, "maxx_schema_info"))
        return false;
    Statement row(
        database,
        "SELECT schema_version,minimum_reader_version,"
        "producer_version,producer_commit "
        "FROM maxx_schema_info");
    if (!row.row()) return false;
    const int64_t schema_version =
        integer(row.get(), 0, "MAXX schema_version");
    const int64_t minimum_reader_version =
        integer(row.get(), 1, "MAXX minimum_reader_version");
    const std::string producer_version =
        text(row.get(), 2, "MAXX producer_version");
    const std::string producer_commit =
        text(row.get(), 3, "MAXX producer_commit");
    if (row.row()) return false;
    return schema_version == 1 && minimum_reader_version == 1 &&
           !producer_version.empty() && !producer_commit.empty();
}

void create_schema(sqlite3 *database);

const std::vector<std::string> &expected_profile_schemas() {
    static const std::vector<std::string> expected = [] {
        std::vector<std::string> result;
        result.reserve(colmap_db_profile_specs().size());
        for (const ColmapDbProfileSpec &profile :
             colmap_db_profile_specs()) {
            Database database(
                ":memory:",
                SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE);
            execute(database.get(), profile.schema_sql);
            result.push_back(canonical_schema(database.get()));
        }
        return result;
    }();
    return expected;
}

const std::string &expected_legacy_hybrid_schema() {
    static const std::string expected = [] {
        Database database(
            ":memory:",
            SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE);
        create_schema(database.get());
        return canonical_schema(database.get());
    }();
    return expected;
}

ProfileIdentity identify_profile(sqlite3 *database) {
    ProfileIdentity result;
    result.application_id =
        pragma_int(database, "application_id");
    result.user_version = pragma_int(database, "user_version");
    result.schema = canonical_schema(database);
    const auto &profiles = colmap_db_profile_specs();
    const auto &expected = expected_profile_schemas();
    for (size_t index = 0; index < profiles.size(); ++index) {
        const ColmapDbProfileSpec &profile = profiles[index];
        if (result.application_id != profile.application_id ||
            result.user_version != profile.user_version ||
            result.schema != expected[index])
            continue;
        if (profile.requires_maxx_schema_row &&
            !valid_maxx_schema_row(database))
            continue;
        result.name = profile.name;
        result.source_revision = profile.source_revision;
        break;
    }
    if (result.name == "unknown" &&
        result.application_id == 0 &&
        result.schema == expected_legacy_hybrid_schema()) {
        result.name = "sceneio-hybrid-v1";
        result.source_revision = "sceneio-owned";
    }
    return result;
}

std::string schema_signature(const std::string &schema) {
    // A compact deterministic diagnostic only. Exact profile selection above
    // always compares the complete canonical schema string.
    uint64_t value = 1469598103934665603ULL;
    for (unsigned char byte : schema) {
        value ^= byte;
        value *= 1099511628211ULL;
    }
    std::ostringstream output;
    output.imbue(std::locale::classic());
    output << std::hex << std::setfill('0') << std::setw(16) << value;
    return output.str();
}

void require_core_tables(sqlite3 *database) {
    static constexpr const char *required[] = {
        "cameras", "images", "keypoints", "descriptors",
        "matches", "two_view_geometries"};
    for (const char *name : required)
        if (!table_exists(database, name))
            throw std::invalid_argument(
                std::string("COLMAP database: missing required table '") +
                name + "'");
}

void validate_schema(sqlite3 *database) {
    require_core_tables(database);
    const std::array<const char *, 4> rig_frame_tables = {
        "rigs", "rig_sensors", "frames", "frame_data"};
    const size_t rig_frame_table_count =
        static_cast<size_t>(std::count_if(
            rig_frame_tables.begin(), rig_frame_tables.end(),
            [database](const char *name) {
                return table_exists(database, name);
            }));
    if (rig_frame_table_count != 0 &&
        rig_frame_table_count != rig_frame_tables.size())
        throw std::invalid_argument(
            "COLMAP database: rigs, rig_sensors, frames, and "
            "frame_data must be present together");
    const std::map<std::string, std::vector<std::string>> represented = {
        {"rigs", {"rig_id", "ref_sensor_id", "ref_sensor_type"}},
        {"rig_sensors",
         {"rig_id", "sensor_id", "sensor_type", "sensor_from_rig"}},
        {"cameras",
         {"camera_id", "model", "width", "height", "params",
          "prior_focal_length"}},
        {"frames", {"frame_id", "rig_id"}},
        {"frame_data",
         {"frame_id", "data_id", "sensor_id", "sensor_type"}},
        {"images", {"image_id", "name", "camera_id", "time_id"}},
        {"maxx_schema_info",
         {"schema_version", "minimum_reader_version",
          "producer_version", "producer_commit"}},
        {"pose_priors",
         {"image_id", "pose_prior_id", "corr_data_id",
          "corr_sensor_id", "corr_sensor_type", "position",
          "position_covariance", "gravity", "coordinate_system",
          "rotation", "rotation_covariance", "pose_covariance"}},
        {"keypoints", {"image_id", "rows", "cols", "data"}},
        {"keypoint_colors", {"image_id", "rows", "cols", "data"}},
        {"descriptors",
         {"image_id", "type", "type_name", "dtype", "dim",
          "rows", "cols", "data"}},
        {"matches", {"pair_id", "rows", "cols", "data"}},
        {"match_scores", {"pair_id", "rows", "cols", "data"}},
        {"pair_provenance",
         {"pair_id", "source_flags", "retrieval_score"}},
        {"image_qualities", {"image_id", "quality"}},
        {"markers",
         {"marker_id", "label", "type", "world_position",
          "world_position_cov", "point3D_id", "enabled"}},
        {"marker_projections",
         {"marker_id", "image_id", "x", "y", "size", "pinned",
          "point2D_idx"}},
        {"videos",
         {"video_id", "name", "source_path", "content_hash",
          "width", "height", "num_frames", "fps",
          "duration_seconds", "codec_name", "sync_group"}},
        {"video_frames",
         {"video_id", "image_id", "frame_id", "pts_seconds",
          "time_id"}},
        {"two_view_geometries",
         {"pair_id", "rows", "cols", "data", "config", "F", "E",
          "H", "qvec", "tvec", "camera1", "camera2"}},
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
    if (table_exists(database, "pose_priors")) {
        const std::vector<std::string> columns =
            table_columns(database, "pose_priors");
        static const std::vector<std::vector<std::string>>
            exact_layouts = {
                {"image_id", "position", "coordinate_system",
                 "position_covariance"},
                {"pose_prior_id", "corr_data_id", "corr_sensor_id",
                 "corr_sensor_type", "position",
                 "position_covariance", "gravity",
                 "coordinate_system"},
                {"pose_prior_id", "corr_data_id", "corr_sensor_id",
                 "corr_sensor_type", "position",
                 "position_covariance", "gravity",
                 "coordinate_system", "rotation",
                 "rotation_covariance", "pose_covariance"},
            };
        if (std::none_of(
                exact_layouts.begin(), exact_layouts.end(),
                [&columns](const auto &layout) {
                    return columns == layout;
                }))
            throw std::invalid_argument(
                "COLMAP database: pose_priors has an unsupported "
                "or incomplete column layout");
    }
    if (table_exists(database, "descriptors")) {
        const std::vector<std::string> columns =
            table_columns(database, "descriptors");
        static const std::vector<std::vector<std::string>>
            exact_layouts = {
                {"image_id", "rows", "cols", "data"},
                {"image_id", "type", "rows", "cols", "data"},
                {"image_id", "type", "type_name", "dtype", "dim",
                 "rows", "cols", "data"},
            };
        if (std::none_of(
                exact_layouts.begin(), exact_layouts.end(),
                [&columns](const auto &layout) {
                    return columns == layout;
                }))
            throw std::invalid_argument(
                "COLMAP database: descriptors has an unsupported "
                "or incomplete column layout");
    }
    const auto require_table_pair =
        [database](const char *first, const char *second) {
            if (table_exists(database, first) !=
                table_exists(database, second))
                throw std::invalid_argument(
                    std::string("COLMAP database: ") + first +
                    " and " + second +
                    " must be present together");
        };
    require_table_pair("markers", "marker_projections");
    require_table_pair("videos", "video_frames");
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
        "pair_provenance",
        "markers",
        "marker_projections",
        "keypoint_colors",
        "match_scores",
        "maxx_schema_info",
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
    struct IndexSpec {
        const char *table;
        bool unique;
        std::vector<std::string> columns;
    };
    static const std::unordered_map<std::string, IndexSpec> known_indexes = {
        {"rig_ref_sensor_assignment",
         {"rigs", true, {"ref_sensor_id", "ref_sensor_type"}}},
        {"rig_sensor_assignment",
         {"rig_sensors", true, {"sensor_id", "sensor_type"}}},
        {"frame_sensor_assignment",
         {"frame_data", true, {"data_id", "sensor_type"}}},
        {"index_name", {"images", true, {"name"}}},
        {"pose_prior_data_assignment",
         {"pose_priors",
          true,
          {"corr_data_id", "corr_sensor_id", "corr_sensor_type"}}},
        {"index_video_name", {"videos", true, {"name"}}},
        {"index_video_frame_image",
         {"video_frames", false, {"image_id"}}},
        {"index_marker_label", {"markers", true, {"label"}}},
        {"index_marker_projection_image",
         {"marker_projections", false, {"image_id"}}},
    };
    Statement objects(
        database,
        "SELECT type,name,tbl_name FROM sqlite_master "
        "WHERE type IN ('index','view','trigger') "
        "AND name NOT LIKE 'sqlite_%' "
        "ORDER BY type,name");
    while (objects.row()) {
        const std::string type =
            text(objects.get(), 0, "schema object type");
        const std::string name =
            text(objects.get(), 1, "schema object name");
        const std::string table =
            text(objects.get(), 2, "schema object table");
        const auto expected = known_indexes.find(name);
        bool valid =
            type == "index" && expected != known_indexes.end() &&
            table == expected->second.table;
        bool found = false;
        if (valid) {
            Statement list(
                database,
                "PRAGMA index_list(\"" + table + "\")");
            while (list.row()) {
                if (text(list.get(), 1, "index name") != name)
                    continue;
                found = true;
                valid =
                    (integer(list.get(), 2, "index unique") != 0) ==
                        expected->second.unique &&
                    text(list.get(), 3, "index origin") == "c" &&
                    integer(list.get(), 4, "index partial") == 0;
            }
        }
        std::vector<std::string> columns;
        if (valid && found) {
            Statement info(
                database,
                "PRAGMA index_xinfo(\"" + name + "\")");
            while (info.row()) {
                if (integer(info.get(), 5, "index key") == 0)
                    continue;
                const int64_t column_id =
                    integer(info.get(), 1, "index column id");
                if (column_id < 0 ||
                    integer(info.get(), 3, "index descending") != 0 ||
                    text(info.get(), 4, "index collation") != "BINARY") {
                    valid = false;
                    break;
                }
                columns.push_back(
                    text(info.get(), 2, "index column name"));
            }
            valid =
                valid && columns == expected->second.columns;
        } else {
            valid = false;
        }
        if (!valid)
            throw std::invalid_argument(
                "COLMAP database: unsupported schema object '" +
                type + " " + name + "'");
    }
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

ColmapRigFrameSet read_rig_frames(sqlite3 *database) {
    ColmapRigFrameSet result;
    if (!table_exists(database, "rigs") ||
        !table_exists(database, "rig_sensors") ||
        !table_exists(database, "frames") ||
        !table_exists(database, "frame_data"))
        return result;

    struct RigSensorRow {
        int32_t type = 0;
        uint32_t id = 0;
        uint8_t pose_present = 0;
        std::array<double, 4> qvec{};
        std::array<double, 3> tvec{};
    };
    std::unordered_map<uint32_t, size_t> rig_indices;
    {
        Statement rigs(
            database,
            "SELECT rig_id, ref_sensor_id, ref_sensor_type "
            "FROM rigs ORDER BY rig_id");
        while (rigs.row()) {
            const uint32_t rig_id =
                uint32_value(rigs.get(), 0, "rig_id");
            if (!rig_indices.emplace(
                    rig_id, result.rig_ids.size()).second)
                throw std::invalid_argument(
                    "COLMAP database: duplicate rig_id");
            result.rig_ids.push_back(rig_id);
            result.rig_ref_sensor_ids.push_back(
                uint32_value(
                    rigs.get(), 1, "reference sensor_id"));
            result.rig_ref_sensor_types.push_back(
                int32_value(
                    rigs.get(), 2, "reference sensor_type"));
        }
    }
    std::vector<std::vector<RigSensorRow>> rig_sensors(
        result.num_rigs());
    {
        Statement sensors(
            database,
            "SELECT rig_id, sensor_id, sensor_type, sensor_from_rig "
            "FROM rig_sensors "
            "ORDER BY rig_id, sensor_type, sensor_id");
        while (sensors.row()) {
            const uint32_t rig_id =
                uint32_value(sensors.get(), 0, "rig sensor rig_id");
            const auto rig = rig_indices.find(rig_id);
            if (rig == rig_indices.end())
                throw std::invalid_argument(
                    "COLMAP database: rig_sensors references a "
                    "missing rig");
            RigSensorRow row;
            row.id = uint32_value(
                sensors.get(), 1, "rig sensor_id");
            row.type = int32_value(
                sensors.get(), 2, "rig sensor_type");
            std::array<double, 7> pose{};
            row.pose_present = static_cast<uint8_t>(
                optional_strict_fixed_blob(
                    sensors.get(), 3, pose.data(), pose.size(),
                    "sensor_from_rig"));
            if (row.pose_present) {
                std::copy_n(
                    pose.begin(), row.qvec.size(), row.qvec.begin());
                std::copy_n(
                    pose.begin() + row.qvec.size(),
                    row.tvec.size(), row.tvec.begin());
            }
            rig_sensors[rig->second].push_back(std::move(row));
        }
    }
    result.rig_sensor_offsets.clear();
    result.rig_sensor_offsets.push_back(0);
    for (const auto &rows : rig_sensors) {
        for (const RigSensorRow &row : rows) {
            result.rig_sensor_types.push_back(row.type);
            result.rig_sensor_ids.push_back(row.id);
            result.rig_sensor_pose_present.push_back(
                row.pose_present);
            result.rig_sensor_qvecs.insert(
                result.rig_sensor_qvecs.end(),
                row.qvec.begin(), row.qvec.end());
            result.rig_sensor_tvecs.insert(
                result.rig_sensor_tvecs.end(),
                row.tvec.begin(), row.tvec.end());
        }
        result.rig_sensor_offsets.push_back(
            result.num_rig_sensors());
    }

    struct FrameDataRow {
        uint64_t data_id = 0;
        int32_t sensor_type = 0;
        uint32_t sensor_id = 0;
    };
    std::unordered_map<uint32_t, size_t> frame_indices;
    {
        Statement frames(
            database,
            "SELECT frame_id, rig_id FROM frames ORDER BY frame_id");
        while (frames.row()) {
            const uint32_t frame_id =
                uint32_value(frames.get(), 0, "frame_id");
            if (!frame_indices.emplace(
                    frame_id, result.frame_ids.size()).second)
                throw std::invalid_argument(
                    "COLMAP database: duplicate frame_id");
            result.frame_ids.push_back(frame_id);
            result.frame_rig_ids.push_back(
                uint32_value(frames.get(), 1, "frame rig_id"));
        }
    }
    std::vector<std::vector<FrameDataRow>> frame_data(
        result.num_frames());
    {
        Statement rows(
            database,
            "SELECT frame_id, data_id, sensor_id, sensor_type "
            "FROM frame_data "
            "ORDER BY frame_id, sensor_type, sensor_id, data_id");
        while (rows.row()) {
            const uint32_t frame_id =
                uint32_value(rows.get(), 0, "frame data frame_id");
            const auto frame = frame_indices.find(frame_id);
            if (frame == frame_indices.end())
                throw std::invalid_argument(
                    "COLMAP database: frame_data references a "
                    "missing frame");
            frame_data[frame->second].push_back(FrameDataRow{
                nonnegative_int64_value(
                    rows.get(), 1, "frame data_id"),
                int32_value(rows.get(), 3, "frame sensor_type"),
                uint32_value(rows.get(), 2, "frame sensor_id")});
        }
    }
    result.frame_data_offsets.clear();
    result.frame_data_offsets.push_back(0);
    for (const auto &rows : frame_data) {
        for (const FrameDataRow &row : rows) {
            result.frame_data_ids.push_back(row.data_id);
            result.frame_sensor_types.push_back(row.sensor_type);
            result.frame_sensor_ids.push_back(row.sensor_id);
        }
        result.frame_data_offsets.push_back(
            result.num_frame_data());
    }
    return result;
}

ColmapPosePriorSet read_pose_priors(
    sqlite3 *database,
    const std::vector<FeatureSet> &features) {
    ColmapPosePriorSet result;
    if (!table_exists(database, "pose_priors"))
        return result;
    const bool generalized =
        column_exists(database, "pose_priors", "pose_prior_id");
    result.generalized = generalized;
    const bool extended =
        column_exists(database, "pose_priors", "rotation");

    std::unordered_map<uint32_t, uint32_t> image_cameras;
    image_cameras.reserve(features.size());
    for (const FeatureSet &feature : features)
        image_cameras.emplace(feature.image_id, feature.camera_id);

    auto append_optional_vector =
        [](sqlite3_stmt *statement, int column,
           std::vector<uint8_t> &presence,
           std::vector<double> &values,
           const char *name) {
            std::array<double, 3> item{};
            const bool present = optional_strict_fixed_blob(
                statement, column, item.data(), item.size(), name);
            presence.push_back(static_cast<uint8_t>(present));
            values.insert(values.end(), item.begin(), item.end());
        };
    auto append_optional_matrix =
        [](sqlite3_stmt *statement, int column, size_t dimension,
           std::vector<uint8_t> &presence,
           std::vector<double> &values,
           const char *name) {
            std::vector<double> column_major(
                dimension * dimension, 0.0);
            const bool present = optional_strict_fixed_blob(
                statement, column, column_major.data(),
                column_major.size(), name);
            presence.push_back(static_cast<uint8_t>(present));
            for (size_t row = 0; row < dimension; ++row)
                for (size_t column = 0;
                     column < dimension; ++column)
                    values.push_back(
                        column_major[
                            column * dimension + row]);
        };

    if (generalized) {
        Statement priors(
            database,
            "SELECT pose_prior_id, corr_data_id, corr_sensor_id, "
            "corr_sensor_type, position, position_covariance, "
            "gravity, coordinate_system, " +
                std::string(
                    extended
                        ? "rotation, rotation_covariance, "
                          "pose_covariance "
                        : "NULL, NULL, NULL ") +
            "FROM pose_priors ORDER BY pose_prior_id");
        while (priors.row()) {
            result.prior_ids.push_back(
                uint32_value(
                    priors.get(), 0, "pose prior_id"));
            result.corr_data_ids.push_back(
                nonnegative_int64_value(
                    priors.get(), 1,
                    "pose prior correlated data_id"));
            result.corr_sensor_ids.push_back(
                uint32_value(
                    priors.get(), 2,
                    "pose prior correlated sensor_id"));
            result.corr_sensor_types.push_back(
                int32_value(
                    priors.get(), 3,
                    "pose prior correlated sensor_type"));
            append_optional_vector(
                priors.get(), 4, result.position_present,
                result.positions, "pose prior position");
            append_optional_matrix(
                priors.get(), 5, 3,
                result.position_covariance_present,
                result.position_covariances,
                "pose prior position covariance");
            append_optional_vector(
                priors.get(), 6, result.gravity_present,
                result.gravities, "pose prior gravity");
            result.coordinate_systems.push_back(
                int32_value(
                    priors.get(), 7,
                    "pose prior coordinate_system"));
            std::array<double, 4> rotation{};
            const bool rotation_present =
                optional_strict_fixed_blob(
                    priors.get(), 8, rotation.data(),
                    rotation.size(), "pose prior rotation");
            result.rotation_present.push_back(
                static_cast<uint8_t>(rotation_present));
            result.rotations.insert(
                result.rotations.end(),
                rotation.begin(), rotation.end());
            append_optional_matrix(
                priors.get(), 9, 3,
                result.rotation_covariance_present,
                result.rotation_covariances,
                "pose prior rotation covariance");
            append_optional_matrix(
                priors.get(), 10, 6,
                result.pose_covariance_present,
                result.pose_covariances,
                "pose prior pose covariance");
        }
    } else {
        Statement priors(
            database,
            "SELECT image_id, position, coordinate_system, "
            "position_covariance "
            "FROM pose_priors ORDER BY image_id");
        while (priors.row()) {
            const uint32_t image_id =
                uint32_value(
                    priors.get(), 0, "pose prior image_id");
            const auto camera = image_cameras.find(image_id);
            if (camera == image_cameras.end())
                throw std::invalid_argument(
                    "COLMAP database: pose_priors references a "
                    "missing image");
            result.prior_ids.push_back(image_id);
            result.corr_data_ids.push_back(image_id);
            result.corr_sensor_ids.push_back(camera->second);
            result.corr_sensor_types.push_back(0);
            append_optional_vector(
                priors.get(), 1, result.position_present,
                result.positions, "pose prior position");
            result.coordinate_systems.push_back(
                int32_value(
                    priors.get(), 2,
                    "pose prior coordinate_system"));
            append_optional_matrix(
                priors.get(), 3, 3,
                result.position_covariance_present,
                result.position_covariances,
                "pose prior position covariance");
            result.gravity_present.push_back(0);
            result.gravities.insert(
                result.gravities.end(), 3, 0.0);
            result.rotation_present.push_back(0);
            result.rotations.insert(
                result.rotations.end(), 4, 0.0);
            result.rotation_covariance_present.push_back(0);
            result.rotation_covariances.insert(
                result.rotation_covariances.end(), 9, 0.0);
            result.pose_covariance_present.push_back(0);
            result.pose_covariances.insert(
                result.pose_covariances.end(), 36, 0.0);
        }
    }
    return result;
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
    const std::unordered_map<uint32_t, size_t> &index,
    int64_t only_image = -1) {
    Statement statement(
        database,
        only_image < 0
            ? "SELECT image_id, rows, cols, data "
              "FROM keypoints ORDER BY image_id"
            : "SELECT image_id, rows, cols, data "
              "FROM keypoints WHERE image_id=?1");
    if (only_image >= 0)
        check(
            database,
            sqlite3_bind_int64(
                statement.get(), 1, only_image),
            "binding image_id");
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

sio::DType descriptor_dtype_value(int32_t wire_dtype) {
    switch (wire_dtype) {
        case 0:
            return sio::DType::U8;
        case 1:
            return sio::DType::I8;
        case 2:
            return sio::DType::F16;
        case 3:
            return sio::DType::F32;
        case 4:
            return sio::DType::F64;
        default:
            throw std::invalid_argument(
                "COLMAP database: descriptor dtype is unknown");
    }
}

sio::DType effective_descriptor_dtype(
    int32_t extractor_type, bool dtype_present,
    int32_t wire_dtype = 0) {
    sio::DType dtype =
        dtype_present
            ? descriptor_dtype_value(wire_dtype)
            : (extractor_type == 1 || extractor_type == 2)
                  ? sio::DType::F32
                  : sio::DType::U8;
    if (dtype_present &&
        ((extractor_type == 0 && dtype != sio::DType::U8) ||
         ((extractor_type == 1 || extractor_type == 2) &&
          dtype != sio::DType::F32)))
        throw std::invalid_argument(
            "COLMAP database: descriptor dtype contradicts "
            "its built-in extractor type");
    return dtype;
}

void read_descriptors(
    sqlite3 *database, std::vector<FeatureSet> &features,
    const std::unordered_map<uint32_t, size_t> &index,
    int64_t only_image = -1) {
    const bool has_type =
        column_exists(database, "descriptors", "type");
    const bool has_metadata =
        column_exists(database, "descriptors", "dtype");
    std::string query =
        has_metadata
            ? "SELECT image_id, type, type_name, dtype, dim, "
              "rows, cols, data FROM descriptors"
            : has_type
                  ? "SELECT image_id, type, NULL, NULL, NULL, "
                    "rows, cols, data FROM descriptors"
                  : "SELECT image_id, 0, NULL, NULL, NULL, "
                    "rows, cols, data FROM descriptors";
    query += only_image < 0
                 ? " ORDER BY image_id"
                 : " WHERE image_id=?1";
    Statement statement(database, query);
    if (only_image >= 0)
        check(
            database,
            sqlite3_bind_int64(
                statement.get(), 1, only_image),
            "binding image_id");
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
        if (sqlite3_column_type(statement.get(), 2) != SQLITE_NULL) {
            value.extractor_type_name =
                text(statement.get(), 2, "descriptor type_name");
            value.extractor_type_name_present = true;
        }
        const size_t rows =
            extent(statement.get(), 5, "descriptor rows");
        const size_t stored_columns =
            extent(statement.get(), 6, "descriptor cols");
        if (rows != value.rows)
            throw std::invalid_argument(
                "COLMAP database: descriptor rows disagree "
                "with keypoint rows");
        const bool dtype_present =
            sqlite3_column_type(statement.get(), 3) != SQLITE_NULL;
        const bool dim_present =
            sqlite3_column_type(statement.get(), 4) != SQLITE_NULL;
        if (dtype_present) {
            value.descriptor_dtype_present = true;
            value.descriptor_dtype = effective_descriptor_dtype(
                value.extractor_type, true,
                int32_value(
                    statement.get(), 3, "descriptor dtype"));
        } else {
            value.descriptor_dtype = effective_descriptor_dtype(
                value.extractor_type, false);
        }
        const size_t itemsize =
            sio::dtype_info(value.descriptor_dtype).itemsize;
        if (dim_present) {
            value.descriptor_dim_present = true;
            value.descriptor_columns =
                extent(statement.get(), 4, "descriptor dim");
        } else {
            if (stored_columns % itemsize != 0)
                throw std::invalid_argument(
                    "COLMAP database: descriptor cols are not "
                    "divisible by dtype itemsize");
            value.descriptor_columns = stored_columns / itemsize;
        }
        if (value.descriptor_columns >
                std::numeric_limits<size_t>::max() / itemsize ||
            value.descriptor_columns * itemsize != stored_columns)
            throw std::invalid_argument(
                "COLMAP database: descriptor cols disagree "
                "with dtype and dim");
        value.descriptors = byte_blob(
            statement.get(), 7, rows,
            stored_columns, "descriptor data");
        value.has_descriptors = true;
    }
}

void read_keypoint_colors(
    sqlite3 *database, std::vector<FeatureSet> &features,
    const std::unordered_map<uint32_t, size_t> &index,
    int64_t only_image = -1) {
    if (!table_exists(database, "keypoint_colors"))
        return;
    Statement statement(
        database,
        only_image < 0
            ? "SELECT image_id, rows, cols, data "
              "FROM keypoint_colors ORDER BY image_id"
            : "SELECT image_id, rows, cols, data "
              "FROM keypoint_colors WHERE image_id=?1");
    if (only_image >= 0)
        check(
            database,
            sqlite3_bind_int64(
                statement.get(), 1, only_image),
            "binding image_id");
    while (statement.row()) {
        const uint32_t image_id =
            image_id_value(
                statement.get(), 0, "keypoint color image_id");
        const auto found = index.find(image_id);
        if (found == index.end())
            throw std::invalid_argument(
                "COLMAP database: keypoint_colors reference "
                "a missing image");
        FeatureSet &value = features[found->second];
        if (value.keypoint_colors_present)
            throw std::invalid_argument(
                "COLMAP database: duplicate keypoint color row");
        const size_t rows =
            extent(statement.get(), 1, "keypoint color rows");
        const size_t columns =
            extent(statement.get(), 2, "keypoint color cols");
        if (!value.keypoints_present || rows != value.rows ||
            columns != 3)
            throw std::invalid_argument(
                "COLMAP database: keypoint colors must be "
                "Nx3 and parallel to keypoints");
        value.keypoint_colors = byte_blob(
            statement.get(), 3, rows, columns,
            "keypoint color data");
        value.keypoint_colors_present = true;
    }
}

void read_image_qualities(
    sqlite3 *database, std::vector<FeatureSet> &features,
    const std::unordered_map<uint32_t, size_t> &index,
    int64_t only_image = -1) {
    if (!table_exists(database, "image_qualities"))
        return;
    Statement statement(
        database,
        only_image < 0
            ? "SELECT image_id, quality FROM image_qualities "
              "ORDER BY image_id"
            : "SELECT image_id, quality FROM image_qualities "
              "WHERE image_id=?1");
    if (only_image >= 0)
        check(
            database,
            sqlite3_bind_int64(
                statement.get(), 1, only_image),
            "binding image_id");
    while (statement.row()) {
        const uint32_t image_id =
            image_id_value(
                statement.get(), 0, "image quality image_id");
        const auto found = index.find(image_id);
        if (found == index.end())
            throw std::invalid_argument(
                "COLMAP database: image_qualities reference "
                "a missing image");
        FeatureSet &value = features[found->second];
        if (value.quality_present)
            throw std::invalid_argument(
                "COLMAP database: duplicate image quality row");
        value.quality =
            real_value(statement.get(), 1, "image quality");
        value.quality_present = true;
    }
}

ColmapMarkerSet read_markers(sqlite3 *database) {
    ColmapMarkerSet result;
    if (!table_exists(database, "markers") ||
        !table_exists(database, "marker_projections"))
        return result;
    Statement markers(
        database,
        "SELECT marker_id, label, type, world_position, "
        "world_position_cov, point3D_id, enabled "
        "FROM markers ORDER BY marker_id");
    while (markers.row()) {
        result.marker_ids.push_back(
            uint32_value(markers.get(), 0, "marker_id"));
        result.labels.push_back(
            text(markers.get(), 1, "marker label"));
        result.types.push_back(
            int32_value(markers.get(), 2, "marker type"));
        std::array<double, 3> position{};
        const bool position_present =
            optional_strict_fixed_blob(
                markers.get(), 3, position.data(),
                position.size(), "marker world_position");
        result.world_position_present.push_back(
            static_cast<uint8_t>(position_present));
        result.world_positions.insert(
            result.world_positions.end(),
            position.begin(), position.end());
        std::array<double, 9> covariance_column_major{};
        const bool covariance_present =
            optional_strict_fixed_blob(
                markers.get(), 4,
                covariance_column_major.data(),
                covariance_column_major.size(),
                "marker world_position_cov");
        result.world_covariance_present.push_back(
            static_cast<uint8_t>(covariance_present));
        for (size_t row = 0; row < 3; ++row)
            for (size_t column = 0; column < 3; ++column)
                result.world_covariances.push_back(
                    covariance_column_major[column * 3 + row]);
        const int64_t point3d =
            integer(markers.get(), 5, "marker point3D_id");
        if (point3d < -1)
            throw std::invalid_argument(
                "COLMAP database: marker point3D_id must be "
                "-1 or non-negative");
        result.point3d_ids.push_back(
            point3d == -1
                ? std::numeric_limits<uint64_t>::max()
                : static_cast<uint64_t>(point3d));
        const int64_t enabled =
            integer(markers.get(), 6, "marker enabled");
        if (enabled != 0 && enabled != 1)
            throw std::invalid_argument(
                "COLMAP database: marker enabled must be 0 or 1");
        result.enabled.push_back(static_cast<uint8_t>(enabled));
    }

    Statement projections(
        database,
        "SELECT marker_id, image_id, x, y, size, pinned, "
        "point2D_idx FROM marker_projections "
        "ORDER BY marker_id, image_id");
    while (projections.row()) {
        result.projection_marker_ids.push_back(
            uint32_value(
                projections.get(), 0,
                "marker projection marker_id"));
        result.projection_image_ids.push_back(
            image_id_value(
                projections.get(), 1,
                "marker projection image_id"));
        result.projection_xy.push_back(
            number_value(
                projections.get(), 2,
                "marker projection x"));
        result.projection_xy.push_back(
            number_value(
                projections.get(), 3,
                "marker projection y"));
        result.projection_sizes.push_back(
            number_value(
                projections.get(), 4,
                "marker projection size"));
        const int64_t pinned =
            integer(
                projections.get(), 5,
                "marker projection pinned");
        if (pinned != 0 && pinned != 1)
            throw std::invalid_argument(
                "COLMAP database: marker projection pinned "
                "must be 0 or 1");
        result.projection_pinned.push_back(
            static_cast<uint8_t>(pinned));
        result.projection_point2d_indices.push_back(
            uint32_value(
                projections.get(), 6,
                "marker projection point2D_idx"));
    }
    return result;
}

ColmapVideoMetadataSet read_videos(sqlite3 *database) {
    ColmapVideoMetadataSet result;
    if (!table_exists(database, "videos") ||
        !table_exists(database, "video_frames"))
        return result;
    auto append_optional_text =
        [](sqlite3_stmt *statement, int column,
           std::vector<uint8_t> &presence,
           std::vector<std::string> &values,
           const char *name) {
            const bool present =
                sqlite3_column_type(statement, column) != SQLITE_NULL;
            presence.push_back(static_cast<uint8_t>(present));
            values.push_back(
                present ? text(statement, column, name) : std::string{});
        };
    Statement videos(
        database,
        "SELECT video_id, name, source_path, content_hash, "
        "width, height, num_frames, fps, duration_seconds, "
        "codec_name, sync_group FROM videos ORDER BY video_id");
    while (videos.row()) {
        result.video_ids.push_back(
            uint32_value(videos.get(), 0, "video_id"));
        result.names.push_back(text(videos.get(), 1, "video name"));
        append_optional_text(
            videos.get(), 2, result.source_path_present,
            result.source_paths, "video source_path");
        append_optional_text(
            videos.get(), 3, result.content_hash_present,
            result.content_hashes, "video content_hash");
        result.widths.push_back(
            int32_value(videos.get(), 4, "video width"));
        result.heights.push_back(
            int32_value(videos.get(), 5, "video height"));
        result.num_frames.push_back(
            integer(videos.get(), 6, "video num_frames"));
        result.fps.push_back(
            number_value(videos.get(), 7, "video fps"));
        result.duration_seconds.push_back(
            number_value(
                videos.get(), 8, "video duration_seconds"));
        append_optional_text(
            videos.get(), 9, result.codec_name_present,
            result.codec_names, "video codec_name");
        append_optional_text(
            videos.get(), 10, result.sync_group_present,
            result.sync_groups, "video sync_group");
    }

    Statement frames(
        database,
        "SELECT video_id, image_id, frame_id, pts_seconds, "
        "time_id FROM video_frames "
        "ORDER BY video_id, frame_id");
    while (frames.row()) {
        result.frame_video_ids.push_back(
            uint32_value(
                frames.get(), 0, "video frame video_id"));
        result.frame_image_ids.push_back(
            image_id_value(
                frames.get(), 1, "video frame image_id"));
        result.frame_ids.push_back(
            integer(frames.get(), 2, "video frame_id"));
        const bool pts_present =
            sqlite3_column_type(frames.get(), 3) != SQLITE_NULL;
        result.pts_present.push_back(
            static_cast<uint8_t>(pts_present));
        result.pts_seconds.push_back(
            pts_present
                ? number_value(
                      frames.get(), 3,
                      "video frame pts_seconds")
                : 0.0);
        const bool time_present =
            sqlite3_column_type(frames.get(), 4) != SQLITE_NULL;
        result.time_id_present.push_back(
            static_cast<uint8_t>(time_present));
        result.time_ids.push_back(
            time_present
                ? uint32_value(
                      frames.get(), 4,
                      "video frame time_id")
                : 0);
    }
    return result;
}

void read_maxx_ownership(
    sqlite3 *database, ColmapDatabase &result) {
    if (!table_exists(database, "maxx_schema_info"))
        return;
    Statement ownership(
        database,
        "SELECT schema_version, minimum_reader_version, "
        "producer_version, producer_commit "
        "FROM maxx_schema_info ORDER BY schema_version");
    if (!ownership.row())
        throw std::invalid_argument(
            "COLMAP database: maxx_schema_info is empty");
    result.maxx_schema_info.schema_version =
        uint32_value(
            ownership.get(), 0, "MAXX schema_version");
    result.maxx_schema_info.minimum_reader_version =
        uint32_value(
            ownership.get(), 1,
            "MAXX minimum_reader_version");
    result.maxx_schema_info.producer_version =
        text(ownership.get(), 2, "MAXX producer_version");
    result.maxx_schema_info.producer_commit =
        text(ownership.get(), 3, "MAXX producer_commit");
    result.maxx_schema_info.present = true;
    if (ownership.row())
        throw std::invalid_argument(
            "COLMAP database: maxx_schema_info must contain "
            "exactly one row");
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
    bool camera1_present = false;
    bool camera2_present = false;
    Camera recovered_camera1;
    Camera recovered_camera2;
    uint8_t camera1_prior_focal_length = 0;
    uint8_t camera2_prior_focal_length = 0;
    bool scores_present = false;
    std::vector<float> scores;
    bool provenance_present = false;
    uint32_t source_flags = 0;
    bool retrieval_score_present = false;
    float retrieval_score = 0.0f;
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

void read_match_scores(
    sqlite3 *database, std::map<int64_t, PairRow> &rows,
    int64_t only_pair = -1) {
    if (!table_exists(database, "match_scores"))
        return;
    Statement statement(
        database,
        only_pair < 0
            ? "SELECT pair_id, rows, cols, data "
              "FROM match_scores ORDER BY pair_id"
            : "SELECT pair_id, rows, cols, data "
              "FROM match_scores WHERE pair_id=?1");
    if (only_pair >= 0)
        check(
            database,
            sqlite3_bind_int64(
                statement.get(), 1, only_pair),
            "binding pair_id");
    while (statement.row()) {
        const int64_t pair_id =
            integer(statement.get(), 0, "match score pair_id");
        PairRow &row = pair_row(rows, pair_id);
        if (row.scores_present)
            throw std::invalid_argument(
                "COLMAP database: duplicate match score row");
        const size_t count =
            extent(statement.get(), 1, "match score rows");
        const size_t columns =
            extent(statement.get(), 2, "match score cols");
        if (columns != 1)
            throw std::invalid_argument(
                "COLMAP database: match score cols must be 1");
        row.scores = numeric_blob<float>(
            statement.get(), 3, count, 1, "match score data");
        row.scores_present = true;
    }
}

void read_pair_provenance(
    sqlite3 *database, std::map<int64_t, PairRow> &rows,
    int64_t only_pair = -1) {
    if (!table_exists(database, "pair_provenance"))
        return;
    Statement statement(
        database,
        only_pair < 0
            ? "SELECT pair_id, source_flags, retrieval_score "
              "FROM pair_provenance ORDER BY pair_id"
            : "SELECT pair_id, source_flags, retrieval_score "
              "FROM pair_provenance WHERE pair_id=?1");
    if (only_pair >= 0)
        check(
            database,
            sqlite3_bind_int64(
                statement.get(), 1, only_pair),
            "binding pair_id");
    while (statement.row()) {
        const int64_t pair_id =
            integer(statement.get(), 0, "provenance pair_id");
        PairRow &row = pair_row(rows, pair_id);
        if (row.provenance_present)
            throw std::invalid_argument(
                "COLMAP database: duplicate pair provenance row");
        row.source_flags =
            uint32_value(
                statement.get(), 1, "pair source_flags");
        if (sqlite3_column_type(statement.get(), 2) != SQLITE_NULL) {
            const double score = number_value(
                statement.get(), 2, "pair retrieval_score");
            const float converted = static_cast<float>(score);
            row.retrieval_score = converted;
            row.retrieval_score_present = true;
        }
        row.provenance_present = true;
    }
}

void read_geometries(
    sqlite3 *database, std::map<int64_t, PairRow> &rows,
    int64_t only_pair = -1) {
    const bool has_camera1 = column_exists(
        database, "two_view_geometries", "camera1");
    const bool has_camera2 = column_exists(
        database, "two_view_geometries", "camera2");
    if (has_camera1 != has_camera2)
        throw std::invalid_argument(
            "COLMAP database: two_view_geometries camera1 and "
            "camera2 columns must be present together");
    const std::string camera_columns =
        has_camera1 ? "camera1, camera2 "
                    : "NULL, NULL ";
    Statement statement(
        database,
        only_pair < 0
            ? "SELECT pair_id, rows, cols, data, config, "
              "F, E, H, qvec, tvec, " +
                  camera_columns +
                  "FROM two_view_geometries ORDER BY pair_id"
            : "SELECT pair_id, rows, cols, data, config, "
              "F, E, H, qvec, tvec, " +
                  camera_columns +
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
        row.camera1_present = optional_recovered_camera(
            statement.get(), 10, row.recovered_camera1,
            row.camera1_prior_focal_length, "camera1");
        row.camera2_present = optional_recovered_camera(
            statement.get(), 11, row.recovered_camera2,
            row.camera2_prior_focal_length, "camera2");
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
    graph.match_score_present.reserve(rows.size());
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
    graph.camera1_present.reserve(rows.size());
    graph.camera2_present.reserve(rows.size());
    graph.recovered_camera1.reserve(rows.size());
    graph.recovered_camera2.reserve(rows.size());
    graph.camera1_prior_focal_length.reserve(rows.size());
    graph.camera2_prior_focal_length.reserve(rows.size());
    graph.provenance_present.reserve(rows.size());
    graph.source_flags.reserve(rows.size());
    graph.retrieval_score_present.reserve(rows.size());
    graph.retrieval_scores.reserve(rows.size());
    bool any_scores = false;
    for (const auto &[pair_id, row] : rows) {
        graph.pair_ids.push_back(pair_id);
        graph.image_pairs.push_back(row.low);
        graph.image_pairs.push_back(row.high);
        graph.match_present.push_back(row.match_present);
        graph.match_score_present.push_back(
            static_cast<uint8_t>(row.scores_present));
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
        graph.camera1_present.push_back(
            row.camera1_present);
        graph.camera2_present.push_back(
            row.camera2_present);
        graph.recovered_camera1.push_back(
            row.recovered_camera1);
        graph.recovered_camera2.push_back(
            row.recovered_camera2);
        graph.camera1_prior_focal_length.push_back(
            row.camera1_prior_focal_length);
        graph.camera2_prior_focal_length.push_back(
            row.camera2_prior_focal_length);
        if (row.scores_present) {
            if (!row.match_present ||
                row.scores.size() != row.matches.size() / 2)
                throw std::invalid_argument(
                    "COLMAP database: match scores must be "
                    "parallel to a raw match row");
            any_scores = true;
            graph.scores.insert(
                graph.scores.end(),
                row.scores.begin(), row.scores.end());
        } else {
            graph.scores.insert(
                graph.scores.end(),
                row.matches.size() / 2, 0.0f);
        }
        graph.provenance_present.push_back(
            static_cast<uint8_t>(row.provenance_present));
        graph.source_flags.push_back(row.source_flags);
        graph.retrieval_score_present.push_back(
            static_cast<uint8_t>(row.retrieval_score_present));
        graph.retrieval_scores.push_back(row.retrieval_score);
    }
    graph.has_scores = any_scores;
    if (!any_scores)
        graph.scores.clear();
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
    const ProfileIdentity identity = identify_profile(database);
    reject_unknown_tables(database);
    ColmapDatabase result;
    result.user_version = identity.user_version;
    result.application_id = identity.application_id;
    result.profile = identity.name;
    read_maxx_ownership(database, result);
    result.cameras =
        read_cameras(database, result.prior_focal_length);
    std::unordered_map<uint32_t, const Camera *> cameras;
    cameras.reserve(result.cameras.size());
    for (const Camera &camera : result.cameras)
        cameras.emplace(camera.id, &camera);
    result.features = read_images(database, cameras);
    result.rig_frames = read_rig_frames(database);
    result.pose_priors =
        read_pose_priors(database, result.features);
    const auto index = feature_index(result.features);
    read_keypoints(database, result.features, index);
    read_keypoint_colors(database, result.features, index);
    read_descriptors(database, result.features, index);
    read_image_qualities(database, result.features, index);
    std::map<int64_t, PairRow> rows;
    read_matches(database, rows);
    read_match_scores(database, rows);
    read_geometries(database, rows);
    read_pair_provenance(database, rows);
    result.match_graph = make_graph(rows);
    result.markers = read_markers(database);
    result.video_metadata = read_videos(database);
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
    read_keypoints(
        database, one, index, selected_image_id);
    read_keypoint_colors(
        database, one, index, selected_image_id);
    read_descriptors(
        database, one, index, selected_image_id);
    read_image_qualities(
        database, one, index, selected_image_id);
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
    read_match_scores(database, rows, selected_pair);
    read_geometries(database, rows, selected_pair);
    read_pair_provenance(database, rows, selected_pair);
    if (rows.empty())
        throw std::out_of_range(
            "COLMAP database: image pair was not found");
    MatchGraph graph = make_graph(rows);
    if (!graph.match_present[0] &&
        !graph.geometry_present[0])
        return graph;
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

void drop_known_schema(sqlite3 *database) {
    execute(
        database,
        R"SQL(
DROP TABLE IF EXISTS marker_projections;
DROP TABLE IF EXISTS markers;
DROP TABLE IF EXISTS match_scores;
DROP TABLE IF EXISTS keypoint_colors;
DROP TABLE IF EXISTS pair_provenance;
DROP TABLE IF EXISTS maxx_schema_info;
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
)SQL");
}

void create_schema(sqlite3 *database) {
    drop_known_schema(database);
    execute(
        database,
        R"SQL(
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
        if (features.pixel_center[0] != 0.5 ||
            features.pixel_center[1] != 0.5)
            throw std::invalid_argument(
                "COLMAP database writer: FeatureSet pixel_center "
                "must be (0.5,0.5)");
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

const ColmapDbProfileSpec &profile_spec(
    const std::string &name) {
    for (const ColmapDbProfileSpec &profile :
         colmap_db_profile_specs())
        if (name == profile.name) return profile;
    throw std::invalid_argument(
        "COLMAP database writer: unknown target profile '" +
        name + "'");
}

bool any_present(const std::vector<uint8_t> &values) {
    return std::any_of(
        values.begin(), values.end(),
        [](uint8_t value) { return value != 0; });
}

int32_t descriptor_dtype_wire(sio::DType dtype) {
    switch (dtype) {
        case sio::DType::U8:
            return 0;
        case sio::DType::I8:
            return 1;
        case sio::DType::F16:
            return 2;
        case sio::DType::F32:
            return 3;
        case sio::DType::F64:
            return 4;
        default:
            throw std::invalid_argument(
                "COLMAP database writer: descriptor dtype has "
                "no MAXX wire value");
    }
}

void bind_null(
    sqlite3 *database, sqlite3_stmt *statement,
    int parameter) {
    check(
        database,
        sqlite3_bind_null(statement, parameter),
        "binding NULL");
}

void bind_optional_text(
    sqlite3 *database, sqlite3_stmt *statement,
    int parameter, bool present,
    const std::string &value) {
    if (present)
        bind_text(database, statement, parameter, value);
    else
        bind_null(database, statement, parameter);
}

void bind_optional_number(
    sqlite3 *database, sqlite3_stmt *statement,
    int parameter, bool present, double value) {
    if (present)
        check(
            database,
            sqlite3_bind_double(statement, parameter, value),
            "binding REAL");
    else
        bind_null(database, statement, parameter);
}

std::vector<double> column_major_matrix(
    const std::vector<double> &values, size_t offset,
    size_t dimension) {
    std::vector<double> result(dimension * dimension);
    for (size_t row = 0; row < dimension; ++row)
        for (size_t column = 0; column < dimension; ++column)
            result[column * dimension + row] =
                values[offset + row * dimension + column];
    return result;
}

void append_u32_le(
    std::vector<uint8_t> &target, uint32_t value) {
    for (size_t byte = 0; byte < 4; ++byte)
        target.push_back(
            static_cast<uint8_t>(value >> (byte * 8)));
}

void append_u64_le(
    std::vector<uint8_t> &target, uint64_t value) {
    for (size_t byte = 0; byte < 8; ++byte)
        target.push_back(
            static_cast<uint8_t>(value >> (byte * 8)));
}

std::vector<uint8_t> recovered_camera_blob(
    const Camera &camera, uint8_t prior_focal_length) {
    std::vector<uint8_t> result;
    result.reserve(33 + camera.params.size() * sizeof(double));
    append_u32_le(result, camera.id);
    append_u32_le(
        result, static_cast<uint32_t>(camera.model_id));
    append_u64_le(result, camera.width);
    append_u64_le(result, camera.height);
    result.push_back(prior_focal_length);
    append_u64_le(result, camera.params.size());
    for (double parameter : camera.params) {
        uint64_t bits = 0;
        std::memcpy(&bits, &parameter, sizeof(double));
        append_u64_le(result, bits);
    }
    return result;
}

std::vector<std::string> profile_incompatibilities(
    const ColmapDatabase &value,
    const ColmapDbProfileSpec &profile) {
    std::vector<std::string> result;
    const auto add = [&result](const char *message) {
        if (std::find(
                result.begin(), result.end(), message) ==
            result.end())
            result.emplace_back(message);
    };
    const bool maxx = profile.maxx_extensions;
    for (const FeatureSet &features : value.features) {
        if (features.pixel_center[0] != 0.5 ||
            features.pixel_center[1] != 0.5)
            add("COLMAP database requires FeatureSet pixel_center "
                "(0.5,0.5)");
        if (features.has_scores)
            add("per-keypoint scores are not represented by "
                "any selected database profile");
        if (!maxx &&
            (features.has_time_id ||
             features.keypoint_colors_present ||
             features.quality_present ||
             features.descriptor_dtype_present ||
             features.descriptor_dim_present ||
             features.extractor_type_name_present))
            add("selected stock profile cannot represent MAXX "
                "image or descriptor metadata");
        if (!features.has_descriptors) continue;
        if (!profile.typed_descriptors) {
            if (features.extractor_type != 0 ||
                features.descriptor_dtype != sio::DType::U8)
                add("COLMAP 3.13 descriptors must be uint8 SIFT");
        } else if (!maxx) {
            const sio::DType expected =
                effective_descriptor_dtype(
                    features.extractor_type, false);
            if (features.descriptor_dtype != expected)
                add("selected stock profile cannot preserve a "
                    "descriptor dtype that differs from its "
                    "extractor-type inference");
        }
        const size_t itemsize =
            sio::dtype_info(
                features.descriptor_dtype).itemsize;
        if (features.descriptor_columns >
            static_cast<size_t>(
                std::numeric_limits<int64_t>::max()) /
                itemsize)
            add("stored descriptor column count exceeds "
                "SQLite INTEGER");
    }

    const ColmapPosePriorSet &priors = value.pose_priors;
    for (uint64_t data_id : value.rig_frames.frame_data_ids)
        if (data_id >
            static_cast<uint64_t>(
                std::numeric_limits<int64_t>::max()))
            add("frame data_id exceeds SQLite INTEGER");
    for (uint64_t data_id : priors.corr_data_ids)
        if (data_id >
            static_cast<uint64_t>(
                std::numeric_limits<int64_t>::max()))
            add("pose-prior data_id exceeds SQLite INTEGER");
    if (priors.size() != 0 &&
        priors.generalized != profile.generalized_pose_priors)
        add("pose-prior layout does not match the selected profile");
    if (!maxx &&
        (any_present(priors.rotation_present) ||
         any_present(priors.rotation_covariance_present) ||
         any_present(priors.pose_covariance_present)))
        add("selected stock profile cannot represent extended "
            "pose-prior fields");

    const MatchGraph &graph = value.match_graph;
    if (!profile.recovered_two_view_cameras &&
        (any_present(graph.camera1_present) ||
         any_present(graph.camera2_present)))
        add("selected profile cannot represent recovered "
            "two-view cameras");
    if (!maxx &&
        (graph.has_scores ||
         any_present(graph.provenance_present)))
        add("selected stock profile cannot represent match "
            "scores or provenance");
    if (!maxx &&
        (value.markers.num_markers() != 0 ||
         value.markers.num_projections() != 0 ||
         value.video_metadata.num_videos() != 0 ||
         value.video_metadata.num_video_frames() != 0 ||
         value.maxx_schema_info.present))
        add("selected stock profile cannot represent MAXX "
            "companion records");
    if (maxx && !value.maxx_schema_info.present)
        add("maxx-v1 requires an explicit ownership row");
    if (maxx && value.maxx_schema_info.present &&
        (value.maxx_schema_info.schema_version != 1 ||
         value.maxx_schema_info.minimum_reader_version != 1))
        add("maxx-v1 ownership versions must both equal 1");
    if (maxx)
        for (uint64_t point3d_id : value.markers.point3d_ids)
            if (point3d_id !=
                    std::numeric_limits<uint64_t>::max() &&
                point3d_id >
                    static_cast<uint64_t>(
                        std::numeric_limits<int64_t>::max()))
                add("marker point3D_id exceeds SQLite INTEGER");
    return result;
}

void validate_profile_encodable(
    const ColmapDatabase &value,
    const ColmapDbProfileSpec &profile) {
    const std::vector<std::string> issues =
        profile_incompatibilities(value, profile);
    if (!issues.empty())
        throw std::invalid_argument(
            "COLMAP database writer: " + issues.front());
}

void write_rig_frame_rows(
    sqlite3 *database, const ColmapRigFrameSet &value) {
    Statement rigs(
        database,
        "INSERT INTO rigs("
        "rig_id,ref_sensor_id,ref_sensor_type"
        ") VALUES(?1,?2,?3)");
    Statement sensors(
        database,
        "INSERT INTO rig_sensors("
        "rig_id,sensor_id,sensor_type,sensor_from_rig"
        ") VALUES(?1,?2,?3,?4)");
    for (size_t rig = 0; rig < value.num_rigs(); ++rig) {
        bind_int64(database, rigs.get(), 1, value.rig_ids[rig]);
        bind_int64(
            database, rigs.get(), 2,
            value.rig_ref_sensor_ids[rig]);
        bind_int64(
            database, rigs.get(), 3,
            value.rig_ref_sensor_types[rig]);
        rigs.done();
        for (uint64_t row = value.rig_sensor_offsets[rig];
             row < value.rig_sensor_offsets[rig + 1]; ++row) {
            const size_t index = static_cast<size_t>(row);
            bind_int64(
                database, sensors.get(), 1,
                value.rig_ids[rig]);
            bind_int64(
                database, sensors.get(), 2,
                value.rig_sensor_ids[index]);
            bind_int64(
                database, sensors.get(), 3,
                value.rig_sensor_types[index]);
            std::array<double, 7> pose{};
            std::copy_n(
                value.rig_sensor_qvecs.data() + index * 4,
                4, pose.data());
            std::copy_n(
                value.rig_sensor_tvecs.data() + index * 3,
                3, pose.data() + 4);
            bind_optional_blob(
                database, sensors.get(), 4,
                value.rig_sensor_pose_present[index],
                pose.data(), pose.size() * sizeof(double));
            sensors.done();
        }
    }

    Statement frames(
        database,
        "INSERT INTO frames(frame_id,rig_id) VALUES(?1,?2)");
    Statement data(
        database,
        "INSERT INTO frame_data("
        "frame_id,data_id,sensor_id,sensor_type"
        ") VALUES(?1,?2,?3,?4)");
    for (size_t frame = 0;
         frame < value.num_frames(); ++frame) {
        bind_int64(
            database, frames.get(), 1,
            value.frame_ids[frame]);
        bind_int64(
            database, frames.get(), 2,
            value.frame_rig_ids[frame]);
        frames.done();
        for (uint64_t row = value.frame_data_offsets[frame];
             row < value.frame_data_offsets[frame + 1]; ++row) {
            const size_t index = static_cast<size_t>(row);
            bind_int64(
                database, data.get(), 1,
                value.frame_ids[frame]);
            bind_int64(
                database, data.get(), 2,
                static_cast<int64_t>(
                    value.frame_data_ids[index]));
            bind_int64(
                database, data.get(), 3,
                value.frame_sensor_ids[index]);
            bind_int64(
                database, data.get(), 4,
                value.frame_sensor_types[index]);
            data.done();
        }
    }
}

void write_pose_prior_rows(
    sqlite3 *database, const ColmapPosePriorSet &value,
    const ColmapDbProfileSpec &profile) {
    if (!profile.generalized_pose_priors) {
        Statement rows(
            database,
            "INSERT INTO pose_priors("
            "image_id,position,coordinate_system,"
            "position_covariance) VALUES(?1,?2,?3,?4)");
        for (size_t index = 0; index < value.size(); ++index) {
            bind_int64(
                database, rows.get(), 1,
                value.prior_ids[index]);
            bind_optional_blob(
                database, rows.get(), 2,
                value.position_present[index],
                value.positions.data() + index * 3,
                3 * sizeof(double));
            bind_int64(
                database, rows.get(), 3,
                value.coordinate_systems[index]);
            const std::vector<double> covariance =
                column_major_matrix(
                    value.position_covariances,
                    index * 9, 3);
            bind_optional_blob(
                database, rows.get(), 4,
                value.position_covariance_present[index],
                covariance.data(),
                covariance.size() * sizeof(double));
            rows.done();
        }
        return;
    }

    Statement rows(
        database,
        profile.maxx_extensions
            ? "INSERT INTO pose_priors("
              "pose_prior_id,corr_data_id,corr_sensor_id,"
              "corr_sensor_type,position,position_covariance,"
              "gravity,coordinate_system,rotation,"
              "rotation_covariance,pose_covariance"
              ") VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,"
              "?10,?11)"
            : "INSERT INTO pose_priors("
              "pose_prior_id,corr_data_id,corr_sensor_id,"
              "corr_sensor_type,position,position_covariance,"
              "gravity,coordinate_system"
              ") VALUES(?1,?2,?3,?4,?5,?6,?7,?8)");
    for (size_t index = 0; index < value.size(); ++index) {
        bind_int64(
            database, rows.get(), 1,
            value.prior_ids[index]);
        bind_int64(
            database, rows.get(), 2,
            static_cast<int64_t>(value.corr_data_ids[index]));
        bind_int64(
            database, rows.get(), 3,
            value.corr_sensor_ids[index]);
        bind_int64(
            database, rows.get(), 4,
            value.corr_sensor_types[index]);
        bind_optional_blob(
            database, rows.get(), 5,
            value.position_present[index],
            value.positions.data() + index * 3,
            3 * sizeof(double));
        const std::vector<double> position_covariance =
            column_major_matrix(
                value.position_covariances, index * 9, 3);
        bind_optional_blob(
            database, rows.get(), 6,
            value.position_covariance_present[index],
            position_covariance.data(),
            position_covariance.size() * sizeof(double));
        bind_optional_blob(
            database, rows.get(), 7,
            value.gravity_present[index],
            value.gravities.data() + index * 3,
            3 * sizeof(double));
        bind_int64(
            database, rows.get(), 8,
            value.coordinate_systems[index]);
        if (profile.maxx_extensions) {
            bind_optional_blob(
                database, rows.get(), 9,
                value.rotation_present[index],
                value.rotations.data() + index * 4,
                4 * sizeof(double));
            const std::vector<double> rotation_covariance =
                column_major_matrix(
                    value.rotation_covariances,
                    index * 9, 3);
            bind_optional_blob(
                database, rows.get(), 10,
                value.rotation_covariance_present[index],
                rotation_covariance.data(),
                rotation_covariance.size() * sizeof(double));
            const std::vector<double> pose_covariance =
                column_major_matrix(
                    value.pose_covariances,
                    index * 36, 6);
            bind_optional_blob(
                database, rows.get(), 11,
                value.pose_covariance_present[index],
                pose_covariance.data(),
                pose_covariance.size() * sizeof(double));
        }
        rows.done();
    }
}

void write_camera_feature_rows(
    sqlite3 *database, const ColmapDatabase &value,
    const ColmapDbProfileSpec &profile) {
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
            database, cameras.get(), 3,
            static_cast<int64_t>(camera.width));
        bind_int64(
            database, cameras.get(), 4,
            static_cast<int64_t>(camera.height));
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
        profile.maxx_extensions
            ? "INSERT INTO images("
              "image_id,name,camera_id,time_id"
              ") VALUES(?1,?2,?3,?4)"
            : "INSERT INTO images("
              "image_id,name,camera_id"
              ") VALUES(?1,?2,?3)");
    Statement keypoints(
        database,
        "INSERT INTO keypoints("
        "image_id,rows,cols,data"
        ") VALUES(?1,?2,?3,?4)");
    const std::string descriptor_sql =
        profile.maxx_extensions
            ? "INSERT INTO descriptors("
              "image_id,type,type_name,dtype,dim,rows,cols,data"
              ") VALUES(?1,?2,?3,?4,?5,?6,?7,?8)"
            : profile.typed_descriptors
                  ? "INSERT INTO descriptors("
                    "image_id,type,rows,cols,data"
                    ") VALUES(?1,?2,?3,?4,?5)"
                  : "INSERT INTO descriptors("
                    "image_id,rows,cols,data"
                    ") VALUES(?1,?2,?3,?4)";
    Statement descriptors(database, descriptor_sql);

    for (const FeatureSet &features : value.features) {
        bind_int64(
            database, images.get(), 1, features.image_id);
        bind_text(
            database, images.get(), 2, features.image_name);
        bind_int64(
            database, images.get(), 3, features.camera_id);
        if (profile.maxx_extensions) {
            if (features.has_time_id)
                bind_int64(
                    database, images.get(), 4,
                    features.time_id);
            else
                bind_null(database, images.get(), 4);
        }
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
        if (!features.has_descriptors) continue;

        const size_t itemsize =
            sio::dtype_info(
                features.descriptor_dtype).itemsize;
        const size_t stored_columns =
            features.descriptor_columns * itemsize;
        bind_int64(
            database, descriptors.get(), 1,
            features.image_id);
        if (profile.maxx_extensions) {
            bind_int64(
                database, descriptors.get(), 2,
                features.extractor_type);
            bind_optional_text(
                database, descriptors.get(), 3,
                features.extractor_type_name_present,
                features.extractor_type_name);
            if (features.descriptor_dtype_present)
                bind_int64(
                    database, descriptors.get(), 4,
                    descriptor_dtype_wire(
                        features.descriptor_dtype));
            else
                bind_null(database, descriptors.get(), 4);
            if (features.descriptor_dim_present)
                bind_int64(
                    database, descriptors.get(), 5,
                    features.descriptor_columns);
            else
                bind_null(database, descriptors.get(), 5);
            bind_int64(
                database, descriptors.get(), 6,
                features.rows);
            bind_int64(
                database, descriptors.get(), 7,
                stored_columns);
            bind_blob(
                database, descriptors.get(), 8,
                features.descriptors.data(),
                features.descriptors.size());
        } else if (profile.typed_descriptors) {
            bind_int64(
                database, descriptors.get(), 2,
                features.extractor_type);
            bind_int64(
                database, descriptors.get(), 3,
                features.rows);
            bind_int64(
                database, descriptors.get(), 4,
                stored_columns);
            bind_blob(
                database, descriptors.get(), 5,
                features.descriptors.data(),
                features.descriptors.size());
        } else {
            bind_int64(
                database, descriptors.get(), 2,
                features.rows);
            bind_int64(
                database, descriptors.get(), 3,
                stored_columns);
            bind_blob(
                database, descriptors.get(), 4,
                features.descriptors.data(),
                features.descriptors.size());
        }
        descriptors.done();
    }
}

void write_match_rows(
    sqlite3 *database, const MatchGraph &graph,
    const ColmapDbProfileSpec &profile) {
    Statement matches(
        database,
        "INSERT INTO matches("
        "pair_id,rows,cols,data"
        ") VALUES(?1,?2,2,?3)");
    Statement geometries(
        database,
        profile.recovered_two_view_cameras
            ? "INSERT INTO two_view_geometries("
              "pair_id,rows,cols,data,config,F,E,H,qvec,tvec,"
              "camera1,camera2"
              ") VALUES(?1,?2,2,?3,?4,?5,?6,?7,?8,?9,"
              "?10,?11)"
            : "INSERT INTO two_view_geometries("
              "pair_id,rows,cols,data,config,F,E,H,qvec,tvec"
              ") VALUES(?1,?2,2,?3,?4,?5,?6,?7,?8,?9)");
    for (size_t pair = 0; pair < graph.pair_count; ++pair) {
        const size_t match_begin =
            static_cast<size_t>(graph.match_offsets[pair]);
        const size_t match_end =
            static_cast<size_t>(graph.match_offsets[pair + 1]);
        if (graph.match_present[pair]) {
            bind_int64(
                database, matches.get(), 1,
                graph.pair_ids[pair]);
            bind_int64(
                database, matches.get(), 2,
                match_end - match_begin);
            bind_blob(
                database, matches.get(), 3,
                match_begin == match_end
                    ? nullptr
                    : graph.matches.data() + match_begin * 2,
                (match_end - match_begin) * 2 *
                    sizeof(uint32_t));
            matches.done();
        }
        if (!graph.geometry_present[pair]) continue;
        const size_t verified_begin =
            static_cast<size_t>(
                graph.verified_offsets[pair]);
        const size_t verified_end =
            static_cast<size_t>(
                graph.verified_offsets[pair + 1]);
        bind_int64(
            database, geometries.get(), 1,
            graph.pair_ids[pair]);
        bind_int64(
            database, geometries.get(), 2,
            verified_end - verified_begin);
        bind_blob(
            database, geometries.get(), 3,
            verified_begin == verified_end
                ? nullptr
                : graph.verified_matches.data() +
                      verified_begin * 2,
            (verified_end - verified_begin) * 2 *
                sizeof(uint32_t));
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
        if (profile.recovered_two_view_cameras) {
            std::vector<uint8_t> camera1;
            std::vector<uint8_t> camera2;
            if (graph.camera1_present[pair])
                camera1 = recovered_camera_blob(
                    graph.recovered_camera1[pair],
                    graph.camera1_prior_focal_length[pair]);
            if (graph.camera2_present[pair])
                camera2 = recovered_camera_blob(
                    graph.recovered_camera2[pair],
                    graph.camera2_prior_focal_length[pair]);
            bind_optional_blob(
                database, geometries.get(), 10,
                graph.camera1_present[pair],
                camera1.data(), camera1.size());
            bind_optional_blob(
                database, geometries.get(), 11,
                graph.camera2_present[pair],
                camera2.data(), camera2.size());
        }
        geometries.done();
    }

    if (!profile.maxx_extensions) return;
    Statement scores(
        database,
        "INSERT INTO match_scores("
        "pair_id,rows,cols,data"
        ") VALUES(?1,?2,1,?3)");
    Statement provenance(
        database,
        "INSERT INTO pair_provenance("
        "pair_id,source_flags,retrieval_score"
        ") VALUES(?1,?2,?3)");
    for (size_t pair = 0; pair < graph.pair_count; ++pair) {
        const size_t begin =
            static_cast<size_t>(graph.match_offsets[pair]);
        const size_t end =
            static_cast<size_t>(graph.match_offsets[pair + 1]);
        if (graph.match_score_present[pair]) {
            bind_int64(
                database, scores.get(), 1,
                graph.pair_ids[pair]);
            bind_int64(
                database, scores.get(), 2, end - begin);
            bind_blob(
                database, scores.get(), 3,
                begin == end
                    ? nullptr
                    : graph.scores.data() + begin,
                (end - begin) * sizeof(float));
            scores.done();
        }
        if (graph.provenance_present[pair]) {
            bind_int64(
                database, provenance.get(), 1,
                graph.pair_ids[pair]);
            bind_int64(
                database, provenance.get(), 2,
                graph.source_flags[pair]);
            bind_optional_number(
                database, provenance.get(), 3,
                graph.retrieval_score_present[pair],
                graph.retrieval_scores[pair]);
            provenance.done();
        }
    }
}

void write_maxx_rows(
    sqlite3 *database, const ColmapDatabase &value,
    const ColmapDbProfileSpec &profile) {
    if (!profile.maxx_extensions) return;

    Statement colors(
        database,
        "INSERT INTO keypoint_colors("
        "image_id,rows,cols,data"
        ") VALUES(?1,?2,3,?3)");
    Statement qualities(
        database,
        "INSERT INTO image_qualities(image_id,quality) "
        "VALUES(?1,?2)");
    for (const FeatureSet &features : value.features) {
        if (features.keypoint_colors_present) {
            bind_int64(
                database, colors.get(), 1,
                features.image_id);
            bind_int64(
                database, colors.get(), 2,
                features.rows);
            bind_blob(
                database, colors.get(), 3,
                features.keypoint_colors.data(),
                features.keypoint_colors.size());
            colors.done();
        }
        if (features.quality_present) {
            bind_int64(
                database, qualities.get(), 1,
                features.image_id);
            check(
                database,
                sqlite3_bind_double(
                    qualities.get(), 2,
                    features.quality),
                "binding image quality");
            qualities.done();
        }
    }

    const ColmapMarkerSet &markers = value.markers;
    Statement marker_rows(
        database,
        "INSERT INTO markers("
        "marker_id,label,type,world_position,"
        "world_position_cov,point3D_id,enabled"
        ") VALUES(?1,?2,?3,?4,?5,?6,?7)");
    for (size_t index = 0;
         index < markers.num_markers(); ++index) {
        bind_int64(
            database, marker_rows.get(), 1,
            markers.marker_ids[index]);
        bind_text(
            database, marker_rows.get(), 2,
            markers.labels[index]);
        bind_int64(
            database, marker_rows.get(), 3,
            markers.types[index]);
        bind_optional_blob(
            database, marker_rows.get(), 4,
            markers.world_position_present[index],
            markers.world_positions.data() + index * 3,
            3 * sizeof(double));
        const std::vector<double> covariance =
            column_major_matrix(
                markers.world_covariances,
                index * 9, 3);
        bind_optional_blob(
            database, marker_rows.get(), 5,
            markers.world_covariance_present[index],
            covariance.data(),
            covariance.size() * sizeof(double));
        bind_int64(
            database, marker_rows.get(), 6,
            markers.point3d_ids[index] ==
                    std::numeric_limits<uint64_t>::max()
                ? -1
                : static_cast<int64_t>(
                      markers.point3d_ids[index]));
        bind_int64(
            database, marker_rows.get(), 7,
            markers.enabled[index]);
        marker_rows.done();
    }
    Statement projections(
        database,
        "INSERT INTO marker_projections("
        "marker_id,image_id,x,y,size,pinned,point2D_idx"
        ") VALUES(?1,?2,?3,?4,?5,?6,?7)");
    for (size_t index = 0;
         index < markers.num_projections(); ++index) {
        bind_int64(
            database, projections.get(), 1,
            markers.projection_marker_ids[index]);
        bind_int64(
            database, projections.get(), 2,
            markers.projection_image_ids[index]);
        for (int parameter = 3; parameter <= 5; ++parameter) {
            const double item =
                parameter == 3
                    ? markers.projection_xy[index * 2]
                    : parameter == 4
                          ? markers.projection_xy[index * 2 + 1]
                          : markers.projection_sizes[index];
            check(
                database,
                sqlite3_bind_double(
                    projections.get(), parameter, item),
                "binding marker projection REAL");
        }
        bind_int64(
            database, projections.get(), 6,
            markers.projection_pinned[index]);
        bind_int64(
            database, projections.get(), 7,
            markers.projection_point2d_indices[index]);
        projections.done();
    }

    const ColmapVideoMetadataSet &videos = value.video_metadata;
    Statement video_rows(
        database,
        "INSERT INTO videos("
        "video_id,name,source_path,content_hash,width,height,"
        "num_frames,fps,duration_seconds,codec_name,sync_group"
        ") VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11)");
    for (size_t index = 0;
         index < videos.num_videos(); ++index) {
        bind_int64(
            database, video_rows.get(), 1,
            videos.video_ids[index]);
        bind_text(
            database, video_rows.get(), 2,
            videos.names[index]);
        bind_optional_text(
            database, video_rows.get(), 3,
            videos.source_path_present[index],
            videos.source_paths[index]);
        bind_optional_text(
            database, video_rows.get(), 4,
            videos.content_hash_present[index],
            videos.content_hashes[index]);
        bind_int64(
            database, video_rows.get(), 5,
            videos.widths[index]);
        bind_int64(
            database, video_rows.get(), 6,
            videos.heights[index]);
        bind_int64(
            database, video_rows.get(), 7,
            videos.num_frames[index]);
        check(
            database,
            sqlite3_bind_double(
                video_rows.get(), 8, videos.fps[index]),
            "binding video fps");
        check(
            database,
            sqlite3_bind_double(
                video_rows.get(), 9,
                videos.duration_seconds[index]),
            "binding video duration");
        bind_optional_text(
            database, video_rows.get(), 10,
            videos.codec_name_present[index],
            videos.codec_names[index]);
        bind_optional_text(
            database, video_rows.get(), 11,
            videos.sync_group_present[index],
            videos.sync_groups[index]);
        video_rows.done();
    }
    Statement frame_rows(
        database,
        "INSERT INTO video_frames("
        "video_id,image_id,frame_id,pts_seconds,time_id"
        ") VALUES(?1,?2,?3,?4,?5)");
    for (size_t index = 0;
         index < videos.num_video_frames(); ++index) {
        bind_int64(
            database, frame_rows.get(), 1,
            videos.frame_video_ids[index]);
        bind_int64(
            database, frame_rows.get(), 2,
            videos.frame_image_ids[index]);
        bind_int64(
            database, frame_rows.get(), 3,
            videos.frame_ids[index]);
        bind_optional_number(
            database, frame_rows.get(), 4,
            videos.pts_present[index],
            videos.pts_seconds[index]);
        if (videos.time_id_present[index])
            bind_int64(
                database, frame_rows.get(), 5,
                videos.time_ids[index]);
        else
            bind_null(database, frame_rows.get(), 5);
        frame_rows.done();
    }

    Statement ownership(
        database,
        "INSERT INTO maxx_schema_info("
        "schema_version,minimum_reader_version,"
        "producer_version,producer_commit"
        ") VALUES(?1,?2,?3,?4)");
    bind_int64(
        database, ownership.get(), 1,
        value.maxx_schema_info.schema_version);
    bind_int64(
        database, ownership.get(), 2,
        value.maxx_schema_info.minimum_reader_version);
    bind_text(
        database, ownership.get(), 3,
        value.maxx_schema_info.producer_version);
    bind_text(
        database, ownership.get(), 4,
        value.maxx_schema_info.producer_commit);
    ownership.done();
}

void write_profile_rows(
    sqlite3 *database, const ColmapDatabase &value,
    const ColmapDbProfileSpec &profile) {
    write_rig_frame_rows(database, value.rig_frames);
    write_camera_feature_rows(database, value, profile);
    write_pose_prior_rows(database, value.pose_priors, profile);
    write_match_rows(database, value.match_graph, profile);
    write_maxx_rows(database, value, profile);
}

void validate_colmap_encodable(const ColmapDatabase &value) {
    for (const FeatureSet &features : value.features) {
        if (features.has_scores ||
            features.keypoint_colors_present ||
            features.quality_present ||
            features.descriptor_dtype_present ||
            features.descriptor_dim_present ||
            features.extractor_type_name_present)
            throw std::invalid_argument(
                "COLMAP database writer: feature scores or extended "
                "image metadata require an exact-profile writer");
        if (features.has_descriptors &&
            features.descriptor_dtype != sio::DType::U8)
            throw std::invalid_argument(
                "COLMAP database writer: descriptors "
                "must be uint8");
    }
    if (value.match_graph.has_scores ||
        std::any_of(
            value.match_graph.provenance_present.begin(),
            value.match_graph.provenance_present.end(),
            [](uint8_t present) { return present != 0; }))
        throw std::invalid_argument(
            "COLMAP database writer: match scores and provenance "
            "require an exact-profile writer");
    if (value.rig_frames.num_rigs() != 0 ||
        value.rig_frames.num_frames() != 0 ||
        value.rig_frames.num_rig_sensors() != 0 ||
        value.rig_frames.num_frame_data() != 0 ||
        value.pose_priors.size() != 0)
        throw std::invalid_argument(
            "COLMAP database writer: rigs, frames, and pose priors "
            "require an exact-profile writer");
    if (value.markers.num_markers() != 0 ||
        value.markers.num_projections() != 0 ||
        value.video_metadata.num_videos() != 0 ||
        value.video_metadata.num_video_frames() != 0 ||
        value.maxx_schema_info.present)
        throw std::invalid_argument(
            "COLMAP database writer: MAXX marker, video metadata, "
            "and ownership rows require an exact-profile writer");
    if (std::any_of(
            value.match_graph.camera1_present.begin(),
            value.match_graph.camera1_present.end(),
            [](uint8_t present) { return present != 0; }) ||
        std::any_of(
            value.match_graph.camera2_present.begin(),
            value.match_graph.camera2_present.end(),
            [](uint8_t present) { return present != 0; }))
        throw std::invalid_argument(
            "COLMAP database writer: recovered two-view cameras "
            "require an exact current-profile writer");
}

void verify_written_database(
    sqlite3 *database, const std::string &profile,
    int32_t application_id, int32_t expected_user_version) {
    Statement foreign_keys(database, "PRAGMA foreign_key_check");
    if (foreign_keys.row())
        throw std::runtime_error(
            "COLMAP database writer: foreign-key validation failed");

    Statement integrity(database, "PRAGMA integrity_check");
    if (!integrity.row() ||
        text(integrity.get(), 0, "integrity result") != "ok" ||
        integrity.row())
        throw std::runtime_error(
            "COLMAP database writer: SQLite integrity check failed");

    if (pragma_int(database, "application_id") != application_id ||
        pragma_int(database, "user_version") !=
            expected_user_version)
        throw std::runtime_error(
            "COLMAP database writer: profile identity check failed");
    const ProfileIdentity identity = identify_profile(database);
    if (identity.name != profile)
        throw std::runtime_error(
            "COLMAP database writer: emitted schema does not "
            "match target profile");
}

void write_database(
    const ColmapDatabase &value, const std::string &path,
    const std::string &requested_profile,
    size_t test_fail_after) {
    require_little_endian();
    validate_colmap_database(value, "COLMAP database writer");
    const std::string target_profile =
        requested_profile.empty()
            ? "sceneio-hybrid-v1"
            : requested_profile;
    const bool hybrid =
        target_profile == "sceneio-hybrid-v1";
    const ColmapDbProfileSpec *profile = nullptr;
    if (hybrid) {
        validate_colmap_encodable(value);
        if (value.profile != "sceneio-hybrid-v1" ||
            value.application_id != 0)
            throw std::invalid_argument(
                "COLMAP database writer: exact profile preservation "
                "requires an explicit target profile");
    } else {
        profile = &profile_spec(target_profile);
        validate_profile_encodable(value, *profile);
    }
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
        if (hybrid) {
            create_schema(database);
        } else {
            drop_known_schema(database);
            execute(database, profile->schema_sql);
        }
        if (test_fail_after == 1)
            throw std::runtime_error(
                "COLMAP database: injected failure after schema");
        if (hybrid)
            write_rows(database, value);
        else
            write_profile_rows(database, value, *profile);
        if (test_fail_after == 2)
            throw std::runtime_error(
                "COLMAP database: injected failure after rows");
        execute(
            database,
            "PRAGMA user_version=" +
                std::to_string(
                    hybrid
                        ? value.user_version
                        : profile->user_version));
        execute(
            database,
            "PRAGMA application_id=" +
                std::to_string(
                    hybrid ? 0 : profile->application_id));
        verify_written_database(
            database, target_profile,
            hybrid ? 0 : profile->application_id,
            hybrid ? value.user_version
                   : profile->user_version);
        if (test_fail_after == 3)
            throw std::runtime_error(
                "COLMAP database: injected failure after "
                "profile verification");
        transaction.commit();
    } catch (...) {
        if (created) {
            std::error_code ignored;
            std::filesystem::remove(
                filesystem_path, ignored);
            for (const char *suffix :
                 {"-journal", "-wal", "-shm"}) {
                std::filesystem::path sidecar =
                    filesystem_path;
                sidecar += suffix;
                std::filesystem::remove(sidecar, ignored);
            }
        }
        throw;
    }
}

struct DatabaseInspection {
    std::string profile;
    std::string profile_source_revision;
    std::string schema_signature;
    int32_t application_id = 0;
    int32_t user_version = 0;
    int64_t rigs = 0;
    int64_t rig_sensors = 0;
    int64_t frames = 0;
    int64_t frame_data = 0;
    int64_t pose_priors = 0;
    std::string pose_prior_layout = "none";
    int64_t keypoint_color_rows = 0;
    int64_t match_score_pairs = 0;
    int64_t image_qualities = 0;
    int64_t pair_provenance = 0;
    int64_t markers = 0;
    int64_t marker_projections = 0;
    int64_t videos = 0;
    int64_t video_frames = 0;
    bool maxx_schema_info_present = false;
    uint32_t maxx_schema_version = 0;
    uint32_t maxx_minimum_reader_version = 0;
    std::string maxx_producer_version;
    std::string maxx_producer_commit;
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
    std::vector<std::string> image_descriptor_dtypes;
};

template <typename T>
nb::list integer_list(const std::vector<T> &values) {
    nb::list result;
    for (T value : values) result.append(nb::int_(value));
    return result;
}

nb::list string_list(const std::vector<std::string> &values) {
    nb::list result;
    for (const std::string &value : values)
        result.append(nb::str(value.data(), value.size()));
    return result;
}

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
    require_core_tables(database);
    DatabaseInspection result;
    const ProfileIdentity identity = identify_profile(database);
    result.profile = identity.name;
    result.profile_source_revision = identity.source_revision;
    result.schema_signature =
        schema_signature(identity.schema);
    result.application_id = identity.application_id;
    result.user_version = identity.user_version;
    if (table_exists(database, "rigs"))
        result.rigs = scalar_count(database, "rigs");
    if (table_exists(database, "rig_sensors"))
        result.rig_sensors =
            scalar_count(database, "rig_sensors");
    if (table_exists(database, "frames"))
        result.frames = scalar_count(database, "frames");
    if (table_exists(database, "frame_data"))
        result.frame_data =
            scalar_count(database, "frame_data");
    if (table_exists(database, "pose_priors")) {
        result.pose_priors =
            scalar_count(database, "pose_priors");
        if (column_exists(
                database, "pose_priors", "rotation"))
            result.pose_prior_layout = "correlated-extended";
        else if (column_exists(
                     database, "pose_priors",
                     "pose_prior_id"))
            result.pose_prior_layout = "correlated-modern";
        else
            result.pose_prior_layout = "image-linked-3.13";
    }
    const auto table_count =
        [database](const char *name) {
            return table_exists(database, name)
                       ? scalar_count(database, name)
                       : int64_t{0};
        };
    result.keypoint_color_rows =
        table_count("keypoint_colors");
    result.match_score_pairs = table_count("match_scores");
    result.image_qualities = table_count("image_qualities");
    result.pair_provenance = table_count("pair_provenance");
    result.markers = table_count("markers");
    result.marker_projections =
        table_count("marker_projections");
    result.videos = table_count("videos");
    result.video_frames = table_count("video_frames");
    if (table_exists(database, "maxx_schema_info")) {
        Statement ownership(
            database,
            "SELECT schema_version, minimum_reader_version, "
            "producer_version, producer_commit "
            "FROM maxx_schema_info");
        if (ownership.row()) {
            result.maxx_schema_info_present = true;
            result.maxx_schema_version =
                uint32_value(
                    ownership.get(), 0,
                    "MAXX schema_version");
            result.maxx_minimum_reader_version =
                uint32_value(
                    ownership.get(), 1,
                    "MAXX minimum_reader_version");
            result.maxx_producer_version =
                text(
                    ownership.get(), 2,
                    "MAXX producer_version");
            result.maxx_producer_commit =
                text(
                    ownership.get(), 3,
                    "MAXX producer_commit");
        }
    }
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
        const bool descriptor_type =
            column_exists(database, "descriptors", "type");
        const bool descriptor_metadata =
            column_exists(database, "descriptors", "dtype");
        Statement images(
            database,
            "SELECT i.image_id,i.name,"
            "coalesce(k.rows,-1),coalesce(k.cols,-1),"
            "coalesce(d.rows,-1),coalesce(d.cols,-1)," +
                std::string(
                    descriptor_type ? "d.type," : "NULL,") +
                std::string(
                    descriptor_metadata
                        ? "d.dtype,d.dim "
                        : "NULL,NULL ") +
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
            const int64_t stored_columns =
                integer(
                    images.get(), 5,
                    "descriptor stored columns");
            if (stored_columns < 0) {
                result.image_descriptor_dimensions.push_back(-1);
                result.image_descriptor_dtypes.emplace_back();
                continue;
            }
            const int32_t extractor_type =
                sqlite3_column_type(images.get(), 6) == SQLITE_NULL
                    ? 0
                    : int32_value(
                          images.get(), 6,
                          "descriptor type");
            const bool dtype_present =
                sqlite3_column_type(images.get(), 7) != SQLITE_NULL;
            const sio::DType dtype =
                effective_descriptor_dtype(
                    extractor_type, dtype_present,
                    dtype_present
                        ? int32_value(
                              images.get(), 7,
                              "descriptor dtype")
                        : 0);
            const size_t itemsize =
                sio::dtype_info(dtype).itemsize;
            int64_t logical_dimension = 0;
            if (sqlite3_column_type(images.get(), 8) != SQLITE_NULL) {
                logical_dimension =
                    integer(
                        images.get(), 8,
                        "descriptor dimension");
            } else {
                if (stored_columns %
                        static_cast<int64_t>(itemsize) != 0)
                    throw std::invalid_argument(
                        "COLMAP database: descriptor cols are "
                        "not divisible by dtype itemsize");
                logical_dimension =
                    stored_columns /
                    static_cast<int64_t>(itemsize);
            }
            if (logical_dimension < 0 ||
                logical_dimension >
                    std::numeric_limits<int64_t>::max() /
                        static_cast<int64_t>(itemsize) ||
                logical_dimension *
                        static_cast<int64_t>(itemsize) !=
                    stored_columns)
                throw std::invalid_argument(
                    "COLMAP database: descriptor cols disagree "
                    "with dtype and dim");
            result.image_descriptor_dimensions.push_back(
                logical_dimension);
            result.image_descriptor_dtypes.emplace_back(
                sio::dtype_info(dtype).name);
            result.descriptor_dimensions.push_back(
                logical_dimension);
        }
        std::sort(
            result.descriptor_dimensions.begin(),
            result.descriptor_dimensions.end());
        result.descriptor_dimensions.erase(
            std::unique(
                result.descriptor_dimensions.begin(),
                result.descriptor_dimensions.end()),
            result.descriptor_dimensions.end());
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
    result["profile"] = value.profile;
    result["profile_source_revision"] =
        value.profile_source_revision;
    result["schema_signature"] = value.schema_signature;
    result["application_id"] = value.application_id;
    result["user_version"] = value.user_version;
    result["num_rigs"] = value.rigs;
    result["num_rig_sensors"] = value.rig_sensors;
    result["num_frames"] = value.frames;
    result["num_frame_data"] = value.frame_data;
    result["num_pose_priors"] = value.pose_priors;
    result["pose_prior_layout"] =
        value.pose_prior_layout;
    result["num_keypoint_color_rows"] =
        value.keypoint_color_rows;
    result["num_match_score_pairs"] =
        value.match_score_pairs;
    result["num_image_qualities"] =
        value.image_qualities;
    result["num_pair_provenance"] =
        value.pair_provenance;
    result["num_markers"] = value.markers;
    result["num_marker_projections"] =
        value.marker_projections;
    result["num_videos"] = value.videos;
    result["num_video_frames"] = value.video_frames;
    result["maxx_schema_info_present"] =
        value.maxx_schema_info_present;
    result["maxx_schema_version"] =
        value.maxx_schema_version;
    result["maxx_minimum_reader_version"] =
        value.maxx_minimum_reader_version;
    result["maxx_producer_version"] =
        value.maxx_producer_version;
    result["maxx_producer_commit"] =
        value.maxx_producer_commit;
    result["num_cameras"] = value.cameras;
    result["num_images"] = value.images;
    result["num_keypoint_rows"] = value.keypoint_rows;
    result["num_descriptor_rows"] = value.descriptor_rows;
    result["num_match_pairs"] = value.match_pairs;
    result["num_verified_pairs"] = value.verified_pairs;
    result["num_matches"] = value.raw_matches;
    result["num_verified_matches"] = value.verified_matches;
    result["descriptor_dimensions"] =
        integer_list(value.descriptor_dimensions);
    result["image_ids"] = integer_list(value.image_ids);
    result["image_names"] = string_list(value.image_names);
    result["keypoint_counts"] = integer_list(value.keypoint_counts);
    result["keypoint_dimensions"] =
        integer_list(value.keypoint_dimensions);
    result["descriptor_counts"] =
        integer_list(value.descriptor_counts);
    result["image_descriptor_dimensions"] =
        integer_list(value.image_descriptor_dimensions);
    result["image_descriptor_dtypes"] =
        string_list(value.image_descriptor_dtypes);
    result["sqlite_version"] = nb::str(sqlite3_libversion());
    return result;
}

nb::tuple profile_catalog() {
    const auto &profiles = colmap_db_profile_specs();
    nb::tuple result = nb::steal<nb::tuple>(
        PyTuple_New(static_cast<Py_ssize_t>(profiles.size())));
    if (!result.is_valid()) throw nb::python_error();
    for (size_t index = 0; index < profiles.size(); ++index) {
        const ColmapDbProfileSpec &profile = profiles[index];
        nb::dict item;
        item["name"] = profile.name;
        item["source_revision"] = profile.source_revision;
        item["application_id"] = profile.application_id;
        item["user_version"] = profile.user_version;
        item["typed_descriptors"] =
            profile.typed_descriptors;
        item["generalized_pose_priors"] =
            profile.generalized_pose_priors;
        item["recovered_two_view_cameras"] =
            profile.recovered_two_view_cameras;
        item["maxx_extensions"] = profile.maxx_extensions;
        item["has_ownership_row"] =
            profile.requires_maxx_schema_row;
        PyTuple_SetItem(
            result.ptr(), static_cast<Py_ssize_t>(index),
            item.release().ptr());
    }
    return result;
}

nb::dict conversion_report(
    const ColmapDatabase &value,
    const std::string &target_profile) {
    validate_colmap_database(
        value, "COLMAP database conversion report");
    const ColmapDbProfileSpec &profile =
        profile_spec(target_profile);
    const std::vector<std::string> issues =
        profile_incompatibilities(value, profile);
    nb::dict identity_changes;
    if (value.profile != target_profile)
        identity_changes["profile"] =
            nb::make_tuple(value.profile, target_profile);
    if (value.application_id != profile.application_id)
        identity_changes["application_id"] =
            nb::make_tuple(
                value.application_id, profile.application_id);
    if (value.user_version != profile.user_version)
        identity_changes["user_version"] =
            nb::make_tuple(
                value.user_version, profile.user_version);
    nb::dict result;
    result["source_profile"] = value.profile;
    result["target_profile"] = target_profile;
    result["writable"] = issues.empty();
    result["identity_changes"] = identity_changes;
    result["incompatibilities"] = nb::cast(issues);
    return result;
}

std::string profile_schema(const std::string &name) {
    for (const ColmapDbProfileSpec &profile :
         colmap_db_profile_specs())
        if (name == profile.name)
            return profile.schema_sql;
    throw std::invalid_argument(
        "COLMAP database: unknown profile '" + name + "'");
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
           const std::string &path,
           size_t test_fail_after,
           const std::string &profile) {
            nb::gil_scoped_release release;
            write_database(
                value, path, profile, test_fail_after);
        },
        "database"_a, "path"_a,
        "_test_fail_after"_a = 0,
        "profile"_a = "",
        "Write a COLMAP SQLite database transactionally, "
        "using the legacy hybrid profile unless explicitly selected.");
    module.def(
        "inspect_colmap_db", &inspection_dict,
        "path"_a,
        "Inspect COLMAP database row counts and metadata "
        "without reading BLOB payloads.");
    module.def(
        "_colmap_db_profiles", &profile_catalog,
        "Return the exact repository-owned COLMAP database "
        "profile catalog.");
    module.def(
        "_colmap_db_conversion_report", &conversion_report,
        "database"_a, "profile"_a,
        "Analyze an exact COLMAP target profile without "
        "touching a destination.");
    module.def(
        "_colmap_db_profile_schema", &profile_schema,
        "name"_a,
        "Return exact DDL for one repository-owned COLMAP "
        "database profile.");
}
