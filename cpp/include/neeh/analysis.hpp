#ifndef NEEH_ANALYSIS_HPP
#define NEEH_ANALYSIS_HPP

#include <neeh/core.hpp>
#include <neeh/export.h>

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

// Deterministic, bounded ink measurements: the native counterpart of the
// Python `ink-analysis/v1` measurement operations. Semantics intentionally
// mirror neeh/agents/analyzers.py so both hosts compute identical answers:
//   - start/end times are created_at_ms plus first/last point t_ms;
//   - latest_mark orders by (end_ms, start_ms, page order);
//   - creation_order sorts by (start_ms, end_ms, page order);
//   - direction uses the same 8-way compass with a closed-or-stationary
//     threshold of max(4.0, bbox diagonal * 0.12).
// Inference operations (cross-out/connector/grouping candidates) remain
// Python-only; they depend on the timeline recognizer stack.

namespace neeh::analysis {

enum class Direction : std::uint8_t {
    right = 0,
    down_right = 1,
    down = 2,
    down_left = 3,
    left = 4,
    up_left = 5,
    up = 6,
    up_right = 7,
    closed_or_stationary = 8,
};

NEEH_API const char* direction_name(Direction direction) noexcept;

struct NEEH_API MarkAnalysis {
    std::string id;
    std::int64_t start_ms = 0;
    std::int64_t end_ms = 0;
    std::int64_t duration_ms = 0;
    BoundingBox bbox {0.0, 0.0, 0.0, 0.0};
    double center_x = 0.0;
    double center_y = 0.0;
    bool upper_half = false; // relative to the page mid-height
    bool left_half = false;  // relative to the page mid-width
    Direction direction = Direction::closed_or_stationary;
    double path_length = 0.0;
    double pressure_mean = 0.0;
    double pressure_min = 0.0;
    double pressure_max = 0.0;
};

struct NEEH_API OrderEntry {
    std::size_t rank = 0; // 1-based, chronological
    std::string id;
    std::int64_t start_ms = 0;
    std::int64_t end_ms = 0;
};

struct NEEH_API Crossing {
    std::string a;
    std::string b;
    double x = 0.0;
    double y = 0.0;
};

struct NEEH_API Collision {
    std::string a;
    std::string b;
    BoundingBox overlap {0.0, 0.0, 0.0, 0.0};
};

struct NEEH_API ContainmentResult {
    std::vector<std::string> contained; // bbox fully inside the region
    std::vector<std::string> partial;   // bbox intersecting the boundary
};

struct NEEH_API EndpointInfo {
    std::string id;
    Point start;
    Point end;
    double displacement = 0.0;
    Direction direction = Direction::closed_or_stationary;
};

// Analyze one stroke against a page-sized frame (page width/height decide the
// vertical/horizontal halves).
NEEH_API MarkAnalysis analyze_stroke(const Stroke& stroke, double page_width, double page_height);

// The most recently finished visible stroke, or nullopt on an empty page.
NEEH_API std::optional<MarkAnalysis> latest_mark(const Page& page);

// Chronological order of the requested visible strokes. Unknown ids raise
// Error{not_found}; an empty id list raises Error{invalid_argument}.
NEEH_API std::vector<OrderEntry> creation_order(
    const Page& page,
    const std::vector<std::string>& stroke_ids);

// Per-stroke dynamics for the requested visible strokes, in page order.
NEEH_API std::vector<MarkAnalysis> stroke_dynamics(
    const Page& page,
    const std::vector<std::string>& stroke_ids);

// Visible strokes split into fully-contained vs partially-overlapping a region.
NEEH_API ContainmentResult containment(const Page& page, const BoundingBox& region);

// Exact polyline crossings between visible stroke pairs (bbox-prefiltered).
NEEH_API std::vector<Crossing> intersections(const Page& page, std::size_t limit = 16);

// Bounding-box overlap pairs between visible strokes, with the overlap box.
NEEH_API std::vector<Collision> spatial_collisions(const Page& page, std::size_t limit = 16);

// Exact first/last coordinates of the requested visible strokes.
NEEH_API std::vector<EndpointInfo> endpoints(
    const Page& page,
    const std::vector<std::string>& stroke_ids);

} // namespace neeh::analysis

#endif
