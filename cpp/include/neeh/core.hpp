#ifndef NEEH_CORE_HPP
#define NEEH_CORE_HPP

#include <neeh/export.h>

#include <cstddef>
#include <cstdint>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace neeh {

enum class ErrorCode : std::uint32_t {
    ok = 0,
    invalid_argument = 1,
    out_of_range = 2,
    not_found = 3,
    locked = 4,
    conflict = 5,
    buffer_too_small = 6,
    out_of_memory = 7,
    internal = 8,
};

class NEEH_API Error final : public std::runtime_error {
public:
    Error(ErrorCode code, std::string message);
    ErrorCode code() const noexcept;

private:
    ErrorCode code_;
};

enum class Author : std::uint8_t {
    user = 0,
    agent = 1,
};

enum class Brush : std::uint8_t {
    pen = 0,
    marker = 1,
    highlighter = 2,
};

struct NEEH_API Point {
    double x = 0.0;
    double y = 0.0;
    std::int64_t t_ms = 0;
    float pressure = 1.0F;
    float tilt_x = 0.0F;
    float tilt_y = 0.0F;

    Point translated(double dx, double dy) const;
};

class NEEH_API BoundingBox final {
public:
    BoundingBox(double min_x, double min_y, double max_x, double max_y);

    double min_x() const noexcept;
    double min_y() const noexcept;
    double max_x() const noexcept;
    double max_y() const noexcept;
    double width() const noexcept;
    double height() const noexcept;
    std::pair<double, double> center() const noexcept;

    bool contains(double x, double y) const noexcept;
    bool contains(const BoundingBox& other) const noexcept;
    bool intersects(const BoundingBox& other) const noexcept;
    BoundingBox united(const BoundingBox& other) const;
    BoundingBox expanded(double margin) const;

    static BoundingBox from_points(const std::vector<Point>& points);
    static std::optional<BoundingBox> union_all(const std::vector<BoundingBox>& boxes);

private:
    double min_x_;
    double min_y_;
    double max_x_;
    double max_y_;
};

class NEEH_API StrokeStyle final {
public:
    StrokeStyle(
        std::string color = "#1a1a1a",
        double width = 2.0,
        Brush brush = Brush::pen,
        double opacity = 1.0);

    const std::string& color() const noexcept;
    double width() const noexcept;
    Brush brush() const noexcept;
    double opacity() const noexcept;

    static StrokeStyle highlighter(std::string color = "#ffe066", double width = 18.0);

private:
    std::string color_;
    double width_;
    Brush brush_;
    double opacity_;
};

class NEEH_API Stroke final {
public:
    static constexpr std::int64_t use_current_time =
        std::numeric_limits<std::int64_t>::min();

    Stroke(
        std::vector<Point> points,
        StrokeStyle style = StrokeStyle {},
        std::optional<std::string> id = std::nullopt,
        Author author = Author::user,
        std::int64_t created_at_ms = use_current_time);

    const std::vector<Point>& points() const noexcept;
    const StrokeStyle& style() const noexcept;
    const std::string& id() const noexcept;
    Author author() const noexcept;
    std::int64_t created_at_ms() const noexcept;

    BoundingBox bbox() const;
    std::int64_t duration_ms() const noexcept;
    Stroke translated(double dx, double dy) const;
    Stroke with_style(StrokeStyle style) const;

private:
    std::vector<Point> points_;
    StrokeStyle style_;
    std::string id_;
    Author author_;
    std::int64_t created_at_ms_;
};

class NEEH_API Layer final {
public:
    Layer(
        std::string name = "ink",
        Author author = Author::user,
        std::optional<std::string> id = std::nullopt,
        bool visible = true,
        bool locked = false);

    const std::string& name() const noexcept;
    Author author() const noexcept;
    const std::string& id() const noexcept;
    bool visible() const noexcept;
    bool locked() const noexcept;
    const std::vector<Stroke>& strokes() const noexcept;

    void set_visible(bool visible) noexcept;
    void set_locked(bool locked) noexcept;

    const Stroke& add(Stroke stroke);
    std::optional<Stroke> remove(std::string_view stroke_id);
    const Stroke& replace(Stroke stroke);
    const Stroke* get(std::string_view stroke_id) const noexcept;
    std::vector<const Stroke*> strokes_in(const BoundingBox& region) const;
    std::optional<BoundingBox> bbox() const;

private:
    std::string name_;
    Author author_;
    std::string id_;
    bool visible_;
    bool locked_;
    std::vector<Stroke> strokes_;
};

struct NEEH_API StrokeLocation {
    std::size_t layer_index = 0;
    std::size_t stroke_index = 0;
};

class NEEH_API Page final {
public:
    static constexpr double default_width = 1000.0;
    static constexpr double default_height = 1414.0;

    Page(
        double width = default_width,
        double height = default_height,
        std::string background = "#ffffff",
        std::optional<std::string> id = std::nullopt,
        bool create_default_layer = true);

    double width() const noexcept;
    double height() const noexcept;
    const std::string& background() const noexcept;
    const std::string& id() const noexcept;
    BoundingBox rect() const;
    const std::vector<Layer>& layers() const noexcept;

    Layer* layer(std::size_t index) noexcept;
    const Layer* layer(std::size_t index) const noexcept;
    Layer* layer(std::string_view id_or_name) noexcept;
    const Layer* layer(std::string_view id_or_name) const noexcept;

    Layer& add_layer(Layer layer);
    Layer& add_layer(std::string name, Author author = Author::user);
    std::optional<Layer> remove_layer(std::string_view layer_id);
    Layer& agent_layer();

    const Stroke& add_stroke(Stroke stroke, std::string_view layer_id_or_name = {});
    std::optional<Stroke> remove_stroke(std::string_view stroke_id);
    const Stroke& translate_stroke(std::string_view stroke_id, double dx, double dy);
    const Stroke& restyle_stroke(std::string_view stroke_id, StrokeStyle style);

    std::optional<StrokeLocation> find(std::string_view stroke_id) const noexcept;
    std::vector<const Stroke*> all_strokes(bool visible_only = false) const;
    std::vector<const Stroke*> strokes_in(
        const BoundingBox& region,
        bool visible_only = false) const;
    std::vector<const Stroke*> strokes_since(std::int64_t epoch_ms) const;
    std::optional<BoundingBox> content_bbox() const;

private:
    double width_;
    double height_;
    std::string background_;
    std::string id_;
    std::vector<Layer> layers_;
};

class NEEH_API Document final {
public:
    Document(
        std::string title = "Untitled",
        std::optional<std::string> id = std::nullopt,
        std::int64_t created_at_ms = Stroke::use_current_time,
        bool create_default_page = true);

    const std::string& title() const noexcept;
    const std::string& id() const noexcept;
    std::int64_t created_at_ms() const noexcept;
    const std::vector<Page>& pages() const noexcept;

    void set_title(std::string title);
    Page* page(std::size_t index) noexcept;
    const Page* page(std::size_t index) const noexcept;
    Page* page(std::string_view page_id) noexcept;
    const Page* page(std::string_view page_id) const noexcept;

    Page& add_page(Page page);
    Page& new_page(
        double width = Page::default_width,
        double height = Page::default_height,
        std::string background = "#ffffff");
    std::optional<Page> remove_page(std::string_view page_id);
    std::optional<Page> remove_page(std::size_t index);

private:
    std::string title_;
    std::string id_;
    std::int64_t created_at_ms_;
    std::vector<Page> pages_;
};

NEEH_API std::int64_t current_time_ms() noexcept;
NEEH_API std::string generate_id(std::string_view prefix);

} // namespace neeh

#endif
