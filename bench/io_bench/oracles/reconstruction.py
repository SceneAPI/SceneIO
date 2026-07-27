"""Independent parsers and writers for reconstruction benchmark codecs."""

from __future__ import annotations

import csv
import io

import numpy as np

_EUROC_HEADER = (
    "#timestamp [ns]",
    "p_RS_R_x [m]",
    "p_RS_R_y [m]",
    "p_RS_R_z [m]",
    "q_RS_w []",
    "q_RS_x []",
    "q_RS_y []",
    "q_RS_z []",
    "v_RS_R_x [m s^-1]",
    "v_RS_R_y [m s^-1]",
    "v_RS_R_z [m s^-1]",
    "b_w_RS_S_x [rad s^-1]",
    "b_w_RS_S_y [rad s^-1]",
    "b_w_RS_S_z [rad s^-1]",
    "b_a_RS_S_x [m s^-2]",
    "b_a_RS_S_y [m s^-2]",
    "b_a_RS_S_z [m s^-2]",
)


def _euroc_oracle_write(payload):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(_EUROC_HEADER)
    combined = np.concatenate(
        (
            payload["positions"],
            payload["quaternions"],
            payload["velocities"],
            payload["gyro_biases"],
            payload["accel_biases"],
        ),
        axis=1,
    )
    for timestamp, values in zip(
        payload["timestamps"], combined, strict=True
    ):
        writer.writerow((int(timestamp), *map(float, values)))
    return output.getvalue().encode()


def _euroc_oracle_read(data):
    reader = csv.reader(io.StringIO(data.decode()))
    header = tuple(next(reader))
    if header != _EUROC_HEADER:
        raise ValueError("unexpected EuRoC header")
    rows = list(reader)
    return {
        "timestamps": np.asarray([int(row[0]) for row in rows], np.int64),
        "states": np.asarray(
            [[float(value) for value in row[1:]] for row in rows],
            np.float64,
        ),
    }


def _g2o_oracle_write(payload):
    lines = ["# independent g2o oracle"]
    for node_id, translation, quaternion in zip(
        payload["node_ids"],
        payload["node_translations"],
        payload["node_quaternions"],
        strict=True,
    ):
        values = (*translation, *quaternion)
        lines.append(
            "VERTEX_SE3:QUAT "
            + str(int(node_id))
            + " "
            + " ".join(f"{float(value):.17g}" for value in values)
        )
    lines.extend(
        f"FIX {int(node_id)}"
        for node_id, fixed in zip(
            payload["node_ids"], payload["fixed"], strict=True
        )
        if fixed
    )
    for endpoints, translation, quaternion, information in zip(
        payload["edge_endpoints"],
        payload["edge_translations"],
        payload["edge_quaternions"],
        payload["information_matrices"],
        strict=True,
    ):
        upper = (
            information[row, column]
            for row in range(6)
            for column in range(row, 6)
        )
        values = (*translation, *quaternion, *upper)
        lines.append(
            "EDGE_SE3:QUAT "
            + f"{int(endpoints[0])} {int(endpoints[1])} "
            + " ".join(f"{float(value):.17g}" for value in values)
        )
    return ("\n".join(lines) + "\n").encode()


def _g2o_oracle_read(data):
    node_ids = []
    node_translations = []
    node_quaternions = []
    fixed_node_ids = []
    edge_endpoints = []
    edge_translations = []
    edge_quaternions = []
    information_matrices = []
    for raw in data.splitlines():
        fields = raw.partition(b"#")[0].split()
        if not fields:
            continue
        if fields[0] == b"VERTEX_SE3:QUAT" and len(fields) == 9:
            values = [float(value) for value in fields[2:]]
            node_ids.append(int(fields[1]))
            node_translations.append(values[:3])
            node_quaternions.append(values[3:])
        elif fields[0] == b"EDGE_SE3:QUAT" and len(fields) == 31:
            values = [float(value) for value in fields[3:10]]
            upper = [float(value) for value in fields[10:]]
            information = np.zeros((6, 6), np.float64)
            index = 0
            for row in range(6):
                for column in range(row, 6):
                    information[row, column] = upper[index]
                    information[column, row] = upper[index]
                    index += 1
            edge_endpoints.append((int(fields[1]), int(fields[2])))
            edge_translations.append(values[:3])
            edge_quaternions.append(values[3:])
            information_matrices.append(information)
        elif fields[0] == b"FIX" and len(fields) == 2:
            fixed_node_ids.append(int(fields[1]))
        else:
            raise ValueError("unsupported g2o record")
    return {
        "node_ids": np.asarray(node_ids, np.int64),
        "node_translations": np.asarray(
            node_translations, np.float64
        ).reshape(-1, 3),
        "node_quaternions": np.asarray(
            node_quaternions, np.float64
        ).reshape(-1, 4),
        "fixed_node_ids": np.asarray(fixed_node_ids, np.int64),
        "edge_endpoints": np.asarray(edge_endpoints, np.int64).reshape(-1, 2),
        "edge_translations": np.asarray(
            edge_translations, np.float64
        ).reshape(-1, 3),
        "edge_quaternions": np.asarray(
            edge_quaternions, np.float64
        ).reshape(-1, 4),
        "information_matrices": np.asarray(
            information_matrices, np.float64
        ).reshape(-1, 6, 6),
    }


def _bal_oracle_write(payload):
    cameras = payload["cameras"]
    points = payload["points"]
    camera_indices = payload["camera_indices"]
    point_indices = payload["point_indices"]
    observations = payload["observations"]
    lines = [
        f"{len(cameras)} {len(points)} {len(observations)}",
    ]
    lines.extend(
        f"{int(camera)} {int(point)} {xy[0]:.17g} {xy[1]:.17g}"
        for camera, point, xy in zip(
            camera_indices,
            point_indices,
            observations,
            strict=True,
        )
    )
    lines.extend(f"{value:.17g}" for value in cameras.flat)
    lines.extend(f"{value:.17g}" for value in points.flat)
    return ("\n".join(lines) + "\n").encode()


def _bal_oracle_read(data):
    values = np.fromstring(data.decode("ascii"), sep=" ")
    if len(values) < 3:
        raise ValueError("truncated BAL header")
    cameras, points, observations = (
        int(values[0]),
        int(values[1]),
        int(values[2]),
    )
    expected = 3 + observations * 4 + cameras * 9 + points * 3
    if min(cameras, points, observations) < 0 or len(values) != expected:
        raise ValueError("invalid BAL token count")
    cursor = 3
    observed = values[cursor : cursor + observations * 4].reshape(
        observations, 4
    )
    cursor += observations * 4
    camera_values = values[cursor : cursor + cameras * 9].reshape(
        cameras, 9
    )
    cursor += cameras * 9
    point_values = values[cursor:].reshape(points, 3)
    return {
        "observations": observed,
        "cameras": camera_values,
        "points": point_values,
    }


__all__ = [
    "_EUROC_HEADER",
    "_bal_oracle_read",
    "_bal_oracle_write",
    "_euroc_oracle_read",
    "_euroc_oracle_write",
    "_g2o_oracle_read",
    "_g2o_oracle_write",
]
