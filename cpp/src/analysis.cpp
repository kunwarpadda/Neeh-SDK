#include <neeh/analysis.hpp>

#include <algorithm>
#include <cmath>
#include <limits>
#include <unordered_map>
#include <unordered_set>

namespace neeh::analysis {

namespace {

constexpr double pi = 3.14159265358979323846;

std::int64_t start_ms(const Stroke& stroke) {
    return stroke.created_at_ms() + stroke.points().front().t_ms;
}

std::int64_t end_ms(const Stroke& stroke) {
    return stroke.created_at_ms() + stroke.points().back().t_ms;
}

double path_length(const Stroke& stroke) {
    double total = 0.0;
    const auto& pts = stroke.points();
    for (std::size_t i = 1; i < pts.size(); ++i) {
        total += std::hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y);
    }
    return total;
}

Direction direction_of(const Stroke& stroke) {
    const auto& pts = stroke.points();
    const auto& first = pts.front();
    const auto& last = pts.back();
    const double dx = last.x - first.x;
    const double dy = last.y - first.y;
    const double distance = std::hypot(dx, dy);
    const auto box = stroke.bbox();
    const double diagonal = std::hypot(box.width(), box.height());
    if (distance <= std::max(4.0, diagonal * 0.12)) {
        return Direction::closed_or_stationary;
    }
    const double angle = std::atan2(dy, dx);
    // nearbyint under the default FE_TONEAREST mode rounds half-to-even,
    // matching Python's round() on the compass index.
    const long index = static_cast<long>(std::nearbyint(angle / (pi / 4.0)));
    return static_cast<Direction>(((index % 8) + 8) % 8);
}

std::vector<const Stroke*> visible(const Page& page) {
    return page.all_strokes(/*visible_only=*/true);
}

std::unordered_map<std::string, std::size_t> page_order_of(
    const std::vector<const Stroke*>& strokes) {
    std::unordered_map<std::string, std::size_t> order;
    order.reserve(strokes.size());
    for (std::size_t i = 0; i < strokes.size(); ++i) {
        order.emplace(strokes[i]->id(), i);
    }
    return order;
}

std::vector<const Stroke*> select_requested(
    const Page& page,
    const std::vector<std::string>& stroke_ids,
    const char* operation) {
    if (stroke_ids.empty()) {
        throw Error(
            ErrorCode::invalid_argument,
            std::string(operation) + " requires at least one stroke id");
    }
    const auto strokes = visible(page);
    std::unordered_map<std::string, const Stroke*> by_id;
    by_id.reserve(strokes.size());
    for (const auto* stroke : strokes) {
        by_id.emplace(stroke->id(), stroke);
    }
    std::vector<const Stroke*> selected;
    std::unordered_set<std::string> seen;
    selected.reserve(stroke_ids.size());
    for (const auto& id : stroke_ids) {
        if (!seen.insert(id).second) {
            continue; // ignore duplicates, matching the Python de-dup
        }
        const auto found = by_id.find(id);
        if (found == by_id.end()) {
            throw Error(ErrorCode::not_found, "unknown visible stroke id: " + id);
        }
        selected.push_back(found->second);
    }
    return selected;
}

std::optional<std::pair<double, double>> segment_intersection(
    double x1, double y1, double x2, double y2,
    double x3, double y3, double x4, double y4) {
    const double denom = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3);
    if (denom == 0.0) {
        return std::nullopt; // parallel or collinear; overlap is not reported
    }
    const double t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / denom;
    const double u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / denom;
    if (t < 0.0 || t > 1.0 || u < 0.0 || u > 1.0) {
        return std::nullopt;
    }
    return std::make_pair(x1 + t * (x2 - x1), y1 + t * (y2 - y1));
}

std::optional<std::pair<double, double>> polyline_crossing(const Stroke& a, const Stroke& b) {
    const auto& ap = a.points();
    const auto& bp = b.points();
    for (std::size_t i = 0; i + 1 < ap.size(); ++i) {
        for (std::size_t j = 0; j + 1 < bp.size(); ++j) {
            const auto hit = segment_intersection(
                ap[i].x, ap[i].y, ap[i + 1].x, ap[i + 1].y,
                bp[j].x, bp[j].y, bp[j + 1].x, bp[j + 1].y);
            if (hit) {
                return hit;
            }
        }
    }
    return std::nullopt;
}

} // namespace

const char* direction_name(Direction direction) noexcept {
    switch (direction) {
    case Direction::right: return "right";
    case Direction::down_right: return "down-right";
    case Direction::down: return "down";
    case Direction::down_left: return "down-left";
    case Direction::left: return "left";
    case Direction::up_left: return "up-left";
    case Direction::up: return "up";
    case Direction::up_right: return "up-right";
    case Direction::closed_or_stationary: return "closed-or-stationary";
    }
    return "closed-or-stationary";
}

MarkAnalysis analyze_stroke(const Stroke& stroke, double page_width, double page_height) {
    MarkAnalysis out;
    out.id = stroke.id();
    out.start_ms = start_ms(stroke);
    out.end_ms = end_ms(stroke);
    out.duration_ms = stroke.duration_ms();
    out.bbox = stroke.bbox();
    const auto center = out.bbox.center();
    out.center_x = center.first;
    out.center_y = center.second;
    out.upper_half = out.center_y < page_height / 2.0;
    out.left_half = out.center_x < page_width / 2.0;
    out.direction = direction_of(stroke);
    out.path_length = path_length(stroke);
    double sum = 0.0;
    double mn = std::numeric_limits<double>::infinity();
    double mx = -std::numeric_limits<double>::infinity();
    for (const auto& point : stroke.points()) {
        sum += point.pressure;
        mn = std::min(mn, static_cast<double>(point.pressure));
        mx = std::max(mx, static_cast<double>(point.pressure));
    }
    const auto count = static_cast<double>(stroke.points().size());
    out.pressure_mean = sum / count;
    out.pressure_min = mn;
    out.pressure_max = mx;
    return out;
}

