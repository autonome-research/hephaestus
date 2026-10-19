"""Declared parser vocabulary from the exact pinned public build123d wheel.

Source: build123d-0.11.1-py3-none-any.whl, SHA256
4e95fa7ccbdc83e624313be492e7c4f5f0eb2ea1df36130eb718bb0c25a89e10.
Extracted from the literal __all__ assignment using ast.literal_eval, not by
executing third-party code on the host. namespace._build123d_exports validates
exact parity before every actual namespace construction. Upgrades must update
this declaration with their separately reviewed toolchain change.
"""

BUILD123D_EXPORTS = frozenset(
    """
MC MM CM M IN FT THOU UNITS_PER_METER G KG LB Align ApproxOption AngularDirection
CenterOf ContinuityLevel Extrinsic FontStyle FrameMethod GeomType HeadType Intrinsic
Keep Kind Sagitta LengthMode MeshType Mode NumberDisplay PageSize Tangency PositionMode
PrecisionMode Select Side SortBy TextAlign Transition Unit Until HexLocations
PolarLocations Locations GridLocations BuildLine BuildPart BuildSketch BaseLineObject
Airfoil Bezier BlendCurve BSpline CenterArc ConstrainedArcs ConstrainedLines
DoubleTangentArc EllipticalCenterArc EllipticalStartArc ParabolicCenterArc
HyperbolicCenterArc FilletPolyline Helix IntersectingLine Line PolarLine Polyline
RadiusArc SagittaArc Spline TangentArc JernArc ThreePointArc PointArcTangentLine
ArcArcTangentLine PointArcTangentArc ArcArcTangentArc ArrowHead Arrow BaseSketchObject
Circle Draft DimensionLine Ellipse ExtensionLine Polygon Rectangle RectangleRounded
RegularPolygon SlotArc SlotCenterPoint SlotCenterToCenter SlotOverall Text
TechnicalDrawing Trapezoid Triangle BasePartObject Box Cone ConvexPolyhedron
CounterBoreHole CounterSinkHole Cylinder Hole Sphere Torus Wedge BoundBox OrientedBoundBox
Rotation Rot Pos RotationLike ShapeList topo_distance_to Axis Color Curve Vector VectorLike
Vertex Edge Wire Face Matrix Solid Shell Part Plane Compound Location LocationEncoder
GeomEncoder Joint RigidJoint RevoluteJoint Sketch LinearJoint CylindricalJoint BallJoint
DraftAngleError FontManager Export2D ExportDXF ExportSVG LineType DotLength Mesher
detect_primitives import_brep import_dxf import_step import_stl import_svg
import_svg_as_buildline_code delta edges_to_wires new_edges pack polar available_fonts
solids faces wires edges vertices solid face wire edge vertex add bounding_box chamfer
draft extrude fillet full_round loft make_brake_formed make_face make_hull mirror offset
project project_workplane revolve scale section split sweep thicken trace
topo_explore_connected_edges topo_explore_common_vertex export_step export_gltf export_stl
export_brep export_to_pcbway
""".split()  # noqa: SIM905 - compact audited wheel-derived data, not hand-maintained logic
)
