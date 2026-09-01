from __future__ import annotations

import numpy as np
import pytest

import sceneio


def test_colmap_equirectangular_axes_and_roundtrip():
    xy = np.array(
        [
            [200.0, 100.0],
            [300.0, 100.0],
            [100.0, 100.0],
            [200.0, 0.0],
            [200.0, 200.0],
        ]
    )
    rays = sceneio.spherical_pixels_to_rays(xy, 400, 200)
    np.testing.assert_allclose(
        rays,
        np.array(
            [
                [0.0, 0.0, 1.0],
                [1.0, 0.0, 0.0],
                [-1.0, 0.0, 0.0],
                [0.0, -1.0, 0.0],
                [0.0, 1.0, 0.0],
            ]
        ),
        atol=1e-15,
    )

    samples = np.array([[20.0, 30.0], [120.0, 80.0], [210.0, 110.0], [390.0, 170.0]])
    np.testing.assert_allclose(
        sceneio.rays_to_spherical_pixels(
            sceneio.spherical_pixels_to_rays(samples, 400, 200),
            400,
            200,
        ),
        samples,
        atol=1e-12,
    )


def test_crop_local_geometry_and_colmap_camera():
    crop = sceneio.image(
        np.zeros((2, 3, 3), np.uint8),
        projection="equirectangular",
        projection_canvas_width=8,
        projection_canvas_height=4,
        projection_crop_left=3,
        projection_crop_top=1,
    )
    np.testing.assert_allclose(
        sceneio.equirectangular_pixels_to_rays(crop, [[1.0, 1.0]]),
        [[0.0, 0.0, 1.0]],
        atol=1e-15,
    )
    np.testing.assert_allclose(
        sceneio.rays_to_equirectangular_pixels(crop, [[0.0, 0.0, 1.0]]),
        [[1.0, 1.0]],
        atol=1e-15,
    )
    with pytest.raises(sceneio.ContractViolation, match="cropped panoramas"):
        sceneio.equirectangular_camera(crop)

    full = sceneio.image(
        np.zeros((4, 8, 3), np.uint8),
        projection="equirectangular",
    )
    camera = sceneio.equirectangular_camera(full)
    assert camera.model_id == 17
    assert camera.model == "EQUIRECTANGULAR"
    assert (camera.width, camera.height) == (8, 4)
    np.testing.assert_array_equal(camera.params, [8.0, 4.0])


def test_explicit_equirectangular_read_and_strict_write(tmp_path):
    pixels = np.zeros((4, 8, 3), np.uint8)
    png = tmp_path / "pano.png"
    sceneio.write(sceneio.image(pixels), png)

    generic = sceneio.read(png)
    assert generic.projection == "unknown"
    pano = sceneio.read_equirectangular(png)
    assert pano.projection == "equirectangular"
    assert pano.is_full_sphere
    with pytest.raises(sceneio.FormatError, match=r"cannot preserve Image\.projection"):
        sceneio.write(pano, tmp_path / "copy.png")

    jpeg = tmp_path / "pano.jpg"
    sceneio.write(pano, jpeg)
    decoded = sceneio.read(jpeg)
    assert decoded.projection == "equirectangular"
    assert decoded.is_full_sphere
    inspection = sceneio.inspect(jpeg)
    assert inspection.metadata["projection"] == "equirectangular"
    assert inspection.metadata["projection_canvas_width"] == 8
    assert inspection.metadata["projection_canvas_height"] == 4
    assert inspection.metadata["is_full_sphere"] is True


@pytest.mark.parametrize(
    ("function", "value", "match"),
    [
        (sceneio.spherical_pixels_to_rays, [[1.0, np.nan]], "finite"),
        (sceneio.rays_to_spherical_pixels, [[0.0, 0.0, 0.0]], "non-zero"),
    ],
)
def test_spherical_geometry_rejects_invalid_inputs(function, value, match):
    with pytest.raises(sceneio.ContractViolation, match=match):
        function(value, 8, 4)
