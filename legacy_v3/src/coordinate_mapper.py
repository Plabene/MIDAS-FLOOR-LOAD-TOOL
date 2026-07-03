from __future__ import annotations

from dataclasses import dataclass, field
from math import atan2, cos, hypot, sin
from typing import Sequence

import numpy as np
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform

Point2D = tuple[float, float]


@dataclass(frozen=True)
class TransformReport:
    mode: str
    rms_error: float = 0.0
    max_error: float = 0.0
    residuals: list[float] = field(default_factory=list)

    def to_record(self) -> dict:
        return {
            "mode": self.mode,
            "rms_error": self.rms_error,
            "max_error": self.max_error,
            "residuals": list(self.residuals),
        }


@dataclass(frozen=True)
class CoordinateMapper:
    matrix: np.ndarray
    report: TransformReport = field(default_factory=lambda: TransformReport(mode="identity"))

    @classmethod
    def identity(cls) -> "CoordinateMapper":
        return cls(np.eye(3, dtype=float), TransformReport(mode="identity"))

    @classmethod
    def from_control_points(
        cls,
        cad_points: Sequence[Point2D] | None,
        midas_points: Sequence[Point2D] | None,
    ) -> "CoordinateMapper":
        cad = _as_points(cad_points or [])
        midas = _as_points(midas_points or [])
        if not cad and not midas:
            return cls.identity()
        if len(cad) != len(midas):
            raise ValueError("CAD and MIDAS control point counts must match.")
        if len(cad) == 2:
            return cls(*_fit_similarity_2pt(cad, midas))
        if len(cad) >= 3:
            return cls(*_fit_affine(cad, midas))
        raise ValueError("Use either no control points, 2 control points, or 3+ control points.")

    def transform_point(self, point: Point2D) -> Point2D:
        vector = self.matrix @ np.array([float(point[0]), float(point[1]), 1.0], dtype=float)
        return (float(vector[0]), float(vector[1]))

    def transform_points(self, points: Sequence[Point2D]) -> list[Point2D]:
        if not points:
            return []
        array = np.asarray(points, dtype=float)
        ones = np.ones((array.shape[0], 1), dtype=float)
        mapped = np.hstack([array, ones]) @ self.matrix.T
        return [(float(row[0]), float(row[1])) for row in mapped]

    def transform_geometry(self, geometry: BaseGeometry) -> BaseGeometry:
        a, b, c = self.matrix[0, 0], self.matrix[0, 1], self.matrix[0, 2]
        d, e, f = self.matrix[1, 0], self.matrix[1, 1], self.matrix[1, 2]

        def apply(x, y, z=None):
            xx = np.asarray(x, dtype=float)
            yy = np.asarray(y, dtype=float)
            mapped_x = a * xx + b * yy + c
            mapped_y = d * xx + e * yy + f
            if z is None:
                return mapped_x, mapped_y
            return mapped_x, mapped_y, z

        return shapely_transform(apply, geometry)


def _fit_similarity_2pt(cad: list[Point2D], midas: list[Point2D]) -> tuple[np.ndarray, TransformReport]:
    src0, src1 = cad
    dst0, dst1 = midas
    src_vec = (src1[0] - src0[0], src1[1] - src0[1])
    dst_vec = (dst1[0] - dst0[0], dst1[1] - dst0[1])
    src_len = hypot(*src_vec)
    dst_len = hypot(*dst_vec)
    if src_len <= 1.0e-12:
        raise ValueError("CAD 2-point baseline length is zero.")
    scale = dst_len / src_len
    angle = atan2(dst_vec[1], dst_vec[0]) - atan2(src_vec[1], src_vec[0])
    ca = cos(angle)
    sa = sin(angle)
    linear = np.array([[scale * ca, -scale * sa], [scale * sa, scale * ca]], dtype=float)
    src0_array = np.array(src0, dtype=float)
    dst0_array = np.array(dst0, dtype=float)
    translation = dst0_array - linear @ src0_array
    matrix = np.array(
        [[linear[0, 0], linear[0, 1], translation[0]], [linear[1, 0], linear[1, 1], translation[1]], [0.0, 0.0, 1.0]],
        dtype=float,
    )
    report = _make_report("similarity_2pt", matrix, cad, midas)
    return matrix, report


def _fit_affine(cad: list[Point2D], midas: list[Point2D]) -> tuple[np.ndarray, TransformReport]:
    source = np.asarray(cad, dtype=float)
    target = np.asarray(midas, dtype=float)
    design = np.hstack([source, np.ones((source.shape[0], 1), dtype=float)])
    coeff, _residuals, _rank, _singular = np.linalg.lstsq(design, target, rcond=None)
    matrix = np.array(
        [[coeff[0, 0], coeff[1, 0], coeff[2, 0]], [coeff[0, 1], coeff[1, 1], coeff[2, 1]], [0.0, 0.0, 1.0]],
        dtype=float,
    )
    report = _make_report("affine_least_squares", matrix, cad, midas)
    return matrix, report


def _make_report(mode: str, matrix: np.ndarray, cad: list[Point2D], midas: list[Point2D]) -> TransformReport:
    if not cad:
        return TransformReport(mode=mode)
    source = np.asarray(cad, dtype=float)
    target = np.asarray(midas, dtype=float)
    mapped = np.hstack([source, np.ones((source.shape[0], 1), dtype=float)]) @ matrix.T
    errors = np.linalg.norm(mapped[:, :2] - target, axis=1)
    rms = float(np.sqrt(np.mean(errors**2))) if len(errors) else 0.0
    max_error = float(np.max(errors)) if len(errors) else 0.0
    return TransformReport(mode=mode, rms_error=rms, max_error=max_error, residuals=[float(value) for value in errors])


def _as_points(points: Sequence[Point2D]) -> list[Point2D]:
    return [(float(point[0]), float(point[1])) for point in points]