std::optional<MarkAnalysis> latest_mark(const Page& page) {
    const auto strokes = visible(page);
    if (strokes.empty()) {
        return std::nullopt;
    }
    const auto order = page_order_of(strokes);
    const Stroke* best = strokes.front();
    auto key = [&order](const Stroke* stroke) {
        return std::make_tuple(end_ms(*stroke), start_ms(*stroke), order.at(stroke->id()));
    };
    for (const auto* stroke : strokes) {
        if (key(stroke) > key(best)) {
            best = stroke;
        }
    }
    return analyze_stroke(*best, page.width(), page.height());
}

std::vector<OrderEntry> creation_order(
    const Page& page,
    const std::vector<std::string>& stroke_ids) {
    auto selected = select_requested(page, stroke_ids, "creation_order");
    const auto order = page_order_of(visible(page));
    std::sort(selected.begin(), selected.end(), [&order](const Stroke* a, const Stroke* b) {
        return std::make_tuple(start_ms(*a), end_ms(*a), order.at(a->id()))
            < std::make_tuple(start_ms(*b), end_ms(*b), order.at(b->id()));
    });
    std::vector<OrderEntry> out;
    out.reserve(selected.size());
    for (std::size_t i = 0; i < selected.size(); ++i) {
        out.push_back(OrderEntry {i + 1, selected[i]->id(), start_ms(*selected[i]), end_ms(*selected[i])});
    }
    return out;
}

std::vector<MarkAnalysis> stroke_dynamics(
    const Page& page,
    const std::vector<std::string>& stroke_ids) {
    auto selected = select_requested(page, stroke_ids, "stroke_dynamics");
    const auto order = page_order_of(visible(page));
    std::sort(selected.begin(), selected.end(), [&order](const Stroke* a, const Stroke* b) {
        return order.at(a->id()) < order.at(b->id());
    });
    std::vector<MarkAnalysis> out;
    out.reserve(selected.size());
    for (const auto* stroke : selected) {
        out.push_back(analyze_stroke(*stroke, page.width(), page.height()));
    }
    return out;
}

ContainmentResult containment(const Page& page, const BoundingBox& region) {
    ContainmentResult result;
    for (const auto* stroke : visible(page)) {
        const auto box = stroke->bbox();
        if (!region.intersects(box)) {
            continue;
        }
        if (region.contains(box)) {
            result.contained.push_back(stroke->id());
        } else {
            result.partial.push_back(stroke->id());
        }
    }
    return result;
}

std::vector<Crossing> intersections(const Page& page, std::size_t limit) {
    const auto strokes = visible(page);
    std::vector<Crossing> out;
    for (std::size_t i = 0; i < strokes.size() && out.size() < limit; ++i) {
        for (std::size_t j = i + 1; j < strokes.size() && out.size() < limit; ++j) {
            if (!strokes[i]->bbox().intersects(strokes[j]->bbox())) {
                continue; // exact crossing impossible without bbox overlap
            }
            const auto hit = polyline_crossing(*strokes[i], *strokes[j]);
            if (hit) {
                out.push_back(Crossing {strokes[i]->id(), strokes[j]->id(), hit->first, hit->second});
            }
        }
    }
    return out;
}

std::vector<Collision> spatial_collisions(const Page& page, std::size_t limit) {
    const auto strokes = visible(page);
    std::vector<Collision> out;
    for (std::size_t i = 0; i < strokes.size() && out.size() < limit; ++i) {
        const auto a = strokes[i]->bbox();
        for (std::size_t j = i + 1; j < strokes.size() && out.size() < limit; ++j) {
            const auto b = strokes[j]->bbox();
            if (!a.intersects(b)) {
                continue;
            }
            out.push_back(Collision {
                strokes[i]->id(),
                strokes[j]->id(),
                BoundingBox(
                    std::max(a.min_x(), b.min_x()),
                    std::max(a.min_y(), b.min_y()),
                    std::min(a.max_x(), b.max_x()),
                    std::min(a.max_y(), b.max_y())),
            });
        }
    }
    return out;
}

std::vector<EndpointInfo> endpoints(
    const Page& page,
    const std::vector<std::string>& stroke_ids) {
    auto selected = select_requested(page, stroke_ids, "endpoints");
    const auto order = page_order_of(visible(page));
    std::sort(selected.begin(), selected.end(), [&order](const Stroke* a, const Stroke* b) {
        return order.at(a->id()) < order.at(b->id());
    });
    std::vector<EndpointInfo> out;
    out.reserve(selected.size());
    for (const auto* stroke : selected) {
        EndpointInfo info;
        info.id = stroke->id();
        info.start = stroke->points().front();
        info.end = stroke->points().back();
        info.displacement = std::hypot(info.end.x - info.start.x, info.end.y - info.start.y);
        info.direction = direction_of(*stroke);
        out.push_back(std::move(info));
    }
    return out;
}

} // namespace neeh::analysis
