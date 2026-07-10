#include <neeh/core.hpp>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cctype>
#include <cmath>
#include <iomanip>
#include <limits>
#include <sstream>

namespace neeh {
namespace {

void require_finite(double value, const char* field) {
    if (!std::isfinite(value)) {
        throw Error(ErrorCode::invalid_argument, std::string(field) + " must be finite");
    }
}

void validate_author(Author author) {
    if (author != Author::user && author != Author::agent) {
        throw Error(ErrorCode::invalid_argument, "unknown stroke author");
    }
}

void validate_brush(Brush brush) {
    if (brush != Brush::pen && brush != Brush::marker && brush != Brush::highlighter) {
        throw Error(ErrorCode::invalid_argument, "unknown brush");
    }
}

bool is_hex_digit(char value) noexcept {
    return (value >= '0' && value <= '9') || (value >= 'a' && value <= 'f') ||
           (value >= 'A' && value <= 'F');
}

void validate_color(std::string_view color, const char* field) {
    if ((color.size() != 4 && color.size() != 7) || color.front() != '#' ||
        !std::all_of(color.begin() + 1, color.end(), is_hex_digit)) {
        throw Error(
            ErrorCode::invalid_argument,
            std::string(field) + " must be #rgb or #rrggbb");
    }
}

bool blank(std::string_view value) noexcept {
    return value.empty() || std::all_of(value.begin(), value.end(), [](char character) {
               return std::isspace(static_cast<unsigned char>(character)) != 0;
           });
}

std::string id_or_generate(std::optional<std::string> id, std::string_view prefix) {
    if (!id.has_value()) {
        return generate_id(prefix);
    }
    if (blank(*id)) {
        throw Error(ErrorCode::invalid_argument, "id must be a non-empty, non-blank string");
    }
    return std::move(*id);
}

} // namespace

Error::Error(ErrorCode code, std::string message)
    : std::runtime_error(std::move(message)), code_(code) {}

ErrorCode Error::code() const noexcept {
    return code_;
}

Point Point::translated(double dx, double dy) const {
    require_finite(dx, "dx");
    require_finite(dy, "dy");
    const double translated_x = x + dx;
    const double translated_y = y + dy;
    require_finite(translated_x, "translated point.x");
    require_finite(translated_y, "translated point.y");
    return Point {translated_x, translated_y, t_ms, pressure, tilt_x, tilt_y};
}

BoundingBox::BoundingBox(double min_x, double min_y, double max_x, double max_y)
    : min_x_(min_x), min_y_(min_y), max_x_(max_x), max_y_(max_y) {
    require_finite(min_x_, "min_x");
    require_finite(min_y_, "min_y");
    require_finite(max_x_, "max_x");
    require_finite(max_y_, "max_y");
    if (max_x_ < min_x_ || max_y_ < min_y_) {
        throw Error(ErrorCode::invalid_argument, "inverted bounding box");
    }
}

double BoundingBox::min_x() const noexcept { return min_x_; }
double BoundingBox::min_y() const noexcept { return min_y_; }
double BoundingBox::max_x() const noexcept { return max_x_; }
double BoundingBox::max_y() const noexcept { return max_y_; }
double BoundingBox::width() const noexcept { return max_x_ - min_x_; }
double BoundingBox::height() const noexcept { return max_y_ - min_y_; }

std::pair<double, double> BoundingBox::center() const noexcept {
    return {(min_x_ + max_x_) / 2.0, (min_y_ + max_y_) / 2.0};
}

bool BoundingBox::contains(double x, double y) const noexcept {
    return min_x_ <= x && x <= max_x_ && min_y_ <= y && y <= max_y_;
}

bool BoundingBox::contains(const BoundingBox& other) const noexcept {
    return other.min_x_ >= min_x_ && other.max_x_ <= max_x_ &&
           other.min_y_ >= min_y_ && other.max_y_ <= max_y_;
}

bool BoundingBox::intersects(const BoundingBox& other) const noexcept {
    return !(other.min_x_ > max_x_ || other.max_x_ < min_x_ ||
             other.min_y_ > max_y_ || other.max_y_ < min_y_);
}

BoundingBox BoundingBox::united(const BoundingBox& other) const {
    return BoundingBox(
        std::min(min_x_, other.min_x_),
        std::min(min_y_, other.min_y_),
        std::max(max_x_, other.max_x_),
        std::max(max_y_, other.max_y_));
}

BoundingBox BoundingBox::expanded(double margin) const {
    require_finite(margin, "margin");
    return BoundingBox(min_x_ - margin, min_y_ - margin, max_x_ + margin, max_y_ + margin);
}

BoundingBox BoundingBox::from_points(const std::vector<Point>& points) {
    if (points.empty()) {
        throw Error(ErrorCode::invalid_argument, "cannot compute a bounding box of zero points");
    }
    double min_x = points.front().x;
    double min_y = points.front().y;
    double max_x = points.front().x;
    double max_y = points.front().y;
    for (const auto& point : points) {
        require_finite(point.x, "point.x");
        require_finite(point.y, "point.y");
        min_x = std::min(min_x, point.x);
        min_y = std::min(min_y, point.y);
        max_x = std::max(max_x, point.x);
        max_y = std::max(max_y, point.y);
    }
    return BoundingBox(min_x, min_y, max_x, max_y);
}

std::optional<BoundingBox> BoundingBox::union_all(const std::vector<BoundingBox>& boxes) {
    if (boxes.empty()) {
        return std::nullopt;
    }
    BoundingBox result = boxes.front();
    for (std::size_t index = 1; index < boxes.size(); ++index) {
        result = result.united(boxes[index]);
    }
    return result;
}

StrokeStyle::StrokeStyle(std::string color, double width, Brush brush, double opacity)
    : color_(std::move(color)), width_(width), brush_(brush), opacity_(opacity) {
    validate_color(color_, "stroke color");
    require_finite(width_, "stroke width");
    require_finite(opacity_, "stroke opacity");
    validate_brush(brush_);
    if (width_ <= 0.0) {
        throw Error(ErrorCode::invalid_argument, "stroke width must be positive");
    }
    if (opacity_ <= 0.0 || opacity_ > 1.0) {
        throw Error(ErrorCode::invalid_argument, "stroke opacity must be in (0, 1]");
    }
}

const std::string& StrokeStyle::color() const noexcept { return color_; }
double StrokeStyle::width() const noexcept { return width_; }
Brush StrokeStyle::brush() const noexcept { return brush_; }
double StrokeStyle::opacity() const noexcept { return opacity_; }

StrokeStyle StrokeStyle::highlighter(std::string color, double width) {
    return StrokeStyle(std::move(color), width, Brush::highlighter, 0.35);
}

Stroke::Stroke(
    std::vector<Point> points,
    StrokeStyle style,
    std::optional<std::string> id,
    Author author,
    std::int64_t created_at_ms)
    : points_(std::move(points)),
      style_(std::move(style)),
      id_(id_or_generate(std::move(id), "st")),
      author_(author),
      created_at_ms_(created_at_ms == use_current_time ? current_time_ms() : created_at_ms) {
    validate_author(author_);
    if (points_.empty()) {
        throw Error(ErrorCode::invalid_argument, "a stroke needs at least one point");
    }
    if (created_at_ms_ < 0) {
        throw Error(ErrorCode::invalid_argument, "stroke created_at_ms must be non-negative");
    }
    std::int64_t previous_t_ms = points_.front().t_ms;
    for (const auto& point : points_) {
        require_finite(point.x, "point.x");
        require_finite(point.y, "point.y");
        require_finite(point.pressure, "point.pressure");
        require_finite(point.tilt_x, "point.tilt_x");
        require_finite(point.tilt_y, "point.tilt_y");
        if (point.t_ms < 0) {
            throw Error(ErrorCode::invalid_argument, "point t_ms must be non-negative");
        }
        if (point.t_ms < previous_t_ms) {
            throw Error(ErrorCode::invalid_argument, "stroke point t_ms values must be non-decreasing");
        }
        if (point.pressure < 0.0F || point.pressure > 1.0F) {
            throw Error(ErrorCode::invalid_argument, "point pressure must be in [0, 1]");
        }
        if (point.tilt_x < -90.0F || point.tilt_x > 90.0F ||
            point.tilt_y < -90.0F || point.tilt_y > 90.0F) {
            throw Error(ErrorCode::invalid_argument, "point tilt must be in [-90, 90]");
        }
        previous_t_ms = point.t_ms;
    }
}

const std::vector<Point>& Stroke::points() const noexcept { return points_; }
const StrokeStyle& Stroke::style() const noexcept { return style_; }
const std::string& Stroke::id() const noexcept { return id_; }
Author Stroke::author() const noexcept { return author_; }
std::int64_t Stroke::created_at_ms() const noexcept { return created_at_ms_; }

BoundingBox Stroke::bbox() const {
    return BoundingBox::from_points(points_);
}

std::int64_t Stroke::duration_ms() const noexcept {
    const long double duration = static_cast<long double>(points_.back().t_ms) -
                                 static_cast<long double>(points_.front().t_ms);
    if (duration > static_cast<long double>(std::numeric_limits<std::int64_t>::max())) {
        return std::numeric_limits<std::int64_t>::max();
    }
    if (duration < static_cast<long double>(std::numeric_limits<std::int64_t>::min())) {
        return std::numeric_limits<std::int64_t>::min();
    }
    return static_cast<std::int64_t>(duration);
}

Stroke Stroke::translated(double dx, double dy) const {
    std::vector<Point> translated_points;
    translated_points.reserve(points_.size());
    for (const auto& point : points_) {
        translated_points.push_back(point.translated(dx, dy));
    }
    return Stroke(std::move(translated_points), style_, id_, author_, created_at_ms_);
}

Stroke Stroke::with_style(StrokeStyle style) const {
    return Stroke(points_, std::move(style), id_, author_, created_at_ms_);
}

Layer::Layer(
    std::string name,
    Author author,
    std::optional<std::string> id,
    bool visible,
    bool locked)
    : name_(std::move(name)),
      author_(author),
      id_(id_or_generate(std::move(id), "ly")),
      visible_(visible),
      locked_(locked) {
    validate_author(author_);
    if (blank(name_)) {
        throw Error(ErrorCode::invalid_argument, "layer name must be non-empty and non-blank");
    }
}

const std::string& Layer::name() const noexcept { return name_; }
Author Layer::author() const noexcept { return author_; }
const std::string& Layer::id() const noexcept { return id_; }
bool Layer::visible() const noexcept { return visible_; }
bool Layer::locked() const noexcept { return locked_; }
const std::vector<Stroke>& Layer::strokes() const noexcept { return strokes_; }
void Layer::set_visible(bool visible) noexcept { visible_ = visible; }
void Layer::set_locked(bool locked) noexcept { locked_ = locked; }

const Stroke& Layer::add(Stroke stroke) {
    if (locked_) {
        throw Error(ErrorCode::locked, "layer '" + name_ + "' is locked");
    }
    if (get(stroke.id()) != nullptr) {
        throw Error(ErrorCode::conflict, "duplicate stroke id: " + stroke.id());
    }
    strokes_.push_back(std::move(stroke));
    return strokes_.back();
}

std::optional<Stroke> Layer::remove(std::string_view stroke_id) {
    if (locked_) {
        throw Error(ErrorCode::locked, "layer '" + name_ + "' is locked");
    }
    const auto found = std::find_if(strokes_.begin(), strokes_.end(), [&](const Stroke& stroke) {
        return stroke.id() == stroke_id;
    });
    if (found == strokes_.end()) {
        return std::nullopt;
    }
    Stroke removed = std::move(*found);
    strokes_.erase(found);
    return removed;
}

const Stroke& Layer::replace(Stroke stroke) {
    if (locked_) {
        throw Error(ErrorCode::locked, "layer '" + name_ + "' is locked");
    }
    const auto found = std::find_if(strokes_.begin(), strokes_.end(), [&](const Stroke& current) {
        return current.id() == stroke.id();
    });
    if (found == strokes_.end()) {
        throw Error(ErrorCode::not_found, "stroke not found: " + stroke.id());
    }
    *found = std::move(stroke);
    return *found;
}

const Stroke* Layer::get(std::string_view stroke_id) const noexcept {
    const auto found = std::find_if(strokes_.begin(), strokes_.end(), [&](const Stroke& stroke) {
        return stroke.id() == stroke_id;
    });
    return found == strokes_.end() ? nullptr : &*found;
}

std::vector<const Stroke*> Layer::strokes_in(const BoundingBox& region) const {
    std::vector<const Stroke*> result;
    for (const auto& stroke : strokes_) {
        if (region.intersects(stroke.bbox())) {
            result.push_back(&stroke);
        }
    }
    return result;
}

std::optional<BoundingBox> Layer::bbox() const {
    std::vector<BoundingBox> boxes;
    boxes.reserve(strokes_.size());
    for (const auto& stroke : strokes_) {
        boxes.push_back(stroke.bbox());
    }
    return BoundingBox::union_all(boxes);
}

Page::Page(
    double width,
    double height,
    std::string background,
    std::optional<std::string> id,
    bool create_default_layer)
    : width_(width),
      height_(height),
      background_(std::move(background)),
      id_(id_or_generate(std::move(id), "pg")) {
    require_finite(width_, "page width");
    require_finite(height_, "page height");
    if (width_ <= 0.0 || height_ <= 0.0) {
        throw Error(ErrorCode::invalid_argument, "page dimensions must be positive");
    }
    validate_color(background_, "page background");
    if (create_default_layer) {
        layers_.emplace_back("ink", Author::user);
    }
}

double Page::width() const noexcept { return width_; }
double Page::height() const noexcept { return height_; }
const std::string& Page::background() const noexcept { return background_; }
const std::string& Page::id() const noexcept { return id_; }
BoundingBox Page::rect() const { return BoundingBox(0.0, 0.0, width_, height_); }
const std::vector<Layer>& Page::layers() const noexcept { return layers_; }

Layer* Page::layer(std::size_t index) noexcept {
    return index < layers_.size() ? &layers_[index] : nullptr;
}

const Layer* Page::layer(std::size_t index) const noexcept {
    return index < layers_.size() ? &layers_[index] : nullptr;
}

Layer* Page::layer(std::string_view id_or_name) noexcept {
    for (auto& candidate : layers_) {
        if (candidate.id() == id_or_name) {
            return &candidate;
        }
    }
    for (auto& candidate : layers_) {
        if (candidate.name() == id_or_name) {
            return &candidate;
        }
    }
    return nullptr;
}

const Layer* Page::layer(std::string_view id_or_name) const noexcept {
    for (const auto& candidate : layers_) {
        if (candidate.id() == id_or_name) {
            return &candidate;
        }
    }
    for (const auto& candidate : layers_) {
        if (candidate.name() == id_or_name) {
            return &candidate;
        }
    }
    return nullptr;
}

Layer& Page::add_layer(Layer layer_value) {
    if (layer(layer_value.id()) != nullptr) {
        throw Error(ErrorCode::conflict, "duplicate layer id: " + layer_value.id());
    }
    layers_.push_back(std::move(layer_value));
    return layers_.back();
}

Layer& Page::add_layer(std::string name, Author author) {
    return add_layer(Layer(std::move(name), author));
}

std::optional<Layer> Page::remove_layer(std::string_view layer_id) {
    const auto found = std::find_if(layers_.begin(), layers_.end(), [&](const Layer& candidate) {
        return candidate.id() == layer_id;
    });
    if (found == layers_.end()) {
        return std::nullopt;
    }
    if (found->locked()) {
        throw Error(ErrorCode::locked, "layer '" + found->name() + "' is locked");
    }
    Layer removed = std::move(*found);
    layers_.erase(found);
    return removed;
}

Layer& Page::agent_layer() {
    for (auto& candidate : layers_) {
        if (candidate.author() == Author::agent && !candidate.locked()) {
            return candidate;
        }
    }
    return add_layer("agent", Author::agent);
}

const Stroke& Page::add_stroke(Stroke stroke, std::string_view layer_id_or_name) {
    if (find(stroke.id()).has_value()) {
        throw Error(ErrorCode::conflict, "duplicate stroke id on page: " + stroke.id());
    }
    Layer* destination = nullptr;
    if (!layer_id_or_name.empty()) {
        destination = layer(layer_id_or_name);
        if (destination == nullptr) {
            throw Error(ErrorCode::not_found, "layer not found: " + std::string(layer_id_or_name));
        }
    } else if (stroke.author() == Author::agent) {
        for (auto& candidate : layers_) {
            if (candidate.author() == Author::agent && !candidate.locked()) {
                destination = &candidate;
                break;
            }
        }
    } else {
        destination = layer("ink");
        if (destination == nullptr || destination->locked()) {
            destination = nullptr;
            for (auto& candidate : layers_) {
                if (candidate.author() == Author::user && !candidate.locked()) {
                    destination = &candidate;
                    break;
                }
            }
        }
    }
    if (destination == nullptr) {
        const bool agent = stroke.author() == Author::agent;
        Layer created(agent ? "agent" : "ink", stroke.author());
        created.add(std::move(stroke));
        Layer& added = add_layer(std::move(created));
        return added.strokes().back();
    }
    return destination->add(std::move(stroke));
}

std::optional<Stroke> Page::remove_stroke(std::string_view stroke_id) {
    for (auto& candidate : layers_) {
        if (candidate.get(stroke_id) != nullptr) {
            return candidate.remove(stroke_id);
        }
    }
    return std::nullopt;
}

const Stroke& Page::translate_stroke(std::string_view stroke_id, double dx, double dy) {
    const auto location = find(stroke_id);
    if (!location.has_value()) {
        throw Error(ErrorCode::not_found, "stroke not found: " + std::string(stroke_id));
    }
    Layer& owner = layers_[location->layer_index];
    const Stroke transformed = owner.strokes()[location->stroke_index].translated(dx, dy);
    return owner.replace(transformed);
}

const Stroke& Page::restyle_stroke(std::string_view stroke_id, StrokeStyle style) {
    const auto location = find(stroke_id);
    if (!location.has_value()) {
        throw Error(ErrorCode::not_found, "stroke not found: " + std::string(stroke_id));
    }
    Layer& owner = layers_[location->layer_index];
    const Stroke transformed = owner.strokes()[location->stroke_index].with_style(std::move(style));
    return owner.replace(transformed);
}

std::optional<StrokeLocation> Page::find(std::string_view stroke_id) const noexcept {
    for (std::size_t layer_index = 0; layer_index < layers_.size(); ++layer_index) {
        const auto& strokes = layers_[layer_index].strokes();
        for (std::size_t stroke_index = 0; stroke_index < strokes.size(); ++stroke_index) {
            if (strokes[stroke_index].id() == stroke_id) {
                return StrokeLocation {layer_index, stroke_index};
            }
        }
    }
    return std::nullopt;
}

std::vector<const Stroke*> Page::all_strokes(bool visible_only) const {
    std::vector<const Stroke*> result;
    for (const auto& candidate : layers_) {
        if (visible_only && !candidate.visible()) {
            continue;
        }
        for (const auto& stroke : candidate.strokes()) {
            result.push_back(&stroke);
        }
    }
    return result;
}

std::vector<const Stroke*> Page::strokes_in(const BoundingBox& region, bool visible_only) const {
    std::vector<const Stroke*> result;
    for (const auto& candidate : layers_) {
        if (visible_only && !candidate.visible()) {
            continue;
        }
        auto matches = candidate.strokes_in(region);
        result.insert(result.end(), matches.begin(), matches.end());
    }
    return result;
}

std::vector<const Stroke*> Page::strokes_since(std::int64_t epoch_ms) const {
    if (epoch_ms < 0) {
        throw Error(ErrorCode::invalid_argument, "epoch_ms must be non-negative");
    }
    std::vector<const Stroke*> result;
    for (const auto* stroke : all_strokes(false)) {
        if (stroke->created_at_ms() >= epoch_ms) {
            result.push_back(stroke);
        }
    }
    return result;
}

std::optional<BoundingBox> Page::content_bbox() const {
    std::vector<BoundingBox> boxes;
    for (const auto& candidate : layers_) {
        const auto candidate_box = candidate.bbox();
        if (candidate_box.has_value()) {
            boxes.push_back(*candidate_box);
        }
    }
    return BoundingBox::union_all(boxes);
}

Document::Document(
    std::string title,
    std::optional<std::string> id,
    std::int64_t created_at_ms,
    bool create_default_page)
    : title_(std::move(title)),
      id_(id_or_generate(std::move(id), "doc")),
      created_at_ms_(created_at_ms == Stroke::use_current_time ? current_time_ms() : created_at_ms) {
    if (created_at_ms_ < 0) {
        throw Error(ErrorCode::invalid_argument, "document created_at_ms must be non-negative");
    }
    if (create_default_page) {
        pages_.emplace_back();
    }
}

const std::string& Document::title() const noexcept { return title_; }
const std::string& Document::id() const noexcept { return id_; }
std::int64_t Document::created_at_ms() const noexcept { return created_at_ms_; }
const std::vector<Page>& Document::pages() const noexcept { return pages_; }
void Document::set_title(std::string title) { title_ = std::move(title); }

Page* Document::page(std::size_t index) noexcept {
    return index < pages_.size() ? &pages_[index] : nullptr;
}

const Page* Document::page(std::size_t index) const noexcept {
    return index < pages_.size() ? &pages_[index] : nullptr;
}

Page* Document::page(std::string_view page_id) noexcept {
    const auto found = std::find_if(pages_.begin(), pages_.end(), [&](const Page& candidate) {
        return candidate.id() == page_id;
    });
    return found == pages_.end() ? nullptr : &*found;
}

const Page* Document::page(std::string_view page_id) const noexcept {
    const auto found = std::find_if(pages_.begin(), pages_.end(), [&](const Page& candidate) {
        return candidate.id() == page_id;
    });
    return found == pages_.end() ? nullptr : &*found;
}

Page& Document::add_page(Page page_value) {
    if (page(page_value.id()) != nullptr) {
        throw Error(ErrorCode::conflict, "duplicate page id: " + page_value.id());
    }
    pages_.push_back(std::move(page_value));
    return pages_.back();
}

Page& Document::new_page(double width, double height, std::string background) {
    return add_page(Page(width, height, std::move(background)));
}

std::optional<Page> Document::remove_page(std::string_view page_id) {
    const auto found = std::find_if(pages_.begin(), pages_.end(), [&](const Page& candidate) {
        return candidate.id() == page_id;
    });
    if (found == pages_.end()) {
        return std::nullopt;
    }
    Page removed = std::move(*found);
    pages_.erase(found);
    return removed;
}

std::optional<Page> Document::remove_page(std::size_t index) {
    if (index >= pages_.size()) {
        return std::nullopt;
    }
    Page removed = std::move(pages_[index]);
    pages_.erase(pages_.begin() + static_cast<std::ptrdiff_t>(index));
    return removed;
}

std::int64_t current_time_ms() noexcept {
    const auto now = std::chrono::system_clock::now().time_since_epoch();
    return std::chrono::duration_cast<std::chrono::milliseconds>(now).count();
}

std::string generate_id(std::string_view prefix) {
    if (prefix.empty()) {
        throw Error(ErrorCode::invalid_argument, "id prefix cannot be empty");
    }
    static std::atomic<std::uint64_t> sequence {0};
    const auto ticks = std::chrono::duration_cast<std::chrono::microseconds>(
                           std::chrono::system_clock::now().time_since_epoch())
                           .count();
    const auto suffix = sequence.fetch_add(1, std::memory_order_relaxed);
    std::ostringstream stream;
    stream << prefix << '_' << std::hex << static_cast<std::uint64_t>(ticks) << '_' << suffix;
    return stream.str();
}

} // namespace neeh
