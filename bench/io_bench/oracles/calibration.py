"""Independent or library-backed oracles for calibration codecs."""

from __future__ import annotations

import xml.etree.ElementTree as ET

try:
    import yaml
except Exception:
    yaml = None


def _yaml_oracle_write(payload):
    if yaml is None:
        raise RuntimeError("PyYAML unavailable")
    return yaml.safe_dump(payload, sort_keys=False).encode()


def _yaml_oracle_read(data):
    if yaml is None:
        raise RuntimeError("PyYAML unavailable")
    text = (
        data.decode()
        .replace("%YAML:1.0", "")
        .replace("!!opencv-matrix", "")
    )
    return yaml.safe_load(text)


def _xml_oracle_write(payload):
    root = ET.Element("opencv_storage")
    for name, value in payload.items():
        node = ET.SubElement(root, name)
        if isinstance(value, dict):
            node.set("type_id", "opencv-matrix")
            for child_name in ("rows", "cols", "dt", "data"):
                if child_name not in value:
                    continue
                child = ET.SubElement(node, child_name)
                child_value = value[child_name]
                child.text = (
                    " ".join(str(item) for item in child_value)
                    if isinstance(child_value, list)
                    else str(child_value)
                )
        else:
            node.text = str(value)
    return ET.tostring(root)


def _xml_oracle_read(data):
    return ET.fromstring(data)


__all__ = [
    "_xml_oracle_read",
    "_xml_oracle_write",
    "_yaml_oracle_read",
    "_yaml_oracle_write",
    "yaml",
]
