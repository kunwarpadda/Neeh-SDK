#include <neeh/render.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <iomanip>
#include <limits>
#include <locale>
#include <sstream>

namespace neeh {
namespace {

std::string format_number(double value) {
    std::ostringstream stream;
    stream.imbue(std::locale::classic());
    stream << std::fixed << std::setprecision(2) << value;
    std::string text = stream.str();
    while (text.size() > 1 && text.back() == '0') {
        text.pop_back();
    }
    if (!text.empty() && text.back() == '.') {
        text.pop_back();
    }
    if (text == "-0") {
        text = "0";
    }
    return text;
}

std::string escape_xml(std::string_view text) {
    std::string escaped;
    escaped.reserve(text.size());
    for (const char character : text) {
        switch (character) {
        case '&': escaped += "&amp;"; break;
        case '<': escaped += "&lt;"; break;
        case '>': escaped += "&gt;"; break;
        case '"': escaped += "&quot;"; break;
        case '\'': escaped += "&apos;"; break;
        default: escaped.push_back(character); break;
        }
    }
    return escaped;
}

void require_scale(double scale) {
    if (!std::isfinite(scale) || scale <= 0.0) {
        throw Error(ErrorCode::invalid_argument, "render scale must be finite and positive");
    }
}

std::string stroke_svg(const Stroke& stroke) {
    const auto& style = stroke.style();
    const auto opacity = style.opacity() < 1.0
                             ? " opacity=\"" + format_number(style.opacity()) + "\""
                             : std::string {};
    const auto color = escape_xml(style.color());
    if (stroke.points().size() == 1) {
        const auto& point = stroke.points().front();
        return "<circle cx=\"" + format_number(point.x) + "\" cy=\"" +
               format_number(point.y) + "\" r=\"" + format_number(style.width() / 2.0) +
               "\" fill=\"" + color + "\"" + opacity + "/>";
    }

    std::string points;
    for (const auto& point : stroke.points()) {
        if (!points.empty()) {
            points.push_back(' ');
        }
        points += format_number(point.x) + "," + format_number(point.y);
    }
    const char* line_cap = style.brush() == Brush::highlighter ? "butt" : "round";
    return "<polyline points=\"" + points + "\" fill=\"none\" stroke=\"" + color +
           "\" stroke-width=\"" + format_number(style.width()) + "\" stroke-linecap=\"" +
           line_cap + "\" stroke-linejoin=\"round\"" + opacity + "/>";
}

struct Color {
    std::uint8_t red;
    std::uint8_t green;
    std::uint8_t blue;
    std::uint8_t alpha;
};

int hex_digit(char value) {
    if (value >= '0' && value <= '9') return value - '0';
    if (value >= 'a' && value <= 'f') return value - 'a' + 10;
    if (value >= 'A' && value <= 'F') return value - 'A' + 10;
    return -1;
}

std::uint8_t hex_byte(char high, char low, bool* valid) {
    const int first = hex_digit(high);
    const int second = hex_digit(low);
    if (first < 0 || second < 0) {
        *valid = false;
        return 0;
    }
    return static_cast<std::uint8_t>((first << 4) | second);
}

Color parse_color(std::string_view text, Color fallback) {
    if (text == "black") return Color {0, 0, 0, 255};
    if (text == "white") return Color {255, 255, 255, 255};
    if (text == "transparent") return Color {0, 0, 0, 0};
    if (text.empty() || text.front() != '#') return fallback;

    if (text.size() == 4 || text.size() == 5) {
        std::array<int, 4> digits {0, 0, 0, 15};
        for (std::size_t index = 1; index < text.size(); ++index) {
            digits[index - 1] = hex_digit(text[index]);
            if (digits[index - 1] < 0) return fallback;
        }
        return Color {
            static_cast<std::uint8_t>(digits[0] * 17),
            static_cast<std::uint8_t>(digits[1] * 17),
            static_cast<std::uint8_t>(digits[2] * 17),
            static_cast<std::uint8_t>(digits[3] * 17)};
    }

    if (text.size() == 7 || text.size() == 9) {
        bool valid = true;
        const auto red = hex_byte(text[1], text[2], &valid);
        const auto green = hex_byte(text[3], text[4], &valid);
        const auto blue = hex_byte(text[5], text[6], &valid);
        const auto alpha = text.size() == 9
                               ? hex_byte(text[7], text[8], &valid)
                               : static_cast<std::uint8_t>(255);
        return valid ? Color {red, green, blue, alpha} : fallback;
    }

    return fallback;
}

void blend_pixel(std::vector<std::uint8_t>& pixels, std::size_t offset, Color color, double opacity) {
    const double source_alpha = std::clamp(opacity, 0.0, 1.0) *
                                (static_cast<double>(color.alpha) / 255.0);
    const double destination_alpha = static_cast<double>(pixels[offset + 3]) / 255.0;
    const double output_alpha = source_alpha + destination_alpha * (1.0 - source_alpha);
    if (output_alpha <= 0.0) {
        pixels[offset] = pixels[offset + 1] = pixels[offset + 2] = pixels[offset + 3] = 0;
        return;
    }
    const auto channel = [&](std::uint8_t source, std::uint8_t destination) {
        const double value = (static_cast<double>(source) * source_alpha +
                              static_cast<double>(destination) * destination_alpha *
                                  (1.0 - source_alpha)) /
                             output_alpha;
        return static_cast<std::uint8_t>(std::clamp(std::lround(value), 0L, 255L));
    };
    pixels[offset] = channel(color.red, pixels[offset]);
    pixels[offset + 1] = channel(color.green, pixels[offset + 1]);
    pixels[offset + 2] = channel(color.blue, pixels[offset + 2]);
    pixels[offset + 3] = static_cast<std::uint8_t>(
        std::clamp(std::lround(output_alpha * 255.0), 0L, 255L));
}

void fill(std::vector<std::uint8_t>& pixels, Color color) {
    for (std::size_t offset = 0; offset < pixels.size(); offset += 4) {
        pixels[offset] = color.red;
        pixels[offset + 1] = color.green;
        pixels[offset + 2] = color.blue;
        pixels[offset + 3] = color.alpha;
    }
}

struct PixelPoint {
    double x;
    double y;
    double radius;
};

bool intersects_with_margin(
    const BoundingBox& region,
    const BoundingBox& box,
    double margin) noexcept {
    const long double expanded_min_x = static_cast<long double>(box.min_x()) - margin;
    const long double expanded_min_y = static_cast<long double>(box.min_y()) - margin;
    const long double expanded_max_x = static_cast<long double>(box.max_x()) + margin;
    const long double expanded_max_y = static_cast<long double>(box.max_y()) + margin;
    return !(expanded_min_x > region.max_x() || expanded_max_x < region.min_x() ||
             expanded_min_y > region.max_y() || expanded_max_y < region.min_y());
}

double pixel_coordinate(double coordinate, double origin, double scale, double extent) noexcept {
    const long double transformed =
        (static_cast<long double>(coordinate) - origin) * static_cast<long double>(scale);
    const long double guard = 65536.0L;
    if (!std::isfinite(transformed)) {
        return transformed < 0.0L ? -static_cast<double>(guard)
                                  : static_cast<double>(extent + guard);
    }
    return static_cast<double>(std::clamp(
        transformed,
        -guard,
        static_cast<long double>(extent) + guard));
}

double pixel_radius(double width, double scale, double pressure, double extent) noexcept {
    const long double requested = static_cast<long double>(width) * scale * pressure / 2.0L;
    const long double limit = std::max(1.0L, static_cast<long double>(extent) * 2.0L);
    if (!std::isfinite(requested) || requested > limit) {
        return static_cast<double>(limit);
    }
    return static_cast<double>(std::max(0.0L, requested));
}

void draw_segment(
    std::vector<std::uint8_t>& pixels,
    std::uint32_t width,
    std::uint32_t height,
    const PixelPoint& start,
    const PixelPoint& end,
    Color color,
    double opacity) {
    const double max_radius = std::max(start.radius, end.radius);
    const auto clamp_index = [](double value, int upper) {
        return static_cast<int>(std::clamp(value, 0.0, static_cast<double>(upper)));
    };
    const int min_x = clamp_index(
        std::floor(std::min(start.x, end.x) - max_radius - 1.0),
        static_cast<int>(width) - 1);
    const int min_y = clamp_index(
        std::floor(std::min(start.y, end.y) - max_radius - 1.0),
        static_cast<int>(height) - 1);
    const int max_x = clamp_index(
        std::ceil(std::max(start.x, end.x) + max_radius + 1.0),
        static_cast<int>(width) - 1);
    const int max_y = clamp_index(
        std::ceil(std::max(start.y, end.y) + max_radius + 1.0),
        static_cast<int>(height) - 1);

    const double delta_x = end.x - start.x;
    const double delta_y = end.y - start.y;
    const double length_squared = delta_x * delta_x + delta_y * delta_y;
    for (int y = min_y; y <= max_y; ++y) {
        for (int x = min_x; x <= max_x; ++x) {
            const double sample_x = static_cast<double>(x) + 0.5;
            const double sample_y = static_cast<double>(y) + 0.5;
            double position = 0.0;
            if (length_squared > 1e-12) {
                position = ((sample_x - start.x) * delta_x + (sample_y - start.y) * delta_y) /
                           length_squared;
                position = std::clamp(position, 0.0, 1.0);
            }
            const double nearest_x = start.x + position * delta_x;
            const double nearest_y = start.y + position * delta_y;
            const double radius = start.radius + position * (end.radius - start.radius);
            const double distance_x = sample_x - nearest_x;
            const double distance_y = sample_y - nearest_y;
            const double distance = std::sqrt(distance_x * distance_x + distance_y * distance_y);
            if (distance <= radius) {
                const double coverage = std::clamp(radius + 0.5 - distance, 0.0, 1.0);
                const auto offset = (static_cast<std::size_t>(y) * width +
                                     static_cast<std::size_t>(x)) *
                                    4;
                blend_pixel(pixels, offset, color, opacity * coverage);
            }
        }
    }
}

std::uint32_t derive_dimension(double extent, double scale) {
    const double requested = std::ceil(std::max(extent, 1e-6) * scale);
    if (!std::isfinite(requested) || requested > 32768.0) {
        throw Error(ErrorCode::invalid_argument, "render dimension exceeds 32768 pixels");
    }
    return static_cast<std::uint32_t>(std::max(1.0, requested));
}

} // namespace

std::string SvgRenderer::render(const Page& page, const SvgRenderOptions& options) const {
    require_scale(options.scale);
    const BoundingBox region = options.region.value_or(page.rect());
    const double width = std::max(region.width(), 1e-6) * options.scale;
    const double height = std::max(region.height(), 1e-6) * options.scale;
    if (!std::isfinite(width) || !std::isfinite(height)) {
        throw Error(ErrorCode::invalid_argument, "render dimensions are not finite");
    }

    std::string svg = "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"" +
                      format_number(width) + "\" height=\"" + format_number(height) +
                      "\" viewBox=\"" + format_number(region.min_x()) + " " +
                      format_number(region.min_y()) + " " + format_number(region.width()) +
                      " " + format_number(region.height()) + "\">";
    svg += "<rect x=\"" + format_number(region.min_x()) + "\" y=\"" +
           format_number(region.min_y()) + "\" width=\"" + format_number(region.width()) +
           "\" height=\"" + format_number(region.height()) + "\" fill=\"" +
           escape_xml(page.background()) + "\"/>";
    for (const auto& layer : page.layers()) {
        if (!layer.visible()) {
            continue;
        }
        for (const auto& stroke : layer.strokes()) {
            if (intersects_with_margin(region, stroke.bbox(), stroke.style().width())) {
                svg += stroke_svg(stroke);
            }
        }
    }
    svg += "</svg>";
    return svg;
}

Image::Image(std::uint32_t width, std::uint32_t height, std::vector<std::uint8_t> rgba)
    : width_(width), height_(height), pixels_(std::move(rgba)) {
    if (width_ == 0 || height_ == 0) {
        throw Error(ErrorCode::invalid_argument, "image dimensions must be positive");
    }
    const auto expected = static_cast<std::uint64_t>(width_) * height_ * 4ULL;
    if (expected > std::numeric_limits<std::size_t>::max() || pixels_.size() != expected) {
        throw Error(ErrorCode::invalid_argument, "RGBA image size does not match its dimensions");
    }
}

std::uint32_t Image::width() const noexcept { return width_; }
std::uint32_t Image::height() const noexcept { return height_; }
std::size_t Image::stride() const noexcept { return static_cast<std::size_t>(width_) * 4; }
const std::vector<std::uint8_t>& Image::pixels() const noexcept { return pixels_; }

Image CpuRenderer::render(const Page& page, const CpuRenderOptions& options) const {
    require_scale(options.scale);
    const BoundingBox region = options.region.value_or(page.rect());
    const std::uint32_t width = options.width == 0
                                    ? derive_dimension(region.width(), options.scale)
                                    : options.width;
    const std::uint32_t height = options.height == 0
                                     ? derive_dimension(region.height(), options.scale)
                                     : options.height;
    if (width == 0 || height == 0 || width > 32768 || height > 32768) {
        throw Error(ErrorCode::invalid_argument, "render dimensions must be in [1, 32768]");
    }
    const auto pixel_count = static_cast<std::uint64_t>(width) * height;
    if (pixel_count > 64ULL * 1024ULL * 1024ULL) {
        throw Error(ErrorCode::invalid_argument, "render exceeds the 64-megapixel safety limit");
    }

    std::vector<std::uint8_t> pixels(static_cast<std::size_t>(pixel_count) * 4);
    fill(pixels, parse_color(page.background(), Color {255, 255, 255, 255}));

    const double region_width = std::max(region.width(), 1e-6);
    const double region_height = std::max(region.height(), 1e-6);
    const double scale_x = static_cast<double>(width) / region_width;
    const double scale_y = static_cast<double>(height) / region_height;
    const double width_scale = (scale_x + scale_y) / 2.0;

    for (const auto& layer : page.layers()) {
        if (!layer.visible()) {
            continue;
        }
        for (const auto& stroke : layer.strokes()) {
            if (!intersects_with_margin(region, stroke.bbox(), stroke.style().width())) {
                continue;
            }
            const Color color = parse_color(stroke.style().color(), Color {0, 0, 0, 255});
            std::vector<PixelPoint> points;
            points.reserve(stroke.points().size());
            for (const auto& point : stroke.points()) {
                const double pressure = std::clamp(static_cast<double>(point.pressure), 0.0, 1.0);
                points.push_back(PixelPoint {
                    pixel_coordinate(point.x, region.min_x(), scale_x, width),
                    pixel_coordinate(point.y, region.min_y(), scale_y, height),
                    pixel_radius(
                        stroke.style().width(),
                        width_scale,
                        pressure,
                        std::max(width, height))});
            }
            if (points.size() == 1) {
                draw_segment(
                    pixels,
                    width,
                    height,
                    points.front(),
                    points.front(),
                    color,
                    stroke.style().opacity());
                continue;
            }
            for (std::size_t index = 1; index < points.size(); ++index) {
                draw_segment(
                    pixels,
                    width,
                    height,
                    points[index - 1],
                    points[index],
                    color,
                    stroke.style().opacity());
            }
        }
    }
    return Image(width, height, std::move(pixels));
}

} // namespace neeh
